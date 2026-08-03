"""Narrow ``builder`` command-line interface."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .commands import BuilderCliFailure, build_artifacts, verify_artifacts
from .exit_codes import ExitCode


def _command_parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"builder {command}", add_help=False, exit_on_error=False)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    return parser


def _usage() -> str:
    return (
        "usage: builder build --request PATH --output PATH\n"
        "       builder verify --request PATH --output PATH"
    )


def _parse(argv: Sequence[str]) -> tuple[str, argparse.Namespace]:
    if list(argv) in (["--help"], ["-h"]):
        print(_usage())
        raise BuilderCliFailure(int(ExitCode.SUCCESS), "help requested")
    if not argv or argv[0] not in {"build", "verify"}:
        raise BuilderCliFailure(int(ExitCode.INVALID_CLI), "expected build or verify")
    command = argv[0]
    if list(argv[1:]) in (["--help"], ["-h"]):
        print(_usage())
        raise BuilderCliFailure(int(ExitCode.SUCCESS), "help requested")
    parser = _command_parser(command)
    try:
        arguments, extras = parser.parse_known_args(argv[1:])
    except (argparse.ArgumentError, SystemExit) as exc:
        raise BuilderCliFailure(int(ExitCode.INVALID_CLI), "invalid command") from exc
    if extras:
        raise BuilderCliFailure(int(ExitCode.INVALID_CLI), "unsupported option or argument")
    return command, arguments


def main(argv: Sequence[str] | None = None) -> int:
    try:
        command, arguments = _parse(tuple(sys.argv[1:] if argv is None else argv))
        if command == "build":
            build_artifacts(arguments.request, arguments.output)
        else:
            verify_artifacts(arguments.request, arguments.output)
    except BuilderCliFailure as exc:
        if exc.exit_code == int(ExitCode.SUCCESS):
            return int(ExitCode.SUCCESS)
        print(f"BUILDER: FAIL[{exc.exit_code}]: {exc.message}", file=sys.stderr)
        return exc.exit_code
    except Exception:
        # The launcher is a trusted boundary.  Unexpected implementation
        # failures must not expose exception text, paths, or environment data
        # through a traceback, and retain the documented internal-error code.
        print(f"BUILDER: FAIL[{int(ExitCode.INTERNAL)}]: internal launcher failure", file=sys.stderr)
        return int(ExitCode.INTERNAL)
    print(f"BUILDER_{command.upper()}: PASS")
    return int(ExitCode.SUCCESS)


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
