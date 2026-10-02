"""Open project evidence with the HBCB REVIEW PREVIEW program."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading

from .launcher import interruptible
from .preview_manifest import verify
from .project import Project
from .review_server import LocalReviewServer, ReviewProject

BANNER = ("REVIEW PREVIEW: Read-only mode. The program shows project evidence. It does not make models or use AI. "
          "It cannot connect to an account, download runtime files, or start background services. You cannot record decisions or change requests.")


def bundle_root() -> Path | None:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None


def serve(project: Project, port: int) -> None:
    if not 0 <= port <= 65535:
        raise ValueError("Port must be 0..65535")
    project.validate_folders()
    review = ReviewProject(project.folder("evidence"), name=project.name, read_only=True)
    review.read_only_reason = BANNER
    server = LocalReviewServer(review, port)
    # Unlike the write-capable launcher, this preview creates no project lease,
    # status record, migration, cache or review directory. Concurrent readers
    # are permitted; do not run a builder against the project during review.
    server.daemon_threads = False
    stop = threading.Event()

    def terminal_input():
        # One portable shutdown path also works on console-less Windows CI.
        # EOF does not stop detached review, and no command is ever evaluated.
        if sys.stdin is None:
            return
        # Avoid holding Python's buffered stdin lock in a daemon during Ctrl-C
        # interpreter shutdown. No terminal commands or arbitrary text execute.
        try:
            descriptor = sys.stdin.fileno()
            pending = b""
            while not stop.is_set():
                chunk = os.read(descriptor, 256)
                if not chunk:
                    return
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    if line.strip().lower() == b"q":
                        stop.set()
                        return
                if len(pending) > 256:
                    pending = b""
        except (OSError, ValueError):
            return

    reader = threading.Thread(target=terminal_input, daemon=True)
    server.timeout = .2
    try:
        with interruptible():
            reader.start()
            print(BANNER, flush=True)
            print(f"Local project review: {server.origin}", flush=True)
            print("Open this address in your browser. To stop, type q and push Enter, or push Ctrl-C.", flush=True)
            while not stop.is_set():
                server.handle_request()
    finally:
        stop.set()
        server.server_close()
        print("Review stopped. The program did not change project files.", flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--project", type=Path, help="Select a version-1 project folder. The program does not change project files.")
    action.add_argument("--verify", action="store_true", help="Do the package integrity check without a network connection.")
    action.add_argument("--provenance", action="store_true", help="Show the package provenance after the integrity check.")
    parser.add_argument("--port", type=int, default=0, help="Set the local port. The program selects a free port if you do not set one.")
    args = parser.parse_args(argv)
    try:
        root = bundle_root()
        if root is not None:
            result = verify(root)
        elif args.verify or args.provenance:
            raise ValueError("Use the REVIEW PREVIEW executable from the complete package for this integrity check.")
        if args.verify:
            print(json.dumps(result, indent=2))
        elif args.provenance:
            print((root / "provenance.json").read_text(encoding="utf-8"))
        else:
            serve(Project.open(args.project), args.port)
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"REVIEW PREVIEW: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
