"""Linux process-inspection boundary for the credentialed worker supervisor."""

from __future__ import annotations

import ctypes
import sys
from typing import Any

from .errors import WorkerError

try:  # pragma: no cover - the production worker is Linux-only.
    import resource
except ImportError:  # pragma: no cover - keeps imports safe on Windows.
    resource = None  # type: ignore[assignment]


# Linux ``prctl(2)`` operation numbers are part of the userspace ABI.
_PR_GET_DUMPABLE = 3
_PR_SET_DUMPABLE = 4


def _prctl() -> Any:
    if resource is None:
        raise WorkerError(
            "process_boundary_unavailable",
            "worker core-dump protection is unavailable",
        )
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        operation = libc.prctl
        operation.argtypes = (
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
        )
        operation.restype = ctypes.c_int
    except (AttributeError, OSError, TypeError) as exc:
        raise WorkerError(
            "process_boundary_unavailable",
            "worker process-inspection protection is unavailable",
        ) from exc
    return operation


def _dumpable(operation: Any) -> int:
    try:
        result = int(operation(_PR_GET_DUMPABLE, 0, 0, 0, 0))
    except (OSError, TypeError, ValueError) as exc:
        raise WorkerError(
            "process_boundary_unavailable",
            "worker process-inspection protection is unavailable",
        ) from exc
    if result < 0:
        raise WorkerError(
            "process_boundary_unavailable",
            "worker process-inspection protection is unavailable",
        )
    return result


def secure_supervisor_process(*, require_linux: bool = False) -> None:
    """Make the current worker supervisor non-inspectable by same-UID children.

    Linux gates access to ``/proc/<pid>/environ``, ``/proc/<pid>/mem``, and
    ptrace-like process-memory operations through the process dumpable flag.
    The worker runs without ``CAP_SYS_PTRACE``, so setting that flag to zero
    prevents its same-UID Blender descendants from crossing back into the
    credentialed supervisor.  Core dumps are disabled as a second, separately
    verified invariant.

    The production entrypoint requires Linux.  The launcher also calls this
    function before every child spawn; that defensive call remains a no-op for
    native contributor tests on other operating systems.
    """

    if sys.platform != "linux":
        if require_linux:
            raise WorkerError(
                "process_boundary_unsupported",
                "worker process-inspection protection requires Linux",
            )
        return

    operation = _prctl()
    try:
        result = int(operation(_PR_SET_DUMPABLE, 0, 0, 0, 0))
    except (OSError, TypeError, ValueError) as exc:
        raise WorkerError(
            "process_boundary_unavailable",
            "worker process-inspection protection could not be enabled",
        ) from exc
    if result != 0 or _dumpable(operation) != 0:
        raise WorkerError(
            "process_boundary_unavailable",
            "worker process-inspection protection could not be enabled",
        )

    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        core_limit = resource.getrlimit(resource.RLIMIT_CORE)
    except (OSError, ValueError) as exc:
        raise WorkerError(
            "process_boundary_unavailable",
            "worker core-dump protection could not be enabled",
        ) from exc
    if core_limit != (0, 0):
        raise WorkerError(
            "process_boundary_unavailable",
            "worker core-dump protection could not be enabled",
        )


def supervisor_process_is_secure() -> bool:
    """Return whether the current Linux process has the required boundary."""

    if sys.platform != "linux":
        return False
    if resource is None:
        return False
    try:
        core_limit = resource.getrlimit(resource.RLIMIT_CORE)
        return _dumpable(_prctl()) == 0 and core_limit == (0, 0)
    except WorkerError:
        return False


__all__ = ["secure_supervisor_process", "supervisor_process_is_secure"]
