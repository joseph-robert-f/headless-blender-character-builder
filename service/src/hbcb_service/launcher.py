"""Fresh-process deterministic builder launcher with a scrubbed environment."""

from __future__ import annotations

import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional
from uuid import UUID

from .errors import WorkerError


IMAGE_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+-]{0,254}$")
IMAGE_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_LOG_TAIL_BYTES = 64 * 1024
MAX_PROCESS_TREE_PIDS = 4096
TERMINATION_GRACE_SECONDS = 2.0


class LaunchTermination(str, Enum):
    COMPLETED = "completed"
    CANCELED = "canceled"
    TIMED_OUT = "timed_out"
    LEASE_LOST = "lease_lost"


@dataclass(frozen=True)
class LaunchResult:
    attempt_id: UUID
    scratch_dir: Path
    output_dir: Path
    exit_code: int
    termination: LaunchTermination
    log_tail: bytes


class _TailBuffer:
    def __init__(self, maximum: int = MAX_LOG_TAIL_BYTES) -> None:
        self._maximum = maximum
        self._payload = bytearray()
        self._lock = threading.Lock()

    def append(self, chunk: bytes) -> None:
        with self._lock:
            self._payload.extend(chunk)
            if len(self._payload) > self._maximum:
                del self._payload[: len(self._payload) - self._maximum]

    def bytes(self) -> bytes:
        with self._lock:
            return bytes(self._payload)


def _drain(stream: object, tail: _TailBuffer) -> None:
    try:
        while True:
            chunk = stream.read(8192)  # type: ignore[attr-defined]
            if not chunk:
                return
            tail.append(bytes(chunk))
    except Exception:
        return


def _normalized_exit(return_code: int) -> int:
    if return_code < 0:
        return min(255, 128 + abs(return_code))
    return min(255, return_code)


def _process_parents() -> dict[int, int]:
    """Return a bounded PID-to-parent snapshot without trusting child input."""

    proc = Path("/proc")
    parents: dict[int, int] = {}
    if proc.is_dir():
        try:
            entries = proc.iterdir()
            for entry in entries:
                if len(parents) >= MAX_PROCESS_TREE_PIDS:
                    break
                if not entry.name.isascii() or not entry.name.isdigit():
                    continue
                try:
                    payload = (entry / "stat").read_text(encoding="ascii")
                    suffix = payload[payload.rfind(")") + 2 :].split()
                    pid = int(entry.name)
                    parent = int(suffix[1])
                except (OSError, UnicodeDecodeError, ValueError, IndexError):
                    continue
                parents[pid] = parent
        except OSError:
            pass
        if parents:
            return parents

    # Native macOS contributor tests have no /proc.  Production Linux uses the
    # branch above; this fixed system utility is only a bounded portability path.
    try:
        completed = subprocess.run(
            ("/bin/ps", "-axo", "pid=,ppid="),
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.SubprocessError):
        return parents
    if completed.returncode != 0 or len(completed.stdout) > 4 * 1024 * 1024:
        return parents
    for line in completed.stdout.splitlines()[:MAX_PROCESS_TREE_PIDS]:
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            pid, parent = (int(field) for field in fields)
        except ValueError:
            continue
        parents[pid] = parent
    return parents


def _descendants(root_pid: int) -> set[int]:
    parents = _process_parents()
    children: dict[int, list[int]] = {}
    for pid, parent in parents.items():
        children.setdefault(parent, []).append(pid)
    found: set[int] = set()
    pending = list(children.get(root_pid, ()))
    while pending and len(found) < MAX_PROCESS_TREE_PIDS:
        pid = pending.pop()
        if pid in found or pid <= 1 or pid == os.getpid():
            continue
        found.add(pid)
        pending.extend(children.get(pid, ()))
    return found


def _signal_processes(pids: set[int], signum: int) -> None:
    for pid in sorted(pids, reverse=True):
        if pid <= 1 or pid == os.getpid():
            continue
        try:
            os.kill(pid, signum)
        except OSError:
            continue


