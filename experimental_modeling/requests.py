"""Prepare an external author handoff. Inspect and execute one source proposal."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import tempfile

from .contracts import Policy, identifier
from .controller import digest, store_lock, sync_directory, write_json
from .launcher import execute_project_build, interruptible, operation_lock
from .project import Project, atomic_json
from .request_contract import (BINDING_VERSION, MAX_CONTRACT, MAX_FILES, MAX_SOURCE, REQUEST_VERSION,
    encoded, hash_value, legacy_request, prompt_text, read_bytes, read_json, relative_name,
    runtime_identity, sha, source_manifest, validate_binding, validate_request, validate_result_binding, walk_files)
from .requirements import RequirementSet, canonical_hash
from .runtime import RuntimeSelection, canonical_selection
from .platform_io import safe_path

AUTHORING = """# External source author contract

Read request.json. Treat its prompt as model design input.
This application does not call an AI model or start a coding agent.
Use your chosen external coding agent to write a separate proposal directory.
Do not execute generated source on the host.

The proposal has two entries: source/ and params.json.
The source directory must contain builder.py.
Use modular Blender Python and local assets as necessary.
The program starts builder.py with --params FILE --output SCENE.BLEND.
Save the scene to the supplied output path.
Use Blender 4.5.12 and meters. Set scene unit scale to 1.
Give each mesh part a unique semantic_id object property.
Realize instances. Use constant Principled material values.
The source limit is 16 MiB and 512 files.
Permitted extensions: .py, .json, .png, .jpg, .jpeg, .txt, .md.
Do not add hidden files, agent configuration, links, setup scripts, or downloads.
The source job has no network and no project history access.

