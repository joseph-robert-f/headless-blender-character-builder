#!/opt/blender/4.5/python/bin/python3.11
"""Real-Linux gate for the credentialed worker-to-Blender boundary.

The same file is the gate driver and its fixed builder fixture.  The driver is
run in the production worker image.  ``SubprocessBuilderLauncher`` executes it
again with the normal ``builder build --request ... --output ...`` argument
shape, which tests the actual child-spawn path without adding a test hook to the
production image.
"""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import UUID

CANARY_NAME = "HBCB_BOUNDARY_TEST_CANARY"
CANARY_VALUE = "hbcb-boundary-synthetic-canary"
SECURITY_ATTEMPT = UUID("c8a5aa10-4a73-45ef-a5cf-7c2179fc26dc")
CANCEL_ATTEMPT = UUID("f03cccbf-d5f5-4714-8584-b813948bf894")


class GateFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateFailure(message)


def _blocked_proc_open(path: Path) -> bool:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError as exc:
        return exc.errno in (errno.EACCES, errno.EPERM)
    else:
        os.close(descriptor)
        return False


def _fixture_arguments() -> tuple[Path, Path]:
    require(
        len(sys.argv) == 6
        and sys.argv[1] == "build"
        and sys.argv[2] == "--request"
        and sys.argv[4] == "--output",
        "builder fixture received an unexpected command",
    )
    return Path(sys.argv[3]), Path(sys.argv[5])


def _security_fixture(request: dict[str, object], output: Path) -> int:
    supervisor_pid = os.getppid()
    require(supervisor_pid > 1, "builder fixture has no supervisor parent")
    try:
        os.kill(supervisor_pid, 0)
    except OSError as exc:
        raise GateFailure("worker supervisor disappeared during inspection") from exc

    marker = request.get("marker")
    require(isinstance(marker, str), "security fixture marker is invalid")
    marker_link = marker + " (deleted)"
    inherited_marker = False
    for descriptor in Path("/proc/self/fd").iterdir():
        try:
            if os.readlink(descriptor) in (marker, marker_link):
                inherited_marker = True
                break
        except OSError:
            continue

    evidence = {
        "canary_environment_scrubbed": CANARY_NAME not in os.environ,
        "inheritable_descriptor_closed": not inherited_marker,
        "parent_environ_blocked": _blocked_proc_open(
            Path("/proc") / str(supervisor_pid) / "environ"
        ),
        "parent_memory_blocked": _blocked_proc_open(
            Path("/proc") / str(supervisor_pid) / "mem"
        ),
    }
    output.mkdir(mode=0o700)
    (output / "boundary.json").write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0 if all(evidence.values()) else 19


