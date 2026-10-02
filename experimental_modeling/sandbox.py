"""Experimental Docker isolation backend; see documented exact-commit CI evidence.

The Docker daemon and immutable image are trusted. No native fallback exists.
Each stage uses a fresh container; policy and acceptance stay in the parent.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import uuid


class SandboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class Limits:
    memory_bytes: int = 4 * 1024**3
    output_bytes: int = 512 * 1024**2
    max_files: int = 512
    log_bytes: int = 128 * 1024
    pids: int = 128
    cpus: int = 2
    timeout_seconds: int = 120

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in self.__dict__.values()):
            raise ValueError("sandbox limits must be positive integers")


def _path(path: Path) -> Path:
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlink input/output path")
    if any(c in str(path) for c in (",", "\n", "\r")):
        raise ValueError("invalid mount path")
    return path.resolve()


def _input(path: Path, directory: bool) -> Path:
    path = _path(path)
    if directory:
        if not path.is_dir():
            raise ValueError("source must be a directory")
        paths = path.rglob("*")
    else:
        if not path.is_file():
            raise ValueError("input must be a regular file")
        paths = [path]
    for entry in paths:
        mode = entry.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode) or entry.stat().st_nlink != 1:
            raise ValueError("inputs must contain only regular, non-hardlinked files")
    return path


def extract_output(archive: Path, output: Path, limits: Limits) -> None:
    """Never tar.extract: reject links, devices, traversal, duplicates and budgets."""
    seen: set[str] = set()
    total = count = 0
    with tarfile.open(archive, "r|*") as stream:
        for member in stream:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or "\\" in member.name:
                raise SandboxError("unsafe output archive path")
            if str(name) == "." and member.isdir():
                continue
            if str(name) in seen or len(str(name)) > 1024:
                raise SandboxError("duplicate or oversized output archive path")
            seen.add(str(name))
            count += 1
            if count > limits.max_files:
                raise SandboxError("output file-count limit")
            if not (member.isdir() or member.isfile()) or member.issparse():
                raise SandboxError("nonregular output archive entry")
            target = output.joinpath(*name.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            total += member.size
            if member.size < 0 or total > limits.output_bytes:
                raise SandboxError("output byte limit")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = stream.extractfile(member)
            if source is None:
                raise SandboxError("missing archive payload")
            with target.open("xb") as destination:
                shutil.copyfileobj(source, destination, length=64 * 1024)
            target.chmod(0o644)


class DockerSandbox:
    """Local Linux Docker only; image must be an existing exact sha256 image ID.

    run(stage, args, inputs, output, log): args are Blender arguments after the
    mandatory safe startup flags. Container paths are /inputs/<role> and /output.
    Inputs: author={source,params}; inspect={inspector,input}; roundtrip/reopen
    ={inspector,input,reference}. Output directory must exist and be empty.
    This API is for the trusted controller, never generated source.
    """
    security_boundary = "EXPERIMENTAL_DOCKER"
    blender = "/opt/blender/blender"
    container_env = {"PATH": "/opt/blender:/usr/bin:/bin", "HOME": "/output", "TMPDIR": "/output",
                     "PYTHONDONTWRITEBYTECODE": "1", "LIBGL_ALWAYS_SOFTWARE": "1",
                     "HBCB_EXECUTION_MODE": "container", "HBCB_WORKER_IMAGE_REFERENCE": "experimental",
                     "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"}

    def __init__(self, image_id: str, limits: Limits | None = None,
                 socket: Path = Path("/var/run/docker.sock"),
                 docker_executable: Path | None = None):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise ValueError("sandbox requires an immutable full sha256 image ID")
        self.image_id = image_id
        self.limits = limits or Limits()
        self.socket = Path(socket).absolute().resolve()
        if docker_executable is not None:
            candidate = Path(docker_executable)
            if not candidate.is_absolute() or not candidate.is_file() or not os.access(candidate, os.X_OK):
                raise ValueError("Docker executable must be an existing executable absolute path")
            self.docker = str(candidate)
        else:
            self.docker = shutil.which("docker")
        self.env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C.UTF-8"}

    def _command(self, *args: str) -> list[str]:
        if self.docker is None:
            raise SandboxError("SANDBOX_UNAVAILABLE: Docker CLI unavailable; no native fallback")
        return [self.docker, "--host", "unix://" + str(self.socket), *args]

    def _control(self, *args: str) -> str:
        try:
            result = subprocess.run(self._command(*args), env=self.env, capture_output=True,
                                    timeout=15, check=True)
            return result.stdout.decode("utf-8")
        except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
            raise SandboxError(f"SANDBOX_UNAVAILABLE: Docker control operation {args[0]} failed") from exc

    def verify_runtime(self) -> dict:
        info = json.loads(self._control("info", "--format", "{{json .}}"))
        security = info.get("SecurityOptions", [])
        if info.get("OSType") != "linux" or not any("name=seccomp" in x and "profile=builtin" in x for x in security):
            raise SandboxError("SANDBOX_UNAVAILABLE: Linux Docker with default seccomp required")
        if any(info.get(key) is not True for key in ("MemoryLimit", "PidsLimit", "CpuCfsQuota")):
            raise SandboxError("SANDBOX_UNAVAILABLE: mandatory cgroup limits unavailable")
        images = json.loads(self._control("image", "inspect", self.image_id))
        if len(images) != 1 or images[0].get("Id") != self.image_id or images[0].get("Os") != "linux":
            raise SandboxError("SANDBOX_UNAVAILABLE: exact Linux image ID not found")
        # Inherited image volumes would create unbounded writable mounts.
        if images[0].get("Config", {}).get("Volumes"):
            raise SandboxError("SANDBOX_UNAVAILABLE: image declares writable volumes")
        inherited = images[0].get("Config", {}).get("Env") or []
        if any(entry.partition("=")[0] not in self.container_env for entry in inherited):
            raise SandboxError("SANDBOX_UNAVAILABLE: unexpected inherited image environment")
        labels = images[0].get("Config", {}).get("Labels") or {}
        return {"image_id": self.image_id, "docker_version": info.get("ServerVersion"),
                "image_architecture": images[0].get("Architecture"),
                "blender_version": labels.get("org.blender.version"),
                "blender_archive_sha256": labels.get("org.blender.download.sha256")}

    def create_command(self, name: str, inputs: dict[str, Path], volume: str, *, exporter: bool = False) -> list[str]:
        lim = self.limits
        args = ["create", "--name", name, "--label", "experimental.modeling.owner=" + volume, "--pull=never", "--network=none", "--ipc=none",
                "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges=true",
                "--user=65532:65532", f"--pids-limit={lim.pids}", f"--cpus={lim.cpus}",
                f"--memory={lim.memory_bytes}", f"--memory-swap={lim.memory_bytes}",
                "--ulimit=core=0:0", "--ulimit=nofile=256:256",
                f"--ulimit=fsize={lim.output_bytes}:{lim.output_bytes}",
                f"--ulimit=cpu={lim.timeout_seconds}:{lim.timeout_seconds + 1}",
                "--log-driver=none", "--restart=no", "--no-healthcheck", "--workdir=/output",
                "--env=HOME=/output", "--env=TMPDIR=/output", "--env=PYTHONDONTWRITEBYTECODE=1",
                "--env=OMP_NUM_THREADS=2", "--env=OPENBLAS_NUM_THREADS=2",
                "--mount", f"type=volume,source={volume},target=/output,volume-nocopy" + (",readonly" if exporter else "")]
        for key, value in self.container_env.items():
            args.append(f"--env={key}={value}")
        for role, path in sorted(inputs.items()):
            args += ["--mount", f"type=bind,source={path},target=/inputs/{role},readonly,bind-recursive=disabled"]
        if exporter:
            args += ["--entrypoint=/bin/tar", self.image_id, "-C", "/output", "-cf", "-", "."]
        else:
            args += ["--entrypoint=/bin/sleep", self.image_id, "infinity"]
        return self._command(*args)

    def _stream(self, command: list[str], destination: Path, budget: int, timeout: int) -> int:
        started = time.monotonic()
        size = 0
        process = subprocess.Popen(command, env=self.env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            with destination.open("xb") as sink, selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    if time.monotonic() - started > timeout:
                        raise SandboxError("sandbox wall-time limit")
                    for key, _ in selector.select(timeout=0.1):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        remaining = budget - size
                        sink.write(chunk[:remaining])
                        size += len(chunk)
                        if size > budget:
                            raise SandboxError("sandbox stream byte limit")
                return process.wait(timeout=max(0.1, timeout - (time.monotonic() - started)))
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stdout:
                process.stdout.close()

    def _remove_owned(self, kind: str, name: str, owner: str) -> None:
        objects = json.loads(self._control(kind, "inspect", name))
        if len(objects) != 1:
            raise SandboxError("cleanup ownership could not be established")
        item = objects[0]
        labels = item.get("Labels") if kind == "volume" else item.get("Config", {}).get("Labels")
        if (labels or {}).get("experimental.modeling.owner") != owner:
            raise SandboxError("refusing cleanup without matching ownership label")
        identity = item.get("Name") if kind == "volume" else item.get("Id")
        if kind == "volume" and identity != name:
            raise SandboxError("cleanup volume identity mismatch")
        if kind == "container" and not re.fullmatch(r"[0-9a-f]{64}", identity or ""):
            raise SandboxError("cleanup container identity mismatch")
        self._control(kind, "rm", "--force", identity)

    def run(self, stage: str, args: list[str], inputs: dict[str, Path], output: Path, log: Path) -> dict:
        roles = {"author": {"source", "params"}, "inspect": {"inspector", "input"},
                 "roundtrip": {"inspector", "input", "reference"}, "reopen": {"inspector", "input", "reference"}}
        if stage not in roles or set(inputs) != roles[stage]:
            raise ValueError("invalid sandbox stage or input roles")
        inputs = {role: _input(path, role == "source") for role, path in inputs.items()}
        output, log = _path(output), _path(log)
        if not output.is_dir() or any(output.iterdir()):
            raise ValueError("sandbox output must be an empty directory")
        if log.exists() or log.is_relative_to(output):
            raise ValueError("sandbox log must be a new file outside output")
        if any(output == p or output.is_relative_to(p) or p.is_relative_to(output) for p in inputs.values()):
            raise ValueError("sandbox inputs/output overlap")
        runtime = self.verify_runtime()
        name = "modeling-" + uuid.uuid4().hex
        exporter = name + "-export"
        volume = name + "-output"
        command = self.create_command(name, inputs, volume)
        started = time.monotonic()
        cleanup = []
        try:
            cleanup.append(("volume", volume))
            self._control("volume", "create", "--label", "experimental.modeling.owner=" + volume, "--driver", "local", "--opt", "type=tmpfs",
                          "--opt", "device=tmpfs", "--opt",
                          f"o=nosuid,nodev,noexec,size={self.limits.output_bytes},nr_inodes={self.limits.max_files + 32},uid=65532,gid=65532,mode=0700", volume)
            cleanup.append(("container", name))
            # Mark cleanup responsibility before create: a timeout is ambiguous.
            subprocess.run(command, env=self.env, capture_output=True, timeout=15, check=True)
            self._control("start", name)
            base = [self.blender, "--background", "--factory-startup", "--disable-autoexec",
                    "--threads", "2", "--python-exit-code", "1"]
            code = self._stream(self._command("exec", name, *base, *args), log,
                                self.limits.log_bytes, self.limits.timeout_seconds)
            # Freeze hostile surviving children before inspecting/copying outputs.
            self._control("pause", name)
            with tempfile.TemporaryDirectory(prefix="modeling-export-") as directory:
                archive = Path(directory) / "output.tar"
                budget = self.limits.output_bytes + self.limits.max_files * 4096 + 1024**2
                cleanup.append(("container", exporter))
                subprocess.run(self.create_command(exporter, {}, volume, exporter=True), env=self.env,
                               capture_output=True, timeout=15, check=True)
                copied = self._stream(self._command("start", "--attach", exporter), archive, budget, 30)
                if copied:
                    raise SandboxError("sandbox output export failed")
                extract_output(archive, output, self.limits)
            if code:
                raise SandboxError(f"sandbox {stage} failed with exit code {code}")
            return {"exit_code": code, "elapsed_seconds": round(time.monotonic() - started, 3),
                    "security_boundary": self.security_boundary, **runtime}
        finally:
            # Failed removal is a hard failure, including after otherwise successful work.
            failures = []
            for operation in reversed(cleanup):
                try:
                    self._remove_owned(*operation, owner=volume)
                except SandboxError as exc:
                    failures.append(str(exc))
            if failures:
                raise SandboxError("sandbox cleanup failed: " + "; ".join(failures))