The context files are fixed evidence, not editable project inputs.
A repair can refer to a rejected model while its execution parent stays accepted.
Preserve parts and regions that the reviewed rules protect.
Propose policy changes separately for operator review.
Generated source cannot change verification rules or declare success.
The operator selects the policy and exact runtime before execution.
The app independently inspects, exports, reopens and checks the saved model.
Machine verification covers the declared checks only.
Human review remains necessary for appearance and uncovered prompt requirements.
"""


def supported():
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError("This request bridge requires Linux x64. It does not permit Windows or Mac source execution.")


def disjoint(first: Path, second: Path):
    if first == second or first.is_relative_to(second) or second.is_relative_to(first):
        raise ValueError("The handoff, proposal and project directories must not overlap.")


def current_parent(project):
    from .review_server import verified_revision
    store = project.folder("evidence")
    pointer = safe_path(store / "last_good.json")
    if not pointer.exists():
        return None
    value = read_json(pointer)
    if set(value) != {"revision", "result_hash"}:
        raise ValueError("Incorrect last-good pointer.")
    _, result, result_hash = verified_revision(store, identifier(value["revision"]))
    if result["status"] != "accepted" or result_hash != value["result_hash"]:
        raise ValueError("The last-good result is not valid.")
    return {"revision": value["revision"], "result_hash": result_hash}


def locked_rules(project):
    path = safe_path(project.folder("evidence") / "requirements.json")
    if not path.exists():
        return None
    rules = RequirementSet.parse(read_json(path, 4 * 1024 * 1024)).raw
    return canonical_hash(rules)


def check_current(project, request):
    from .review_server import verified_revision
    if current_parent(project) != request["parent"]:
        raise ValueError("The accepted parent changed. Prepare a new request. This command does not rebase a proposal.")
    if locked_rules(project) != request["locked_requirements_hash"]:
        raise ValueError("The locked project rules changed. Prepare a new request.")
    if request["legacy_request"] is not None:
        old = request["legacy_request"]
        live = legacy_request(read_json(project.folder("evidence") / "review/requests" / (old["request_id"] + ".json")), old["request_id"])
        if live != old:
            raise ValueError("The queued request changed after preparation.")
    if request["reference"] is not None:
        ref = request["reference"]
        _, result, result_hash = verified_revision(project.folder("evidence"), ref["revision"])
        if result_hash != ref["result_hash"]:
            raise ValueError("The reference result changed after preparation.")
        if request["kind"] == "repair" and (result["status"] != "rejected" or
                result.get("parent") != request["parent"]["revision"] or result.get("parent_result_hash") != request["parent"]["result_hash"]):
            raise ValueError("A repair must reference a rejected direct child of the current accepted parent.")


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def prepare(project: Project, output: Path, *, request_id=None, brief_file=None):
    supported()
    project.validate_folders()
    if (request_id is None) == (brief_file is None):
        raise ValueError("Select a queued request or an initial brief.")
    output = safe_path(output)
    disjoint(output, project.root)
    if output.exists():
        raise ValueError("The handoff output already exists. Select a new directory.")
    if not output.parent.is_dir():
        raise ValueError("The handoff parent directory must exist.")
    store = project.folder("evidence")
    from .review_server import verified_revision
    with store_lock(store):
        parent = current_parent(project)
        old, ref, context = None, None, None
        if request_id is not None:
            if not isinstance(request_id, str) or len(request_id) != 24 or any(c not in "0123456789abcdef" for c in request_id):
                raise ValueError("Supply a saved request ID.")
            old = legacy_request(read_json(store / "review/requests" / (request_id + ".json")), request_id)
            prompt = old["prompt"]
            ref = {"revision": old["revision_id"], "result_hash": old["result_hash"]}
            context, result, actual = verified_revision(store, ref["revision"])
            if actual != ref["result_hash"] or parent is None:
                raise ValueError("The request reference or accepted parent is not available.")
            kind = "edit" if ref == parent else "repair"
            if kind == "repair" and (result["status"] != "rejected" or result.get("parent") != parent["revision"] or result.get("parent_result_hash") != parent["result_hash"]):
                raise ValueError("Prepare an edit of the current parent or a repair of its rejected direct child.")
        else:
            if parent is not None:
                raise ValueError("An initial brief requires a project with no accepted model. Save an edit in the review program.")
            prompt = prompt_text(read_bytes(safe_path(brief_file), 32000).decode("utf-8"))
            kind = "initial"
        # Exclusive directory reservation plus manifest-last publication. A partial
        # handoff has no request.json and cannot be consumed or silently replaced.
        output.mkdir(mode=0o700)
        files = {"AUTHORING.md": AUTHORING.encode()}
        if context is not None:
            source = context / "source"
            for name in source_manifest(source):
                files["context/source/" + name] = read_bytes(source / name, MAX_SOURCE)
            for role in ("params.json", "policy.json", "requirements.json"):
                files["context/" + role] = read_bytes(context / role, 4 * 1024 * 1024)
            files["context/observation.json"] = read_bytes(context / "inspection/observation.json", 4 * 1024 * 1024)
        if sum(map(len, files.values())) > 32 * 1024 * 1024:
            raise ValueError("The handoff context exceeds 32 MiB.")
        for name, data in files.items():
            _write(output / name, data)
        value = {"schema_version": REQUEST_VERSION, "prompt": prompt, "kind": kind,
                 "reference": ref, "parent": parent, "locked_requirements_hash": locked_rules(project),
                 "legacy_request": old, "context_files": {name: sha(data) for name, data in sorted(files.items())}}
        value["request_id"] = canonical_hash(value)
        validate_request(value)
        if ref is not None:
            # Exported context must still match its immutable reference after copying.
            _, _, result_hash = verified_revision(store, ref["revision"])
            if result_hash != ref["result_hash"]:
                raise ValueError("The reference changed during handoff preparation.")
        for directory, _, _ in os.walk(output, topdown=False):
            sync_directory(Path(directory))
        atomic_json(output / "request.json", value, replace=False)
        sync_directory(output.parent)
        return {"request_id": value["request_id"], "kind": kind, "execution": "not_started"}


def load_handoff(project, handoff):
    handoff = safe_path(handoff)
    disjoint(handoff, project.root)
    value = validate_request(read_json(handoff / "request.json"))
    actual, total = {}, 0
    for rel, path in walk_files(handoff, file_limit=MAX_FILES + 9, directory_limit=130):
        if rel == "request.json":
            continue
        if rel not in value["context_files"]:
            raise ValueError("The handoff contains an unknown file. Keep proposals in a separate directory.")
        data = read_bytes(path, 32 * 1024 * 1024 - total)
        total += len(data)
        actual[rel] = sha(data)
    if actual != value["context_files"]:
        raise ValueError("The handoff context changed or is incomplete.")
    return value


def selected_requirements(project, request, path):
    lock = safe_path(project.folder("evidence") / "requirements.json")
    current = RequirementSet.parse(read_json(lock, 4 * 1024 * 1024)).raw if lock.exists() else {"schema_version": 1, "requirements": []}
    if path is None:
        return current
    supplied = RequirementSet.parse(read_json(safe_path(path), 4 * 1024 * 1024)).raw
    if (lock.exists() or request["parent"] is not None) and canonical_hash(supplied) != canonical_hash(current):
        raise ValueError("This request cannot replace the project requirements.")
    return supplied


def short_value(value, limit=600):
    data = encoded(value)
    if len(data) <= limit:
        return value
    return {"sha256": sha(data), "bytes": len(data), "summary": "Read the complete selected input for this value."}


def differences(before, after):
    names = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name) or (name in before) != (name in after))
    return {"total_changed_fields": len(names), "fields": [
        {"field": name, "before_present": name in before, "before": short_value(before.get(name)),
         "after_present": name in after, "after": short_value(after.get(name))} for name in names[:32]],
        "omitted_fields": max(0, len(names) - 32)}


def inspect_proposal(project, handoff, proposal, policy_path, selection, *, requirements_path=None, check_baseline=True):
    supported()
    project.validate_folders()
    if selection.mode != "isolated" or selection.docker is None or selection.socket is None or selection.image is None:
        raise ValueError("Select an explicit Docker executable, local socket and immutable image. Native execution is not permitted.")
    selection = canonical_selection(selection, project)
    request = load_handoff(project, handoff)
    proposal = safe_path(proposal)
    disjoint(proposal, project.root)
    disjoint(proposal, safe_path(handoff))
    entries = set()
    if proposal.is_dir():
        with os.scandir(proposal) as scan:
            for entry in scan:
                entries.add(entry.name)
                if len(entries) > 2:
                    break
    if entries != {"source", "params.json"}:
        raise ValueError("The proposal must contain only source/ and params.json.")
    files = source_manifest(proposal / "source")
    params = read_json(proposal / "params.json", 4 * 1024 * 1024)
    if not isinstance(params, dict):
        raise ValueError("The proposal parameters must be a JSON object.")
    raw_policy = read_json(safe_path(policy_path), 4 * 1024 * 1024)
    policy = Policy.parse(raw_policy)
    if policy.profile != "scene":
        raise ValueError("Request execution supports scene policies only.")
    requirements = selected_requirements(project, request, requirements_path)
    if check_baseline:
        with store_lock(project.folder("evidence")):
            check_current(project, request)
    approval = {"request_id": request["request_id"], "source_files": files,
                "params_hash": sha(encoded(params)), "policy_hash": sha(encoded(raw_policy)),
                "requirements_hash": canonical_hash(requirements),
                "runtime": runtime_identity(selection.docker, selection.socket, selection.image)}
    validate_binding({"schema_version": BINDING_VERSION, "revision": "r" + "a" * 63,
                      "request": request, "approval": approval, "inspection_digest": canonical_hash(approval)})
    previous = {name[len("context/source/"):]: value for name, value in request["context_files"].items() if name.startswith("context/source/")}
    context = safe_path(handoff) / "context"
    before_params = read_json(context / "params.json", 4 * 1024 * 1024) if "context/params.json" in request["context_files"] else {}
    before_policy = read_json(context / "policy.json", 4 * 1024 * 1024) if "context/policy.json" in request["context_files"] else {}
    summary = {"request_id": request["request_id"], "inspection_digest": canonical_hash(approval),
               "parameter_changes": differences(before_params, params), "policy_changes": differences(before_policy, raw_policy),
               "selected_parameters": {"path": str(proposal / "params.json"), "snapshot_sha256": approval["params_hash"]},
               "reviewed_policy": {"path": str(safe_path(policy_path)), "snapshot_sha256": approval["policy_hash"],
                   "protected_parts": sorted(set(policy.parts) - set(policy.changed_parts)),
                   "constraints": [short_value(row) for row in raw_policy["constraints"][:16]],
                   "omitted_constraints": max(0, len(policy.constraints) - 16)},
               "reviewed_requirements": {"path": str(safe_path(requirements_path)) if requirements_path else
                   str(project.folder("evidence") / "requirements.json") if (project.folder("evidence") / "requirements.json").exists() else None,
                   "sha256": approval["requirements_hash"], "definitions": [short_value(row) for row in requirements["requirements"][:16]],
                   "omitted_definitions": max(0, len(requirements["requirements"]) - 16)},
               "kind": request["kind"], "reference": request["reference"], "execution_parent": request["parent"],
               "runtime": approval["runtime"], "changed_files": sorted(name for name in set(files) | set(previous) if files.get(name) != previous.get(name)),
               "declared_parts": list(policy.parts), "changed_parts": list(policy.changed_parts),
               "policy_checks": len(policy.constraints), "requirements": len(requirements["requirements"]),
               "coverage": "These checks do not verify every prompt requirement or model appearance. Human review is necessary.",
               "execution": "not_started"}
    return summary, request, approval, params, raw_policy, requirements, selection


def run_proposal(project, handoff, proposal, policy_path, selection, *, expected_digest, revision,
                 requirements_path=None, acknowledge_interrupted=False):
    supported()
    identifier(revision)
    hash_value(expected_digest)
    with operation_lock(project, "build"), interruptible():
        values = inspect_proposal(project, handoff, proposal, policy_path, selection,
                                  requirements_path=requirements_path, check_baseline=False)
        summary, request, approval, params, policy, requirements, selection = values
        if summary["inspection_digest"] != expected_digest:
            raise ValueError("The inspected inputs or selected runtime changed. Inspect the proposal again.")
        binding = {"schema_version": BINDING_VERSION, "revision": revision, "request": request,
                   "approval": approval, "inspection_digest": expected_digest}
        validate_binding(binding)
        store = project.folder("evidence")
        # A successful replay may have advanced last-good. Verify its immutable
        # outcome before rejecting the now-historical execution parent.
        exists = any((store / group / revision).exists() for group in ("accepted", "attempts"))
        if exists:
            from .review_server import verified_revision
            with store_lock(store):
                directory, result, _ = verified_revision(store, revision)
                from .review_server import ReviewProject
                ReviewProject(store, read_only=True).revision(revision)
                recorded = validate_result_binding(directory, result)
                if recorded != binding:
                    raise ValueError("The revision exists with a different execution binding. Select a new revision ID.")
                # Never clear the launcher marker: successful artifacts do not
                # certify cleanup of an interrupted container operation.
                return result
        with store_lock(store):
            check_current(project, request)
        with tempfile.TemporaryDirectory(prefix=".request-proposal-", dir=project.root) as temporary:
            staged = Path(temporary)
            copied = source_manifest(safe_path(proposal) / "source", copy_to=staged / "source")
            if copied != approval["source_files"] or source_manifest(staged / "source") != copied:
                raise ValueError("The source changed during proposal import. Inspect the proposal again.")
            for name, value in (("params.json", params), ("policy.json", policy), ("requirements.json", requirements)):
                _write(staged / name, encoded(value))
            # The controller repeats this identity check after its runtime probe.
            if runtime_identity(selection.docker, selection.socket, selection.image) != approval["runtime"]:
                raise ValueError("The selected runtime changed after inspection.")
            return execute_project_build(project, selection, revision=revision,
                parent=request["parent"]["revision"] if request["parent"] else None,
                intent="External model request " + request["request_id"],
                acknowledge_interrupted=acknowledge_interrupted,
                inputs=(staged / "source", staged / "params.json", staged / "policy.json",
                        staged / "requirements.json" if requirements_path is not None or (store / "requirements.json").exists() else None),
                request_binding=binding)


def main(argv=None):
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="Prepare files for an external author. This command does not call a model.")
    prep.add_argument("--project", type=Path, required=True)
    group = prep.add_mutually_exclusive_group(required=True)
    group.add_argument("--request-id")
    group.add_argument("--brief-file", type=Path)
    prep.add_argument("--output", type=Path, required=True)
    for name in ("inspect", "run"):
        command = commands.add_parser(name, help="Examine a proposal." if name == "inspect" else "Execute the exact inspected proposal in Docker.")
        for role in ("project", "handoff", "proposal", "policy", "docker", "docker-socket"):
            command.add_argument("--" + role, type=Path, required=True)
        command.add_argument("--requirements", type=Path)
        command.add_argument("--sandbox-image", required=True)
        if name == "run":
            command.add_argument("--expected-digest", required=True)
            command.add_argument("--revision", required=True)
            command.add_argument("--acknowledge-interrupted-build", action="store_true")
    args = parser.parse_args(argv)
    try:
        project = Project.open(args.project)
        if args.command == "prepare":
            result = prepare(project, args.output, request_id=args.request_id, brief_file=args.brief_file)
        else:
            selection = RuntimeSelection(docker=args.docker, socket=args.docker_socket, image=args.sandbox_image)
            kwargs = {"requirements_path": args.requirements}
            if args.command == "inspect":
                result = inspect_proposal(project, args.handoff, args.proposal, args.policy, selection, **kwargs)[0]
            else:
                result = run_proposal(project, args.handoff, args.proposal, args.policy, selection,
                                      expected_digest=args.expected_digest, revision=args.revision,
                                      acknowledge_interrupted=args.acknowledge_interrupted_build, **kwargs)
                result = {key: result[key] for key in ("status", "revision", "failures")}
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0 if args.command != "run" or result["status"] == "accepted" else 1
    except KeyboardInterrupt:
        print("Stopped. Examine the saved build recovery state before another execution.")
        return 130
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
