"""Stable v0.1 application exit codes."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    INVALID_CLI = 2
    INVALID_REQUEST = 3
    FILESYSTEM = 4
    BLENDER = 10
    VERIFICATION = 11
    INTERNAL = 12
    TIMEOUT = 124


APPLICATION_FAILURES = frozenset(int(code) for code in ExitCode if code)

__all__ = ["APPLICATION_FAILURES", "ExitCode"]