def _live_processes(pids: set[int]) -> set[int]:
    live: set[int] = set()
    for pid in pids:
        if pid <= 1 or pid == os.getpid():
            continue
        stat_path = Path("/proc") / str(pid) / "stat"
        if stat_path.parent.is_dir():
            try:
                payload = stat_path.read_text(encoding="ascii")
                state = payload[payload.rfind(")") + 2 :].split()[0]
            except (OSError, UnicodeDecodeError, IndexError):
                continue
            if state != "Z":
                live.add(pid)
            continue
        try:
            os.kill(pid, 0)
        except OSError:
            continue
        live.add(pid)
    return live


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if os.name != "nt":
        root_pid = process.pid
        # Freeze the wrapper first, then repeatedly discover and freeze its
        # descendants.  This captures Blender even though the immutable G4
        # builder starts it in another POSIX session/process group.
        _signal_processes({root_pid}, signal.SIGSTOP)
        descendants: set[int] = set()
        stable_passes = 0
        for _pass in range(8):
            observed = _descendants(root_pid)
            new = observed - descendants
            descendants.update(observed)
            _signal_processes(new, signal.SIGSTOP)
            if new:
                stable_passes = 0
            else:
                stable_passes += 1
                if stable_passes >= 2:
                    break
        targets = descendants | {root_pid}
        _signal_processes(targets, signal.SIGTERM)
        _signal_processes(targets, signal.SIGCONT)
        deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
        while time.monotonic() < deadline:
            live = _live_processes(targets)
            if process.poll() is not None:
                live.discard(root_pid)
            if not live:
                break
            time.sleep(0.05)
        # Reap the wrapper when possible, but never mistake its exit for proof
        # that the separately-sessioned Blender descendant also exited.
        try:
            process.wait(timeout=0.1)
        except (OSError, subprocess.TimeoutExpired):
            pass
        survivors = _live_processes(targets)
        if process.poll() is not None:
            survivors.discard(root_pid)
        if survivors or process.poll() is None:
            _signal_processes(survivors | {root_pid} | _descendants(root_pid), signal.SIGKILL)
            try:
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                return
        return
    try:
        process.terminate()
        process.wait(timeout=5)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return


