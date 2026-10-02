"""Trusted development controller. This is NOT an untrusted-code sandbox."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
from contextlib import contextmanager

from .contracts import MAX_JSON, Policy, identifier, read_json
from .acceptance import check
from .requirements import RequirementSet, canonical_hash, evaluate
from .verification import make_report
from .platform_io import exclusive_lock, is_redirected, safe_path as portable_safe_path

MAX_BUNDLE = 16 * 1024 * 1024
MAX_ATTEMPT = 512 * 1024 * 1024
MAX_LOG = 128 * 1024
MAX_FILES = 512


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def regular_tree(root: Path, max_bytes: int = MAX_ATTEMPT) -> list[Path]:
    files = []
    size = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            path = Path(directory) / name
            if is_redirected(path): raise ValueError("Symlinks and reparse points are not permitted in bundles or artifacts.")
            if path.is_dir(): continue
            if not path.is_file(): raise ValueError("nonregular artifact")
            size += path.stat().st_size
            files.append(path)
            if len(files) > MAX_FILES or size > max_bytes: raise ValueError("artifact budget exceeded")
    return sorted(files)


def bounded_evidence(root: Path) -> tuple[dict[str, str], list[str]]:
    """Retain bounded regular diagnostics; discard unsafe generated entries only.

    Called after the job group is killed. Does not follow symlinks. This bounds
    retained disk output in trusted mode, not a hostile process's host access.
    """
    manifest, discarded, size = {}, [], 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in list(dirs):
            path = Path(directory) / name
            if path.is_symlink():
                path.unlink(); dirs.remove(name)
                if len(discarded) < 100: discarded.append(str(path.relative_to(root)))
        for name in sorted(names):
            path = Path(directory) / name
            rel = str(path.relative_to(root))
            if path.is_symlink() or not path.is_file() or len(manifest) >= MAX_FILES - 2 or size + path.stat().st_size > MAX_ATTEMPT - 2 * MAX_JSON:
                path.unlink()
                if len(discarded) < 100: discarded.append(rel)
                continue
            size += path.stat().st_size
            manifest[rel] = digest(path)
    return manifest, discarded


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def sync_tree(root: Path) -> None:
    """Durability barrier before the current pointer can reference artifacts."""
    for path in regular_tree(root):
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    for directory, _, _ in os.walk(root, topdown=False, followlinks=False):
        sync_directory(Path(directory))


def promote(attempt: Path, store: Path, revision: str) -> None:
    sync_tree(attempt)
    destination = store / "accepted" / revision
    os.rename(attempt, destination)
    sync_directory(store / "attempts")
    sync_directory(store / "accepted")
    temp = store / f".last-good-{revision}.json"
    write_json(temp, {"revision": revision, "result_hash": digest(destination / "result.json")})
    os.replace(temp, store / "last_good.json")
    sync_directory(store)


def verify_accepted(directory: Path, expected_hash: str) -> dict:
    safe_path(directory)
    manifest_path = directory / "result.json"
    if manifest_path.is_symlink() or not manifest_path.is_file() or digest(manifest_path) != expected_hash:
        raise ValueError("parent manifest integrity mismatch")
    manifest = read_json(manifest_path)
    if manifest["status"] != "accepted": raise ValueError("parent not accepted")
    actual = {str(p.relative_to(directory)): digest(p) for p in regular_tree(directory) if p != manifest_path}
    if actual != manifest["artifacts"]: raise ValueError("parent artifact integrity mismatch")
    from .request_contract import validate_result_binding
    validate_result_binding(directory, manifest)
    return manifest


def safe_path(path: Path) -> Path:
    return portable_safe_path(path)


def snapshot(source: Path, target: Path) -> dict[str, str]:
    files = regular_tree(source, MAX_BUNDLE)
    if not (source / "builder.py").is_file(): raise ValueError("source requires builder.py")
    target.mkdir()
    result = {}
    for path in files:
        rel = path.relative_to(source)
        if "__pycache__" in rel.parts:
            continue
        if path.suffix not in {".py", ".json", ".png", ".jpg", ".jpeg", ".txt", ".md"}:
            raise ValueError('not permitted source/asset type')
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        result[str(rel)] = digest(dest)
    return result


def run_job(command: list[str], cwd: Path, log: Path, timeout: int = 120, budget_root: Path | None = None) -> dict:
    """Separate bounded process; deliberately makes no sandbox claim."""
    if os.name == "nt":
        raise RuntimeError("SOURCE_EXECUTION_UNAVAILABLE: Windows process-tree containment is not implemented")
    def limits():
        import resource  # Native source execution remains POSIX-only.
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (120, 125))
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    started = time.monotonic()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(cwd), "TMPDIR": str(cwd),
           "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"}
    with log.open("xb") as stream:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True, preexec_fn=limits)
        failure = None
        try:
            while process.poll() is None:
                if time.monotonic() - started > timeout: raise TimeoutError("job wall time limit")
                if log.stat().st_size > MAX_LOG: raise ValueError("job log limit")
                regular_tree(budget_root or cwd)
                time.sleep(0.1)
        except (TimeoutError, ValueError) as exc:
            failure = str(exc)
        finally:
            # Descendants must not survive a successful or failed leader.
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait()
    if log.stat().st_size > MAX_LOG:
        with log.open("r+b") as stream: stream.truncate(MAX_LOG)
    result = {"exit_code": process.returncode, "elapsed_seconds": round(time.monotonic() - started, 3)}
    if failure or process.returncode:
        raise RuntimeError(f'job failed: {failure or process.returncode}. See {log.name}')
    return result


@contextmanager
def store_lock(store: Path):
    # Keep the same .lock identity and POSIX flock behavior as existing stores.
    with exclusive_lock(store / ".lock"):
        yield


def build(*, source: Path, params: Path, policy_path: Path, store: Path, revision: str,
          parent: str | None = None, blender: str = "blender", trusted_reviewed_source: bool = False,
          renders: bool = True, intent: str = "", sandbox_image: str | None = None, requirements_path: Path | None = None,
          docker_executable: Path | None = None, docker_socket: Path = Path("/var/run/docker.sock"),
          request_binding: dict | None = None) -> dict:
    # Fail before reading/importing/executing author code. No implicit native fallback.
    if os.name == "nt":
        raise RuntimeError('SOURCE_EXECUTION_UNAVAILABLE: Windows builds are not implemented. Review is read-only')
    if trusted_reviewed_source and sandbox_image:
        raise ValueError("Select native mode with source review, or select a sandbox image. Do not select both.")
    if not trusted_reviewed_source and sandbox_image is None:
        raise RuntimeError('UNTRUSTED_EXECUTION_UNAVAILABLE: no audited sandbox backend. Review source and explicitly opt into trusted development only')
    if not isinstance(intent, str) or len(intent) > 2000:
        raise ValueError("revision intent must be at most 2000 characters")
    if request_binding is not None:
        from .request_contract import validate_binding
        validate_binding(request_binding)
        if sandbox_image is None or trusted_reviewed_source:
            raise ValueError("Model request execution requires the isolated Docker backend.")
        if request_binding["revision"] != revision:
            raise ValueError("The request binding targets a different revision.")
    identifier(revision)
    if parent is not None: identifier(parent)
    source, params, policy_path, store = [safe_path(p) for p in (source, params, policy_path, store)]
    if not source.is_dir(): raise ValueError("source must be a directory")
    if store == source or store.is_relative_to(source) or source.is_relative_to(store):
        raise ValueError("source and store must not overlap")
    provided_requirements = RequirementSet.parse(read_json(safe_path(requirements_path))) if requirements_path is not None else None
    raw_policy, raw_params = read_json(policy_path), read_json(params)
    policy = Policy.parse(raw_policy)
    if policy.profile == "print":
        raise ValueError('PRINT_ACCEPTANCE_UNAVAILABLE: scene profile only. Physical print gates are not implemented')
    if not isinstance(raw_params, dict): raise ValueError("parameters must be an object")
    backend = None
    if sandbox_image is not None:
        from .sandbox import DockerSandbox
        backend = DockerSandbox(sandbox_image, socket=docker_socket, docker_executable=docker_executable)
        backend.verify_runtime()  # Mandatory fail-closed preflight, no native fallback.
        binary = backend.blender
    else:
        binary = shutil.which(blender)
        if binary is None: raise ValueError('Blender not available')
        binary = str(Path(binary).resolve())
    store.mkdir(parents=True, exist_ok=True)
    with store_lock(store):
        requirements_lock = safe_path(store / "requirements.json")
        if request_binding is not None:
            from .request_contract import encoded, sha, runtime_identity, legacy_request, read_json as strict_json
            request, approval = request_binding["request"], request_binding["approval"]
            pointer_path = safe_path(store / "last_good.json")
            actual_parent = strict_json(pointer_path) if pointer_path.exists() else None
            prior_rules = canonical_hash(RequirementSet.parse(strict_json(requirements_lock, 4 * 1024 * 1024)).raw) if requirements_lock.exists() else None
            if request["parent"] != actual_parent or request["locked_requirements_hash"] != prior_rules:
                raise ValueError("The accepted parent or project rules changed after inspection.")
            if request["reference"] is not None:
                from .review_server import verified_revision
                ref = request["reference"]
                _, reference_result, reference_hash = verified_revision(store, ref["revision"])
                if reference_hash != ref["result_hash"]:
                    raise ValueError("The reference result changed after inspection.")
                if request["kind"] == "repair" and (reference_result["status"] != "rejected" or
                        reference_result.get("parent") != actual_parent["revision"] or
                        reference_result.get("parent_result_hash") != actual_parent["result_hash"]):
                    raise ValueError("The repair reference is not a rejected direct child of the accepted parent.")
            if request["legacy_request"] is not None:
                old = request["legacy_request"]
                if legacy_request(strict_json(store / "review/requests" / (old["request_id"] + ".json")), old["request_id"]) != old:
                    raise ValueError("The queued request changed after inspection.")
            if (sha(encoded(raw_params)) != approval["params_hash"] or sha(encoded(raw_policy)) != approval["policy_hash"] or
                    runtime_identity(Path(backend.docker), docker_socket, sandbox_image) != approval["runtime"]):
                raise ValueError("The approved inputs or runtime changed after inspection.")
        prior_rule_hashes=set()
        history=list((store/"accepted").glob("*/result.json"))+list((store/"attempts").glob("*/result.json"))
        if len(history)>512:raise ValueError("project history exceeds bounded requirements audit")
        for result_path in history:
            recorded=read_json(safe_path(result_path)).get("requirements_lock_hash")
            if recorded is not None:prior_rule_hashes.add(recorded)
        if prior_rule_hashes and not requirements_lock.exists():
            raise ValueError('The saved project requirements are missing. Restore the recorded rules before you start a build.')
        if requirements_lock.exists() or requirements_lock.is_symlink():
            requirements = RequirementSet.parse(read_json(requirements_lock))
            if prior_rule_hashes and prior_rule_hashes != {canonical_hash(requirements.raw)}:
                raise ValueError("established project requirements were changed")
            if provided_requirements is not None and canonical_hash(provided_requirements.raw) != canonical_hash(requirements.raw):
                raise ValueError('project requirements are locked. Build cannot replace or weaken them')
        else:
            requirements = provided_requirements or RequirementSet.parse({"schema_version":1,"requirements":[]})
            if request_binding is not None and canonical_hash(requirements.raw) != request_binding["approval"]["requirements_hash"]:
                raise ValueError("The request requirements differ from the reviewed definition.")
            if provided_requirements is not None:
                write_json(requirements_lock, requirements.raw)
                sync_directory(store)
        if request_binding is not None and canonical_hash(requirements.raw) != request_binding["approval"]["requirements_hash"]:
            raise ValueError("The request requirements differ from the reviewed definition.")
        for name in ("attempts", "accepted"):
            path = store / name
            safe_path(path)
            path.mkdir(exist_ok=True)
        for root in (store / "attempts", store / "accepted"):
            if (root / revision).exists() or (root / revision).is_symlink():
                raise ValueError('This revision ID is in use. Revisions are immutable.')
        pointer = store / "last_good.json"
        previous = None
        if pointer.exists() or pointer.is_symlink():
            current = read_json(pointer)
            if parent != current["revision"]: raise ValueError("parent must equal last good revision")
            previous_dir = safe_path(store / "accepted" / identifier(parent))
            previous_result=verify_accepted(previous_dir, current["result_hash"])
            if previous_result.get("requirements_lock_hash") is not None and previous_result["requirements_lock_hash"]!=canonical_hash(requirements.raw):
                raise ValueError("parent requirements lock differs from active rules")
            previous = read_json(previous_dir / "inspection" / "observation.json")
        elif parent is not None:
            raise ValueError("parent requires a last-good revision")
        attempt = store / "attempts" / revision
        attempt.mkdir()
        result = {"schema_version": 1, "revision": revision, "parent": parent,
                  "parent_result_hash": current["result_hash"] if previous is not None else None,
                  "intent": intent, "status": "needs_review", "execution_mode": "docker-isolated" if backend else "trusted-reviewed-development",
                  "security_boundary": backend.security_boundary if backend else "NOT_SANDBOXED", "jobs": {}, "failures": []}
        observation = None
        try:
            write_json(attempt / "params.json", raw_params)
            write_json(attempt / "policy.json", raw_policy)
            write_json(attempt / "requirements.json", requirements.raw)
            result["requirements_hash"] = canonical_hash(requirements.raw)
            result["requirements_lock_hash"] = result["requirements_hash"] if requirements_lock.exists() else None
            result["params_hash"] = digest(attempt / "params.json")
            result["policy_hash"] = digest(attempt / "policy.json")
            result["runtime_hash"] = sandbox_image if backend else digest(Path(binary))
            result["source_files"] = snapshot(source, attempt / "source")
            if request_binding is not None:
                from .request_contract import BINDING_FILE, source_manifest
                if (source_manifest(attempt / "source") != request_binding["approval"]["source_files"] or
                        result["source_files"] != request_binding["approval"]["source_files"]):
                    raise ValueError("The executed source differs from the inspected proposal.")
                write_json(attempt / BINDING_FILE, request_binding)
                result["request_binding_hash"] = digest(attempt / BINDING_FILE)
            result["controller_files"] = {p.name: digest(p) for p in Path(__file__).parent.glob("*.py") if backend or p.name != "sandbox.py"}
            authored = attempt / "authored"
            authored.mkdir()
            base = [binary, "--background", "--factory-startup", "--disable-autoexec", "--threads", "2", "--python-exit-code", "1"]
            def execute(stage, arguments, inputs, output, log):
                if backend is None:
                    return run_job(base + arguments, output, log, budget_root=attempt)
                mapping = {str(path): "/inputs/" + role for role, path in inputs.items()}
                mapping[str(output)] = "/output"
                def mapped(argument):
                    for prefix, replacement in sorted(mapping.items(), key=lambda item: -len(item[0])):
                        if argument == prefix or argument.startswith(prefix + os.sep):
                            return replacement + argument[len(prefix):]
                    return argument
                return backend.run(stage, [mapped(arg) for arg in arguments], inputs, output, log)
            result["jobs"]["author"] = execute("author", ["--python", str(attempt / "source" / "builder.py"), "--",
                "--params", str(attempt / "params.json"), "--output", str(authored / "scene.blend")],
                {"source": attempt / "source", "params": attempt / "params.json"}, authored, attempt / "author.log")
            regular_tree(authored)
            scene = authored / "scene.blend"
            if scene.is_symlink() or not scene.is_file(): raise ValueError("The author job did not write a regular scene file.")
            inspection = attempt / "inspection"
            inspection.mkdir()
            inspector = str(Path(__file__).with_name("inspect_scene.py"))
            command = ["--python", inspector, "--", "--input", str(scene), "--output", str(inspection),
                              "--expected-ids", ",".join(policy.parts)]
            if policy.profile == "print": command += ["--print-profile"]
            if not renders: command += ["--skip-renders"]
            result["jobs"]["inspect"] = execute("inspect", command, {"inspector": Path(inspector), "input": scene}, inspection, attempt / "inspect.log")
            regular_tree(inspection)
            observation = read_json(inspection / "observation.json")
            result["failures"] = check(policy, observation, previous)
            relation_report = evaluate(requirements, observation, previous, is_revision=parent is not None)
            result["failures"].extend({"check":"requirement", "requirement_id":row["id"], "status":row["status"], "measured":row["measured"], "evidence":row["evidence"]}
                                      for row in relation_report["requirements"] if row["hard"] and row["applicable"] and row["status"]!="pass")
            roundtrip = attempt / "roundtrip"
            roundtrip.mkdir()
            result["jobs"]["roundtrip"] = execute("roundtrip", ["--python", inspector, "--", "--mode", "roundtrip",
                "--input", str(inspection / "model.glb"), "--output", str(roundtrip),
                "--reference", str(inspection / "observation.json")], {"inspector": Path(inspector), "input": inspection / "model.glb", "reference": inspection / "observation.json"}, roundtrip, attempt / "roundtrip.log")
            reopened = attempt / "reopened"
            reopened.mkdir()
            result["jobs"]["reopen"] = execute("reopen", ["--python", inspector, "--", "--mode", "reopen",
                "--input", str(inspection / "scene.blend"), "--output", str(reopened),
                "--reference", str(inspection / "observation.json"), "--skip-renders"], {"inspector": Path(inspector), "input": inspection / "scene.blend", "reference": inspection / "observation.json"}, reopened, attempt / "reopen.log")
            # Recheck frozen provenance after author execution: detects accidental edits,
            # not malicious native code (which is unsupported in this mode).
            for rel, expected in result["source_files"].items():
                if digest(attempt / "source" / rel) != expected: raise ValueError("source changed during run")
            for filename, key in (("params.json", "params_hash"), ("policy.json", "policy_hash")):
                if digest(attempt / filename) != result[key]: raise ValueError("frozen input changed during run")
            for filename, expected in result["controller_files"].items():
                if digest(Path(__file__).with_name(filename)) != expected: raise ValueError("controller changed during run")
            if (result["requirements_lock_hash"] is not None and canonical_hash(read_json(requirements_lock)) != result["requirements_hash"]) or canonical_hash(read_json(attempt / "requirements.json")) != result["requirements_hash"]:
                raise ValueError("locked requirements changed during execution")
            if previous is not None:
                verify_accepted(previous_dir, current["result_hash"])
            result["provenance_verified"] = True
            if any(failure.get("status","fail") == "fail" for failure in result["failures"]):result["status"]="rejected"
            else:result["status"]="needs_review" if result["failures"] else "accepted"
        except Exception as exc:
            result["status"] = "needs_review"
            result["error"] = str(exc)[:2000]
        result["artifacts"], discarded = bounded_evidence(attempt)
        if discarded:
            result["status"] = "needs_review"
            result["discarded_unsafe_or_overbudget_entries"] = discarded
            result["provenance_verified"] = False
        retained_observation = attempt / "inspection" / "observation.json"
        try:
            observation = read_json(retained_observation) if retained_observation.is_file() else None
        except (ValueError,OSError) as exc:
            observation=None;result["status"]="needs_review";result["observation_error"]=str(exc)[:300]
        write_json(attempt / "verification.json", make_report(result, policy, observation, previous, requirements))
        result["artifacts"]["verification.json"] = digest(attempt / "verification.json")
        if request_binding is not None and "request_binding_hash" in result:
            from .request_contract import validate_result_binding
            validate_result_binding(attempt, result)
        write_json(attempt / "result.json", result)
        if result["status"] == "accepted":
            promote(attempt, store, revision)
        return result
