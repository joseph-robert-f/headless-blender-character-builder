"""Explicit runtime selection and read-only readiness checks. No discovery/install."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
import re
import selectors
import signal
import subprocess
import time
import tempfile

from .project import Project, RUNTIME_POLICY, local_path, read_object

BLENDER_VERSION = "4.5.12"
BLENDER_ARCHIVE_SHA256 = "95e3a2dfedba3bd32ca54fc355eac6b15a11986954ccb02815a07535d0120a25"
IMAGE_ARCHITECTURE = "amd64"


@dataclass(frozen=True)
class RuntimeSelection:
    mode: str = "isolated"
    blender: Path | None = None
    docker: Path | None = None
    socket: Path | None = None
    image: str | None = None

    def __post_init__(self):
        if self.mode not in {"isolated", "trusted-native"}:
            raise ValueError("Select isolated or trusted-native explicitly")
        if self.mode == "isolated" and self.blender is not None:
            raise ValueError("An isolated build never uses a host Blender executable")
        if self.mode == "trusted-native" and any(v is not None for v in (self.docker, self.socket, self.image)):
            raise ValueError("Trusted native and Docker selections cannot be mixed")
        if self.image is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image):
            raise ValueError("Select a reviewed local image by its complete sha256 image ID")


def executable(path: Path | None, project: Project) -> Path:
    if path is None:
        raise ValueError("No executable selected; supply an absolute path to a trusted installation")
    if not Path(path).is_absolute():
        raise ValueError("Executable selection requires an absolute path; PATH discovery is disabled")
    path = local_path(path)
    if path.is_relative_to(project.root):
        raise ValueError("Executable must be outside the portable project; never execute project-provided runtime files")
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("Selected executable is missing or not executable")
    return path


def canonical_selection(selection: RuntimeSelection, project: Project) -> RuntimeSelection:
    """Use these exact validated paths for both the preflight and dispatch."""
    if selection.socket is not None and not selection.socket.is_absolute():
        raise ValueError("Docker socket selection requires an absolute path")
    return RuntimeSelection(mode=selection.mode, image=selection.image,
                            blender=executable(selection.blender, project) if selection.blender is not None else None,
                            docker=executable(selection.docker, project) if selection.docker is not None else None,
                            socket=local_path(selection.socket) if selection.socket is not None else None)


def _native_version(binary: Path) -> str:
    # The caller explicitly authorizes probing a trusted binary. Never load a project.
    with tempfile.TemporaryDirectory(prefix="modeling-runtime-probe-") as directory:
        env = {"PATH": "/usr/bin:/bin", "HOME": directory, "TMPDIR": directory,
               "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
        process = subprocess.Popen([str(binary), "--version"], cwd=directory, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        output = bytearray()
        deadline = time.monotonic() + 10
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Blender version probe timed out")
                    for key, _ in selector.select(timeout=0.1):
                        chunk = os.read(key.fileobj.fileno(), 8193)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        output.extend(chunk)
                        if len(output) > 8192:
                            raise RuntimeError("Blender version probe exceeded its output limit")
                if process.wait(timeout=max(0.1, deadline - time.monotonic())):
                    raise RuntimeError("Blender version probe failed")
        finally:
            # Includes descendants of a successful launcher; this is cleanup, not isolation.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            process.stdout.close()
        text = output.decode("utf-8", errors="replace")
    match = re.match(r"Blender ([0-9]+\.[0-9]+\.[0-9]+)(?:\s|$)", text)
    if not match:
        raise ValueError("Selected executable did not report a Blender version")
    return match.group(1)


def _sandbox(selection: RuntimeSelection, project: Project):
    from .sandbox import DockerSandbox
    binary = executable(selection.docker, project)
    if selection.image is None:
        raise ValueError("Select a reviewed local Docker image using --sandbox-image sha256:...")
    if selection.socket is None or not selection.socket.is_absolute():
        raise ValueError("Select an explicit local Unix Docker socket using --docker-socket")
    socket = local_path(selection.socket)
    if not socket.is_socket():
        raise ValueError("Selected local Docker socket is unavailable; start the reviewed Docker installation")
    return DockerSandbox(selection.image, socket=socket, docker_executable=binary)


def _check(key, status, detail):
    return {"id": key, "status": status, "detail": detail}


def doctor(project: Project, selection: RuntimeSelection, *, probe: bool = False) -> dict:
    checks = []
    system, machine = platform.system(), platform.machine().lower()
    supported = system == "Linux" and machine in {"x86_64", "amd64"}
    candidate_review = ((system == "Windows" and machine in {"x86_64", "amd64"})
                        or (system == "Darwin" and machine in {"arm64", "aarch64"}))
    checks.append(_check("platform", "ready" if supported else "unsupported",
                         f"{system}/{machine}. Execution adapter is currently Linux x64 only; Windows x64 and Mac Apple Silicon are planned, unverified targets."))
    folders_ready = True
    try:
        project.validate_folders()
        checks.append(_check("project", "ready", "Version 1 portable folder layout is valid"))
    except (ValueError, OSError) as exc:
        folders_ready = False
        checks.append(_check("project", "missing", str(exc)))
    inputs_ready = False
    try:
        from .contracts import Policy, read_json
        from .requirements import RequirementSet
        if not folders_ready or not local_path(project.folder("source") / "builder.py").is_file():
            raise ValueError("Add reviewed source/builder.py and finish project setup")
        if not isinstance(read_json(project.input("params.json")), dict):
            raise ValueError("constraints/params.json must contain a JSON object")
        policy = Policy.parse(read_json(project.input("policy.json")))
        if policy.profile != "scene":
            raise ValueError("Only scene policies are supported; print acceptance is unavailable")
        requirements = project.input("requirements.json")
        if requirements.exists():
            RequirementSet.parse(read_json(requirements))
        inputs_ready = True
        checks.append(_check("build_inputs", "ready", "Input JSON contracts are valid; source trust, history, locked requirements and geometry are checked separately at build time"))
    except (ValueError, OSError, TypeError, KeyError) as exc:
        checks.append(_check("build_inputs", "missing", "Review source/builder.py and constraints/{params,policy,requirements}.json: " + str(exc)))
    checks.append(_check("model_connection", "not_implemented",
                         "No built-in model provider or queue consumer. A coding agent must supply source; queued prompts do not execute."))
    runtime_ready = False
    if not supported:
        checks.append(_check("runtime", "not_probed", "No executable is launched on an unverified platform"))
    else:
        try:
            if selection.mode == "trusted-native":
                binary = executable(selection.blender, project)
                if probe:
                    version = _native_version(binary)
                    if version != BLENDER_VERSION:
                        raise ValueError(f"Blender {version} is incompatible; this policy pins {BLENDER_VERSION}. No upgrade or downgrade was performed")
                    runtime_ready = True
                checks.append(_check("runtime", "ready" if probe else "unverified",
                                     "Native reviewed-source mode has no sandbox" if probe else "Selected native executable exists; use --probe to authorize its version check"))
            else:
                backend = _sandbox(selection, project)
                if probe:
                    runtime = backend.verify_runtime()
                    if runtime.get("image_architecture") != IMAGE_ARCHITECTURE:
                        raise ValueError("Image architecture must be linux/amd64; ARM/emulation is not validated by this launcher")
                    if runtime.get("blender_version") != BLENDER_VERSION + " LTS" or runtime.get("blender_archive_sha256") != BLENDER_ARCHIVE_SHA256:
                        raise ValueError("Image metadata does not match the pinned Blender 4.5.12 archive; use the reviewed repository image")
                    runtime_ready = True
                checks.append(_check("runtime", "ready" if probe else "unverified",
                                     "Explicit local daemon and reviewed immutable image passed capability/metadata checks; this is not an audit or proof of image trust" if probe else "Explicit Docker selection exists; use --probe to authorize read-only daemon/image checks"))
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
            checks.append(_check("runtime", "blocked", str(exc)))
    recovery_required = False
    state = local_path(project.root / ".launcher-build.json")
    if state.exists():
        try:
            record = read_object(state)
            if record.get("schema_version") != 1 or record.get("status") not in {"running", "finished", "recovery_required"}:
                raise ValueError("Invalid build recovery record")
            recovery_required = record["status"] != "finished"
        except (ValueError, OSError):
            recovery_required = True
    checks.append(_check("recovery", "inspection_required" if recovery_required else "clear",
                         "Inspect retained evidence, last_good.json and owned Docker resources before explicitly acknowledging interrupted-build recovery" if recovery_required else "No unresolved launcher build interruption recorded"))
    prerequisites = folders_ready and inputs_ready and supported and runtime_ready
    return {"schema_version": 1, "project_name": project.name, "runtime_policy": RUNTIME_POLICY,
            "mode": selection.mode, "probed": probe, "review_ready": folders_ready and supported,
            "review_candidate": folders_ready and candidate_review, "review_read_only": system == "Windows",
            "build_prerequisites_ready": prerequisites, "build_ready": prerequisites and not recovery_required,
            "recovery_required": recovery_required, "authoring_ready": False, "checks": checks}
