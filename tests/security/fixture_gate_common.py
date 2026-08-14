"""Shared process/ownership machinery for the local fixture security gates.

Not a test module and not a standalone executable (no ``__main__``). Each
gate loads this file relative to its own path before first use, so both
running it directly (interpreter puts the script's own directory on
``sys.path``) and loading it by path from ``tests/release/*`` keep working.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

Runner = Callable[..., "subprocess.CompletedProcess[bytes]"]

SAFE_TOOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
MAX_OUTPUT_BYTES = 1024 * 1024
COMMAND_POLL_SECONDS = 0.1
CHILD_TERMINATION_GRACE_SECONDS = 3
CLEANUP_DOCKER_TIMEOUT_SECONDS = 5
_ACTIVE_TERMINATION_GUARD: "Optional[_TerminationGuard]" = None


class GateError(RuntimeError):
    pass


class _TerminationSignal(SystemExit):
    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(128 + signum)


class _TerminationGuard:
    """Defer default termination until owned Docker resources are removed.

    A nested guard delegates to the already-active outer guard instead of
    installing its own handlers, so a signal recorded anywhere in a nested
    ``with`` chain is visible to every guard in that chain.
    """

    def __init__(self) -> None:
        self.received: Optional[int] = None
        self.previous: dict[int, object] = {}
        self.installed: set[int] = set()
        self.delegate: Optional["_TerminationGuard"] = None

    def _record(self, signum: int, _frame: object) -> None:
        if self.received is None:
            self.received = int(signum)

    def __enter__(self) -> "_TerminationGuard":
        global _ACTIVE_TERMINATION_GUARD
        if _ACTIVE_TERMINATION_GUARD is not None:
            self.delegate = _ACTIVE_TERMINATION_GUARD
            return self
        _ACTIVE_TERMINATION_GUARD = self
        for signum in (signal.SIGINT, getattr(signal, "SIGHUP", None), signal.SIGTERM):
            if not isinstance(signum, int) or signum in self.previous:
                continue
            previous = signal.getsignal(signum)
            self.previous[signum] = previous
            if previous == signal.SIG_DFL or (
                signum == signal.SIGINT and previous == signal.default_int_handler
            ):
                signal.signal(signum, self._record)
                self.installed.add(signum)
        return self

    def __exit__(self, _kind: object, _value: object, _traceback: object) -> None:
        global _ACTIVE_TERMINATION_GUARD
        if self.delegate is not None:
            self.raise_if_pending()
            return
        for signum in self.installed:
            signal.signal(signum, self.previous[signum])
        if _ACTIVE_TERMINATION_GUARD is self:
            _ACTIVE_TERMINATION_GUARD = None
        self.raise_if_pending()

    def raise_if_pending(self) -> None:
        received = self.delegate.received if self.delegate is not None else self.received
        if received is None:
            return
        if received == signal.SIGINT:
            raise KeyboardInterrupt
        raise _TerminationSignal(received)


def _safe_tool_selector(value: str) -> bool:
    if SAFE_TOOL.fullmatch(value) is not None:
        return True
    if not value or len(value) > 1024 or any(ord(character) < 32 for character in value):
        return False
    supplied = Path(value)
    if not supplied.is_absolute() or supplied == Path("/") or ".." in supplied.parts:
        return False
    try:
        resolved = supplied.resolve(strict=True)
    except OSError:
        return False
    return resolved.is_file() and os.access(resolved, os.X_OK)


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except (OSError, PermissionError):
        return True
    return True


def _wait_process_group(process: "subprocess.Popen[bytes]", deadline: float) -> bool:
    process_group = process.pid
    while _process_group_exists(process_group):
        process.poll()
        if time.monotonic() >= deadline:
            return False
        time.sleep(COMMAND_POLL_SECONDS)
    return True


def _terminate_process(process: "subprocess.Popen[bytes]") -> None:
    process_group = process.pid
    if _process_group_exists(process_group):
        try:
            os.killpg(process_group, signal.SIGTERM)
        except OSError:
            pass
    if not _wait_process_group(process, time.monotonic() + CHILD_TERMINATION_GRACE_SECONDS):
        try:
            os.killpg(process_group, signal.SIGKILL)
        except OSError:
            pass
        if not _wait_process_group(process, time.monotonic() + CHILD_TERMINATION_GRACE_SECONDS):
            raise GateError("a Docker subprocess group could not be terminated")
    try:
        process.communicate(timeout=CHILD_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired as failure:
        try:
            process.kill()
        except OSError:
            pass
        raise GateError("a Docker subprocess could not be reaped") from failure


def _run(
    command: Sequence[str],
    *,
    timeout: int = 30,
    check: bool = True,
    interruptible: bool = True,
    check_failure_message: str = "a Docker fixture check failed",
) -> subprocess.CompletedProcess[bytes]:
    process: "Optional[subprocess.Popen[bytes]]" = None
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(os.environ, LC_ALL="C"),
            start_new_session=True,
        )
        while True:
            active = _ACTIVE_TERMINATION_GUARD
            if interruptible and active is not None and active.received is not None:
                _terminate_process(process)
                active.raise_if_pending()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process(process)
                raise GateError("a bounded Docker operation timed out")
            try:
                stdout, stderr = process.communicate(timeout=min(COMMAND_POLL_SECONDS, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    except OSError as failure:
        if process is not None:
            _terminate_process(process)
        raise GateError("a bounded Docker operation failed") from failure
    except BaseException:
        if process is not None and _process_group_exists(process.pid):
            _terminate_process(process)
        raise
    completed = subprocess.CompletedProcess(list(command), process.returncode, stdout, stderr)
    if len(completed.stdout) > MAX_OUTPUT_BYTES or len(completed.stderr) > MAX_OUTPUT_BYTES:
        raise GateError("a Docker operation exceeded the output limit")
    if check and completed.returncode != 0:
        raise GateError(check_failure_message)
    return completed


def _owned_container_ids(
    run: Runner, docker: str, name: str, owner_label: str,
    *, label: str, timeout: int = 30, interruptible: bool = True,
) -> list[str]:
    result = run(
        (
            docker, "container", "ls", "--all", "--no-trunc", "--quiet",
            "--filter", "name=^/" + name + "$",
            "--filter", "label=" + owner_label,
        ),
        timeout=timeout, check=False, interruptible=interruptible,
    )
    if result.returncode != 0:
        raise GateError(label + " ownership could not be inspected")
    try:
        identifiers = result.stdout.decode("ascii", "strict").splitlines()
    except UnicodeError as failure:
        raise GateError(label + " ownership is invalid") from failure
    if (
        any(CONTAINER_ID.fullmatch(identifier) is None for identifier in identifiers)
        or len(identifiers) != len(set(identifiers))
        or len(identifiers) > 1
    ):
        raise GateError(label + " ownership is ambiguous")
    return identifiers


def _remove_owned_container(
    run: Runner, docker: str, name: str, owner_label: str, *, label: str, timeout: int = 30,
) -> None:
    owned = _owned_container_ids(
        run, docker, name, owner_label, label=label, timeout=timeout, interruptible=False
    )
    if owned:
        removal = run(
            (docker, "rm", "--force", owned[0]), timeout=timeout, check=False, interruptible=False
        )
        remaining = _owned_container_ids(
            run, docker, name, owner_label, label=label, timeout=timeout, interruptible=False
        )
        if removal.returncode != 0 or remaining:
            raise GateError(label + " could not be removed")
