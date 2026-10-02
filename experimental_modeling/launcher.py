"""Make a local project. Examine runtime status or open project evidence."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import signal

from .project import Project, atomic_json, initialize, local_path, read_object
from .runtime import RuntimeSelection, canonical_selection, doctor
from .platform_io import exclusive_lock


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def operation_lock(project: Project, operation: str):
    """Kernel-released lease. Persisted PIDs/URLs never authorize takeover or killing."""
    path = local_path(project.root / (".launcher-" + operation + ".lock"))
    with ExitStack() as stack:
        try:
            stack.enter_context(exclusive_lock(path))
        except BlockingIOError as exc:
            raise RuntimeError(f"A {operation} session is active for this project. Use its terminal, or stop the session before you try again.") from exc
        yield


@contextmanager
def interruptible():
    """Convert terminal termination to unwinding so existing backend cleanup runs."""
    signals = [signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        signals.append(signal.SIGBREAK)  # Windows console Ctrl-Break, not TerminateProcess.
    previous = {sig: signal.getsignal(sig) for sig in signals}
    def terminate(signum, frame):
        raise KeyboardInterrupt
    for sig in signals:
        signal.signal(sig, terminate)
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def review_project(project: Project, port: int = 0, *, allow_unverified_platform: bool = False) -> None:
    report = doctor(project, RuntimeSelection())
    if not report["review_ready"] and not (allow_unverified_platform and report["review_candidate"]):
        raise RuntimeError('Review backend not available: Complete setup on a permitted platform. For experimental Windows/Mac review, select --experimental-platform-review. This option does not give permission for builds.')
    if not 0 <= port <= 65535:
        raise ValueError("Port must be 0..65535")
    state = local_path(project.root / ".launcher-review.json")
    from .review_server import LocalReviewServer, ReviewProject
    with operation_lock(project, "review"), interruptible():
        server = LocalReviewServer(ReviewProject(project.folder("evidence"), name=project.name), port)
        try:
            # Drain bounded requests before releasing the lease; acceptance may be writing.
            server.daemon_threads = False
            atomic_json(state, {"schema_version": 1, "status": "running", "started_at": now()})
            print(f"Local project review: {server.origin}", flush=True)
            print(server.project.read_only_reason or "Review only. The program does not run queued prompts. Push Ctrl-C to stop this session.", flush=True)
            server.serve_forever()
        finally:
            server.server_close()
            atomic_json(state, {"schema_version": 1, "status": "stopped", "stopped_at": now()})


def build_project(project: Project, selection: RuntimeSelection, *, revision: str,
                  parent: str | None = None, intent: str = "", renders: bool = True,
                  acknowledge_interrupted: bool = False) -> dict:
    # This explicit build command authorizes probing only the selected trusted runtime.
    selection = canonical_selection(selection, project)
    report = doctor(project, selection, probe=True)
    if not report["build_prerequisites_ready"]:
        details = "; ".join(c["detail"] for c in report["checks"] if c["status"] in {"blocked", "missing", "unsupported"})
        raise RuntimeError("Build is not ready: " + details)
    from .contracts import identifier
    from .controller import build
    identifier(revision)
    if parent is not None:
        identifier(parent)
    state = local_path(project.root / ".launcher-build.json")
    with operation_lock(project, "build"), interruptible():
        if state.exists():
            prior = read_object(state)
            if prior.get("schema_version") != 1 or prior.get("status") not in {"running", "finished", "recovery_required"}:
                raise ValueError('Incorrect build recovery record. Examine this record before you continue.')
            if prior["status"] != "finished" and not acknowledge_interrupted:
                raise RuntimeError("Build recovery is necessary. Examine saved evidence, last_good.json, and Docker resources that this project owns. Make sure that cleanup is complete. Select a new revision ID. Then use --acknowledge-interrupted-build. This command did not remove a process or artifact.")
        # Never overwrite an existing controller revision or its crash evidence.
        if any((project.folder(role) / revision).exists() for role in ("candidates", "accepted")):
            raise ValueError("Revision ID is in use. Examine saved evidence and select a new ID.")
        record = {"schema_version": 1, "status": "running", "revision": revision,
                  "mode": selection.mode, "started_at": now()}
        atomic_json(state, record)
        try:
            requirements = project.input("requirements.json")
            result = build(source=project.folder("source"), params=project.input("params.json"),
                           policy_path=project.input("policy.json"), store=project.folder("evidence"),
                           revision=revision, parent=parent, intent=intent, renders=renders,
                           requirements_path=requirements if requirements.exists() else None,
                           blender=str(selection.blender) if selection.blender is not None else "blender",
                           trusted_reviewed_source=selection.mode == "trusted-native",
                           sandbox_image=selection.image, docker_executable=selection.docker,
                           docker_socket=selection.socket or Path("/var/run/docker.sock"))
        except BaseException:
            # Keep "running" as a conservative recovery marker even if cleanup ran.
            raise
        else:
            # The controller retains backend errors as needs_review results, including
            # failed Docker cleanup. Such a return is not proof of clean shutdown.
            state_status = "recovery_required" if "error" in result else "finished"
            atomic_json(state, record | {"status": state_status, "result_status": result["status"], "finished_at": now()})
            return result


def _runtime_arguments(parser):
    parser.add_argument("--trusted-reviewed-source", action="store_true",
                        help="Give permission to run all source after you examine it. Native execution has no sandbox.")
    parser.add_argument("--blender", type=Path, help="Absolute path of a trusted Blender executable. For native mode only.")
    parser.add_argument("--docker", type=Path, help="Absolute path of a trusted Docker executable. The program does not search PATH.")
    parser.add_argument("--docker-socket", type=Path, help="Set a local Unix socket. The program does not read Docker contexts or Docker environment settings.")
    parser.add_argument("--sandbox-image", help="Use an installed image with ID sha256:... after source review. The program does not download images.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Make a project folder, or complete its setup. A runtime is not necessary.")
    init.add_argument("--project", type=Path, required=True)
    init.add_argument("--name")
    check = commands.add_parser("doctor", help="Show prerequisites. The program runs no executable unless you select --probe.")
    check.add_argument("--project", type=Path, required=True)
    check.add_argument("--probe", action="store_true", help="Give permission for read-only checks with the trusted programs that you select.")
    _runtime_arguments(check)
    review = commands.add_parser("review", help="Examine evidence with the program on the loopback address.")
    review.add_argument("--project", type=Path, required=True)
    review.add_argument("--port", type=int, default=0)
    review.add_argument("--experimental-platform-review", action="store_true",
                        help="Select experimental Windows/Mac review only. Windows mode cannot record decisions or requests.")
    build = commands.add_parser("build", help="Build inputs after source review. The controller stops if a mandatory check fails.")
    build.add_argument("--project", type=Path, required=True)
    build.add_argument("--revision", required=True)
    build.add_argument("--parent")
    build.add_argument("--intent", default="")
    build.add_argument("--skip-renders", action="store_true")
    build.add_argument("--acknowledge-interrupted-build", action="store_true",
                       help="Make sure that you examined evidence and completed cleanup of runtime resources that this project owns. This option erases nothing.")
    _runtime_arguments(build)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            project = initialize(args.project, args.name)
            print(json.dumps({"status": "initialized", "name": project.name}, ensure_ascii=True))
            return 0
        project = Project.open(args.project)
        if args.command == "review":
            review_project(project, args.port, allow_unverified_platform=args.experimental_platform_review)
            return 0
        selection = RuntimeSelection(mode="trusted-native" if args.trusted_reviewed_source else "isolated",
                                     blender=args.blender, docker=args.docker, socket=args.docker_socket, image=args.sandbox_image)
        if args.command == "doctor":
            report = doctor(project, selection, probe=args.probe)
            print(json.dumps(report, ensure_ascii=True, indent=2))
            return 0 if report["build_ready"] else 1
        result = build_project(project, selection, revision=args.revision, parent=args.parent,
                               intent=args.intent, renders=not args.skip_renders,
                               acknowledge_interrupted=args.acknowledge_interrupted_build)
        print(json.dumps({key: result[key] for key in ("status", "revision", "failures")}, indent=2))
        return 0 if result["status"] == "accepted" else 1
    except KeyboardInterrupt:
        print("Stopped. If a build stopped before it was complete, examine its recovery state. This command did not remove evidence.")
        return 130
    except (ValueError, RuntimeError, OSError) as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