class SubprocessBuilderLauncher:
    """Launch exactly ``builder build`` once per isolated scratch directory."""

    def __init__(
        self,
        *,
        builder_executable: Path,
        scratch_root: Path,
        image_reference: str,
        image_digest: Optional[str] = None,
        image_id: Optional[str] = None,
        timeout_seconds: int = 900,
        poll_seconds: float = 1.0,
        system_path: str = "/opt/blender/4.5/python/bin:/opt/blender:/usr/local/bin:/usr/bin:/bin",
    ) -> None:
        try:
            builder = builder_executable.resolve(strict=True)
            root = scratch_root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorkerError("launcher_path_invalid", "builder launcher path is unavailable") from exc
        if not builder.is_file() or not os.access(builder, os.X_OK):
            raise WorkerError("launcher_path_invalid", "builder launcher is not executable")
        if not root.is_dir() or root.is_symlink():
            raise WorkerError("scratch_root_invalid", "worker scratch root is unavailable")
        if IMAGE_REFERENCE_PATTERN.fullmatch(image_reference) is None:
            raise WorkerError("image_reference_invalid", "worker image reference is outside policy")
        for candidate in (image_digest, image_id):
            if candidate is not None and IMAGE_DIGEST_PATTERN.fullmatch(candidate) is None:
                raise WorkerError("image_digest_invalid", "worker image digest is outside policy")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 960:
            raise WorkerError("timeout_invalid", "worker timeout is outside policy")
        if isinstance(poll_seconds, bool) or not isinstance(poll_seconds, (int, float)) or not 0.05 <= float(poll_seconds) <= 5:
            raise WorkerError("poll_interval_invalid", "worker poll interval is outside policy")
        if not isinstance(system_path, str) or not 1 <= len(system_path) <= 1024 or "\x00" in system_path:
            raise WorkerError("path_invalid", "worker executable path is outside policy")
        self._builder = builder
        self._scratch_root = root
        self._image_reference = image_reference
        self._image_digest = image_digest
        self._image_id = image_id
        self._timeout_seconds = timeout_seconds
        self._poll_seconds = float(poll_seconds)
        self._system_path = system_path

    @staticmethod
    def _write_request(path: Path, payload: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise WorkerError("request_stage_failed", "build request could not be staged") from exc

    def _environment(self, scratch: Path) -> dict[str, str]:
        environment = {
            "HOME": str(scratch / "home"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": self._system_path,
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": str(scratch / "tmp"),
            "LIBGL_ALWAYS_SOFTWARE": "1",
            "HBCB_EXECUTION_MODE": "container",
            "HBCB_WORKER_IMAGE_REFERENCE": self._image_reference,
        }
        if self._image_digest is not None:
            environment["HBCB_WORKER_IMAGE_DIGEST"] = self._image_digest
        if self._image_id is not None:
            environment["HBCB_WORKER_IMAGE_ID"] = self._image_id
        return environment

    def execute(
        self,
        request_canonical: bytes,
        attempt_id: UUID,
        heartbeat: Callable[[], bool],
    ) -> LaunchResult:
        if not isinstance(request_canonical, bytes) or not 1 <= len(request_canonical) <= 64 * 1024:
            raise WorkerError("request_invalid", "canonical build request is outside policy")
        if not isinstance(attempt_id, UUID) or not callable(heartbeat):
            raise WorkerError("attempt_invalid", "worker attempt is invalid")
        try:
            scratch = Path(
                tempfile.mkdtemp(prefix=f"attempt-{attempt_id}-", dir=str(self._scratch_root))
            )
            scratch.chmod(0o700)
            (scratch / "home").mkdir(mode=0o700)
            (scratch / "tmp").mkdir(mode=0o700)
        except OSError as exc:
            raise WorkerError("scratch_create_failed", "worker scratch could not be created") from exc
        request_path = scratch / "request.json"
        output_path = scratch / "output"
        try:
            self._write_request(request_path, request_canonical)
            command = (
                str(self._builder),
                "build",
                "--request",
                str(request_path),
                "--output",
                str(output_path),
            )
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(scratch),
                    env=self._environment(scratch),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    start_new_session=os.name != "nt",
                )
            except OSError as exc:
                raise WorkerError("builder_start_failed", "fresh builder process could not be started") from exc
            tail = _TailBuffer()
            reader = threading.Thread(
                target=_drain,
                args=(process.stdout, tail),
                name=f"builder-log-{attempt_id}",
                daemon=True,
            )
            reader.start()
            deadline = time.monotonic() + self._timeout_seconds
            termination = LaunchTermination.COMPLETED
            while process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    termination = LaunchTermination.TIMED_OUT
                    _terminate(process)
                    break
                try:
                    process.wait(timeout=min(self._poll_seconds, remaining))
                except subprocess.TimeoutExpired:
                    try:
                        cancel_requested = bool(heartbeat())
                    except Exception:
                        termination = LaunchTermination.LEASE_LOST
                        _terminate(process)
                        break
                    if cancel_requested:
                        termination = LaunchTermination.CANCELED
                        _terminate(process)
                        break
            reader.join(timeout=5)
            if process.stdout is not None:
                try:
                    process.stdout.close()
                except OSError:
                    pass
            return_code = process.poll()
            if return_code is None:
                _terminate(process)
                return_code = process.poll()
            return LaunchResult(
                attempt_id=attempt_id,
                scratch_dir=scratch,
                output_dir=output_path,
                exit_code=_normalized_exit(255 if return_code is None else return_code),
                termination=termination,
                log_tail=tail.bytes(),
            )
        except Exception:
            try:
                self.cleanup(scratch)
            except WorkerError:
                pass
            raise

    def cleanup(self, scratch: Path) -> None:
        try:
            resolved = scratch.resolve(strict=True)
            metadata = scratch.lstat()
        except OSError as exc:
            raise WorkerError("scratch_cleanup_failed", "worker scratch could not be resolved") from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or scratch.is_symlink()
            or resolved.parent != self._scratch_root
            or not resolved.name.startswith("attempt-")
        ):
            raise WorkerError("scratch_cleanup_refused", "worker scratch cleanup target is unsafe")
        try:
            shutil.rmtree(resolved)
        except OSError as exc:
            raise WorkerError("scratch_cleanup_failed", "worker scratch could not be removed") from exc


__all__ = [
    "LaunchResult",
    "LaunchTermination",
    "SubprocessBuilderLauncher",
]
