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
            raise ValueError("Select isolated or trusted-native.")
        if self.mode == "isolated" and self.blender is not None:
            raise ValueError("An isolated build does not use a host Blender executable.")
        if self.mode == "trusted-native" and any(v is not None for v in (self.docker, self.socket, self.image)):
            raise ValueError("Do not select both trusted-native mode and Docker mode.")
        if self.image is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image):
            raise ValueError("Select a local image after source review. Supply its complete sha256 image ID.")


def executable(path: Path | None, project: Project) -> Path:
    if path is None:
        raise ValueError("No executable selected. Supply the absolute path of a trusted installation.")
    if not Path(path).is_absolute():
        raise ValueError("Supply an absolute path for the executable. The program does not search PATH.")
    path = local_path(path)
    if path.is_relative_to(project.root):
        raise ValueError("Do not select an executable from the project folder. Do not run runtime files that the project supplies.")
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("The selected executable is not available, or the program cannot run it.")
    return path


def canonical_selection(selection: RuntimeSelection, project: Project) -> RuntimeSelection:
    """Use these exact validated paths for both the preflight and dispatch."""
    if selection.socket is not None and not selection.socket.is_absolute():
        raise ValueError("Supply an absolute path for the Docker socket.")
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
        raise ValueError("Select a local Docker image after source review. Use --sandbox-image sha256:....")
    if selection.socket is None or not selection.socket.is_absolute():
        raise ValueError("Select a local Unix Docker socket with --docker-socket.")
    socket = local_path(selection.socket)
    if not socket.is_socket():
        raise ValueError("The selected local Docker socket is not available. Start the Docker installation after source review.")
    return DockerSandbox(selection.image, socket=socket, docker_executable=binary)


def _check(key, status, detail):
    return {"id": key, "status": status, "detail": detail}


def doctor(project: Project, selection: RuntimeSelection, *, probe: bool = False, build_inputs=None) -> dict:
    checks = []
    system, machine = platform.system(), platform.machine().lower()
    supported = system == "Linux" and machine in {"x86_64", "amd64"}
    candidate_review = ((system == "Windows" and machine in {"x86_64", "amd64"})
                        or (system == "Darwin" and machine in {"arm64", "aarch64"}))
    checks.append(_check("platform", "ready" if supported else "unsupported",
                         f"{system}/{machine}. Only Linux x64 has an execution adapter. The plan includes Windows x64 and Mac Apple Silicon adapters. They are not available."))
    folders_ready = True
    try:
        project.validate_folders()
        checks.append(_check("project", "ready", "The project folder layout is correct for version 1."))
    except (ValueError, OSError) as exc:
        folders_ready = False
        checks.append(_check("project", "missing", str(exc)))
    inputs_ready = False
    try:
        from .contracts import Policy, read_json
        from .requirements import RequirementSet
        source, params, policy_path, requirements = build_inputs or (project.folder("source"), project.input("params.json"), project.input("policy.json"), project.input("requirements.json"))
        if not folders_ready or not local_path(source / "builder.py").is_file():
            raise ValueError("Examine source/builder.py. Add this file and complete project setup.")
        if not isinstance(read_json(params), dict):
            raise ValueError("constraints/params.json must contain a JSON object")
        policy = Policy.parse(read_json(policy_path))
        if policy.profile != "scene":
            raise ValueError("Use the scene policy. Print acceptance is not available.")
        if requirements is not None and requirements.exists():
            RequirementSet.parse(read_json(requirements))
        inputs_ready = True
        checks.append(_check("build_inputs", "ready", "The input JSON is correct for these contracts. The build does checks of source trust, history, locked requirements, and geometry."))
    except (ValueError, OSError, TypeError, KeyError) as exc:
        checks.append(_check("build_inputs", "missing", "Examine source/builder.py and constraints/{params,policy,requirements}.json: " + str(exc)))
    checks.append(_check("model_connection", "not_implemented",
                         "The program does not call an AI provider. Use the explicit request bridge with source from an external coding agent. Saved prompts do not run automatically."))
    runtime_ready = False
    if not supported:
        checks.append(_check("runtime", "not_probed", "The launcher does not run an executable on a platform without validation."))
    else:
        try:
            if selection.mode == "trusted-native":
                binary = executable(selection.blender, project)
                if probe:
                    version = _native_version(binary)
                    if version != BLENDER_VERSION:
                        raise ValueError(f"Blender {version} does not match version {BLENDER_VERSION} in this policy. The program did not change Blender.")
                    runtime_ready = True
                checks.append(_check("runtime", "ready" if probe else "unverified",
                                     "Native mode has no sandbox. Examine all source before a build." if probe else "The selected native executable is available. Use --probe to give permission for its version check."))
            else:
                backend = _sandbox(selection, project)
                if probe:
                    runtime = backend.verify_runtime()
                    if runtime.get("image_architecture") != IMAGE_ARCHITECTURE:
                        raise ValueError("Image architecture must be linux/amd64. This launcher has no validation for ARM or emulation.")
                    if runtime.get("blender_version") != BLENDER_VERSION + " LTS" or runtime.get("blender_archive_sha256") != BLENDER_ARCHIVE_SHA256:
                        raise ValueError("Image metadata does not match the Blender 4.5.12 archive. Use the repository image after source review.")
                    runtime_ready = True
                checks.append(_check("runtime", "ready" if probe else "unverified",
                                     "The selected local daemon and image passed capability and metadata checks. These checks are not a security audit. They do not show that the image is safe." if probe else "The selected Docker runtime is available. Use --probe to give permission for read-only daemon and image checks."))
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
            checks.append(_check("runtime", "blocked", str(exc)))
    recovery_required = False
    state = local_path(project.root / ".launcher-build.json")
    if state.exists():
        try:
            record = read_object(state)
            if record.get("schema_version") != 1 or record.get("status") not in {"running", "finished", "recovery_required"}:
                raise ValueError('Incorrect build recovery record')
            recovery_required = record["status"] != "finished"
        except (ValueError, OSError):
            recovery_required = True
    checks.append(_check("recovery", "inspection_required" if recovery_required else "clear",
                         "Examine saved evidence, last_good.json, and Docker resources that this project owns. Then give permission for interrupted-build recovery." if recovery_required else "The launcher has no build interruption record that makes recovery necessary."))
    prerequisites = folders_ready and inputs_ready and supported and runtime_ready
    return {"schema_version": 1, "project_name": project.name, "runtime_policy": RUNTIME_POLICY,
            "mode": selection.mode, "probed": probe, "review_ready": folders_ready and supported,
            "review_candidate": folders_ready and candidate_review, "review_read_only": system == "Windows",
            "build_prerequisites_ready": prerequisites, "build_ready": prerequisites and not recovery_required,
            "recovery_required": recovery_required, "authoring_ready": False, "checks": checks}