def _cancellation_fixture(output: Path) -> int:
    output.mkdir(mode=0o700)
    ready = output / "child-ready"
    child = subprocess.Popen(
        (
            sys.executable,
            "-c",
            (
                "import signal,sys,time; from pathlib import Path; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "Path(sys.argv[1]).write_text('ready', encoding='ascii'); "
                "time.sleep(30)"
            ),
            str(ready),
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
    while not ready.exists():
        time.sleep(0.01)
    (output / "processes.json").write_text(
        json.dumps(
            {
                "builder_pid": os.getpid(),
                "builder_group": os.getpgrp(),
                "child_pid": child.pid,
                "child_group": os.getpgid(child.pid),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "processes-ready").touch()
    return child.wait()


def fixture_main() -> int:
    request_path, output = _fixture_arguments()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    require(isinstance(request, dict), "builder fixture request is invalid")
    if request.get("probe") == "security":
        return _security_fixture(request, output)
    if request.get("probe") == "cancellation":
        return _cancellation_fixture(output)
    raise GateFailure("builder fixture probe is invalid")


def _process_is_live(pid: int) -> bool:
    stat_path = Path("/proc") / str(pid) / "stat"
    try:
        payload = stat_path.read_text(encoding="ascii")
        state = payload[payload.rfind(")") + 2 :].split()[0]
        return state != "Z"
    except (OSError, UnicodeDecodeError, IndexError):
        return False


def gate_main() -> int:
    from hbcb_service.launcher import LaunchTermination, SubprocessBuilderLauncher

    require(sys.platform == "linux", "worker boundary gate requires Linux")
    require(Path("/proc/self/environ").is_file(), "worker boundary gate requires procfs")
    require(
        os.geteuid() == 65532 and os.getegid() == 65532,
        "worker boundary gate requires the production UID/GID",
    )
    process_status = Path("/proc/self/status").read_text(encoding="ascii")
    effective_capabilities = next(
        (
            line.split(":", 1)[1].strip()
            for line in process_status.splitlines()
            if line.startswith("CapEff:")
        ),
        "",
    )
    require(
        effective_capabilities
        and int(effective_capabilities, 16) == 0,
        "worker boundary gate requires every effective capability dropped",
    )
    require(
        os.environ.get(CANARY_NAME) == CANARY_VALUE,
        "worker boundary gate synthetic canary is missing",
    )
    own_environment = Path("/proc/self/environ").read_bytes()
    require(
        f"{CANARY_NAME}={CANARY_VALUE}".encode("ascii") in own_environment,
        "synthetic canary is absent from the supervisor procfs environment",
    )

    with tempfile.TemporaryDirectory(prefix="hbcb-boundary-", dir="/work") as raw:
        root = Path(raw)
        scratch = root / "scratch"
        scratch.mkdir(mode=0o700)
        marker = root / "inheritable-marker"
        marker.write_bytes(b"synthetic descriptor canary")
        descriptor = os.open(marker, os.O_RDONLY)
        try:
            os.set_inheritable(descriptor, True)
            marker.unlink()
            security_launcher = SubprocessBuilderLauncher(
                builder_executable=Path(__file__),
                scratch_root=scratch,
                image_reference="headless-blender-character-builder-worker:boundary-gate",
                timeout_seconds=10,
                poll_seconds=0.05,
            )
            security_request = json.dumps(
                {"marker": str(marker), "probe": "security"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            security = security_launcher.execute(
                security_request,
                SECURITY_ATTEMPT,
                lambda: False,
            )
            evidence_path = security.output_dir / "boundary.json"
            if not evidence_path.is_file():
                diagnostic = security.log_tail.decode("utf-8", errors="replace").strip()
                raise GateFailure(
                    "worker boundary evidence is missing"
                    + (": " + diagnostic[-512:] if diagnostic else "")
                )
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            failed_controls = sorted(
                key for key, passed in evidence.items() if passed is not True
            )
            require(
                security.termination is LaunchTermination.COMPLETED
                and security.exit_code == 0,
                "same-UID process-inspection control failed: "
                + ",".join(failed_controls),
            )
            require(
                evidence
                == {
                    "canary_environment_scrubbed": True,
                    "inheritable_descriptor_closed": True,
                    "parent_environ_blocked": True,
                    "parent_memory_blocked": True,
                },
                "worker boundary evidence is incomplete",
            )
            from hbcb_service.process_boundary import supervisor_process_is_secure

            require(
                supervisor_process_is_secure(),
                "supervisor boundary did not remain active",
            )
            security_launcher.cleanup(security.scratch_dir)
        finally:
            os.close(descriptor)

        cancellation_launcher = SubprocessBuilderLauncher(
            builder_executable=Path(__file__),
            scratch_root=scratch,
            image_reference="headless-blender-character-builder-worker:boundary-gate",
            timeout_seconds=10,
            poll_seconds=0.05,
        )
        started = time.monotonic()
        cancellation = cancellation_launcher.execute(
            b'{"probe":"cancellation"}',
            CANCEL_ATTEMPT,
            lambda: any(scratch.glob("attempt-*/output/processes-ready")),
        )
        elapsed = time.monotonic() - started
        require(
            cancellation.termination is LaunchTermination.CANCELED,
            "ordinary cancellation did not win",
        )
        require(elapsed < 6, "ordinary cancellation exceeded its bounded grace")
        processes = json.loads(
            (cancellation.output_dir / "processes.json").read_text(encoding="utf-8")
        )
        require(
            processes["builder_pid"] != processes["child_pid"]
            and processes["builder_group"] != processes["child_group"],
            "cancellation fixture did not create a separate child process group",
        )
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and _process_is_live(processes["child_pid"]):
            time.sleep(0.02)
        require(
            not _process_is_live(processes["child_pid"]),
            "nested Blender-like child survived supervisor cancellation",
        )
        cancellation_launcher.cleanup(cancellation.scratch_dir)

    print("WORKER_PROCESS_BOUNDARY: PASS")
    return 0


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "build":
            raise SystemExit(fixture_main())
        raise SystemExit(gate_main())
    except GateFailure as exc:
        print(f"WORKER_PROCESS_BOUNDARY: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
