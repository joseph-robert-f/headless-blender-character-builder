"""Strict inert request bindings. No model calls, imports of author code, or jobs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

from .contracts import identifier
from .platform_io import safe_path
from .requirements import canonical_hash

REQUEST_VERSION = "model-request/v1"
BINDING_VERSION = "model-execution/v1"
BINDING_FILE = "request-binding.json"
MAX_CONTRACT = 256 * 1024
MAX_SOURCE = 16 * 1024 * 1024
MAX_FILES = 512
MAX_DIRECTORIES = 128
HASH = re.compile(r"[0-9a-f]{64}\Z")
EXTENSIONS = {".py", ".json", ".png", ".jpg", ".jpeg", ".txt", ".md"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> bytes:
    # Match the existing controller's immutable JSON artifact serialization.
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def hash_value(value):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError("Expected a complete SHA-256 digest.")
    return value


def fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError("The request contract has missing or unknown fields.")


def read_bytes(path: Path, limit: int) -> bytes:
    path = safe_path(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            raise ValueError("Use a bounded regular file with no hard links.")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        named = path.lstat()
        if (len(data) > limit or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or
                (after.st_dev, after.st_ino) != (named.st_dev, named.st_ino) or after.st_nlink != 1):
            raise ValueError("The input file changed during the read.")
        return data


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON fields are not permitted.")
        result[key] = value
    return result


def read_json(path: Path, limit: int = MAX_CONTRACT):
    return json.loads(read_bytes(path, limit).decode("utf-8"), object_pairs_hook=_unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Incorrect JSON number.")))


def prompt_text(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 8000 or not value.strip():
        raise ValueError("Supply a prompt of 1 to 8,000 characters.")
    if len(value.encode("utf-8")) > 32000:
        raise ValueError("The prompt must not exceed 32,000 UTF-8 bytes.")
    return value


def relative_name(value, *, source=False):
    if not isinstance(value, str) or not value or "\\" in value or any(ord(c) < 32 for c in value):
        raise ValueError("Incorrect relative file name.")
    path = PurePosixPath(value)
    if len(value.encode("utf-8")) > 1024 or len(path.parts) > 16 or any(len(part.encode("utf-8")) > 240 for part in path.parts):
        raise ValueError("The relative path exceeds the name or depth limit.")
    if path.is_absolute() or value != path.as_posix() or any(p in {"", ".", ".."} or p.startswith(".") for p in path.parts):
        raise ValueError("File names must be fixed relative paths.")
    if source and (path.suffix not in EXTENSIONS or any(p in {"AGENTS.md", "CLAUDE.md"} for p in path.parts)):
        raise ValueError("Agent configuration and this file type are not permitted.")
    return value


def walk_files(root: Path, *, file_limit=MAX_FILES, directory_limit=MAX_DIRECTORIES):
    """Stop enumeration itself at a budget, including empty directories."""
    root = safe_path(root)
    if not root.is_dir():
        raise ValueError("The source directory is missing.")
    pending, directories, files = [root], 0, 0
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = safe_path(Path(entry.path))
                rel = relative_name(path.relative_to(root).as_posix())
                if entry.is_dir(follow_symlinks=False):
                    directories += 1
                    if directories > directory_limit:
                        raise ValueError("The directory count exceeds its fixed limit.")
                    pending.append(path)
                else:
                    files += 1
                    if files > file_limit:
                        raise ValueError("The file count exceeds its fixed limit.")
                    yield rel, path


def source_manifest(root: Path, *, copy_to: Path | None = None):
    root = safe_path(root)
    result, total = {}, 0
    for rel, path in walk_files(root):
        relative_name(rel, source=True)
        data = read_bytes(path, MAX_SOURCE - total)
        total += len(data)
        result[rel] = sha(data)
        if copy_to is not None:
            target = copy_to / rel
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with target.open("xb") as stream:
                stream.write(data)
    if "builder.py" not in result:
        raise ValueError("The source requires builder.py.")
    return dict(sorted(result.items()))


def manifest(value, *, source=False, limit=MAX_FILES):
    if not isinstance(value, dict) or len(value) > limit:
        raise ValueError("Incorrect file manifest.")
    for name, digest in value.items():
        relative_name(name, source=source)
        hash_value(digest)
    if source and "builder.py" not in value:
        raise ValueError("The source manifest requires builder.py.")


def reference(value):
    if value is not None:
        fields(value, {"revision", "result_hash"})
        identifier(value["revision"])
        hash_value(value["result_hash"])


def legacy_request(value, expected_id=None):
    fields(value, {"schema_version", "request_id", "status", "revision_id", "result_hash", "prompt", "created_at", "execution"})
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["status"] != "queued" or value["execution"] != "not_started":
        raise ValueError("Incorrect legacy request record.")
    identifier(value["revision_id"])
    hash_value(value["result_hash"])
    prompt_text(value["prompt"])
    if not isinstance(value["created_at"], str) or not 1 <= len(value["created_at"]) <= 64:
        raise ValueError("Incorrect request time.")
    identity = sha((value["revision_id"] + "\0" + value["result_hash"] + "\0" + value["prompt"]).encode())[:24]
    if value["request_id"] != identity or (expected_id is not None and identity != expected_id):
        raise ValueError("The legacy request ID does not match its full content.")
    return value


def validate_request(value):
    if len(encoded(value)) > MAX_CONTRACT:
        raise ValueError("The request contract exceeds 256 KiB.")
    fields(value, {"schema_version", "request_id", "prompt", "kind", "reference", "parent", "locked_requirements_hash", "legacy_request", "context_files"})
    if value["schema_version"] != REQUEST_VERSION or value["kind"] not in {"initial", "edit", "repair"}:
        raise ValueError("Unsupported model request version or kind.")
    prompt_text(value["prompt"])
    reference(value["reference"])
    reference(value["parent"])
    if value["kind"] == "initial":
        if value["parent"] is not None or value["reference"] is not None or value["legacy_request"] is not None:
            raise ValueError("An initial request must not contain a revision reference.")
    elif value["parent"] is None or value["reference"] is None:
        raise ValueError("An edit or repair requires a reference and accepted parent.")
    if value["kind"] == "edit" and value["reference"] != value["parent"]:
        raise ValueError("An edit must refer to its accepted parent.")
    if value["locked_requirements_hash"] is not None:
        hash_value(value["locked_requirements_hash"])
    if value["legacy_request"] is not None:
        old = legacy_request(value["legacy_request"])
        if old["prompt"] != value["prompt"] or value["reference"] != {"revision": old["revision_id"], "result_hash": old["result_hash"]}:
            raise ValueError("The handoff differs from the queued request.")
    manifest(value["context_files"], limit=MAX_FILES + 8)
    for name in value["context_files"]:
        if name not in {"AUTHORING.md", "context/params.json", "context/policy.json", "context/requirements.json", "context/observation.json"}:
            if not name.startswith("context/source/"):
                raise ValueError("Unknown handoff context role.")
            relative_name(name[len("context/source/"):], source=True)
    if "AUTHORING.md" not in value["context_files"]:
        raise ValueError("The handoff has no author contract.")
    if value["request_id"] != canonical_hash({k: v for k, v in value.items() if k != "request_id"}):
        raise ValueError("The model request identity does not match its content.")
    return value


def runtime_identity(docker: Path, socket: Path, image: str):
    if not isinstance(image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("Supply an immutable local image ID.")
    docker, socket = safe_path(docker), safe_path(socket)
    info = socket.stat()
    if not stat.S_ISSOCK(info.st_mode):
        raise ValueError("The selected Docker socket is not a local Unix socket.")
    return {"mode": "docker-isolated", "image": image,
            "docker_sha256": sha(read_bytes(docker, 256 * 1024 * 1024)),
            "docker_path_sha256": sha(str(docker).encode()), "socket_path_sha256": sha(str(socket).encode()),
            "socket_device": info.st_dev, "socket_inode": info.st_ino}


def validate_runtime(value):
    fields(value, {"mode", "image", "docker_sha256", "docker_path_sha256", "socket_path_sha256", "socket_device", "socket_inode"})
    if value["mode"] != "docker-isolated" or not isinstance(value["image"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value["image"]):
        raise ValueError("Request execution requires the isolated runtime.")
    for key in ("docker_sha256", "docker_path_sha256", "socket_path_sha256"):
        hash_value(value[key])
    for key in ("socket_device", "socket_inode"):
        if type(value[key]) is not int or value[key] < 0:
            raise ValueError("Incorrect local runtime identity.")


def validate_binding(value):
    if len(encoded(value)) > MAX_CONTRACT:
        raise ValueError("The execution binding exceeds 256 KiB.")
    fields(value, {"schema_version", "revision", "request", "approval", "inspection_digest"})
    if value["schema_version"] != BINDING_VERSION:
        raise ValueError("Unsupported request execution version.")
    identifier(value["revision"])
    request = validate_request(value["request"])
    approval = value["approval"]
    fields(approval, {"request_id", "source_files", "params_hash", "policy_hash", "requirements_hash", "runtime"})
    if approval["request_id"] != request["request_id"]:
        raise ValueError("The execution approval targets a different request.")
    manifest(approval["source_files"], source=True)
    for key in ("params_hash", "policy_hash", "requirements_hash"):
        hash_value(approval[key])
    validate_runtime(approval["runtime"])
    if value["inspection_digest"] != canonical_hash(approval):
        raise ValueError("The execution approval digest is inconsistent.")
    return value


def validate_result_binding(directory: Path, result: dict):
    """Legacy absence is valid; every partial or inconsistent new binding fails."""
    safe_path(directory / BINDING_FILE)  # A dangling redirect is not legacy absence.
    present = BINDING_FILE in result.get("artifacts", {})
    declared = "request_binding_hash" in result
    if not present and not declared and not (directory / BINDING_FILE).exists():
        return None
    if not present or not declared:
        raise ValueError("The request execution binding is incomplete.")
    data = read_bytes(directory / BINDING_FILE, MAX_CONTRACT)
    if sha(data) != result["request_binding_hash"] or sha(data) != result["artifacts"][BINDING_FILE]:
        raise ValueError("The request execution binding hash is inconsistent.")
    binding = validate_binding(read_json(directory / BINDING_FILE))
    approval, request = binding["approval"], binding["request"]
    parent = None if result.get("parent") is None else {"revision": result["parent"], "result_hash": result.get("parent_result_hash")}
    if (binding["revision"] != result.get("revision") or request["parent"] != parent or
            approval["source_files"] != result.get("source_files") or approval["params_hash"] != result.get("params_hash") or
            approval["policy_hash"] != result.get("policy_hash") or approval["requirements_hash"] != result.get("requirements_hash") or
            approval["runtime"]["image"] != result.get("runtime_hash") or result.get("execution_mode") != "docker-isolated"):
        raise ValueError("The request binding differs from the executed inputs.")
    source = {name[len("source/"):]: digest for name, digest in result["artifacts"].items() if name.startswith("source/")}
    if source != approval["source_files"]:
        raise ValueError("The request source manifest differs from saved artifacts.")
    for name, key in (("params.json", "params_hash"), ("policy.json", "policy_hash")):
        if result["artifacts"].get(name) != approval[key]:
            raise ValueError("The request input hash differs from saved artifacts.")
    if canonical_hash(read_json(directory / "requirements.json", 4 * 1024 * 1024)) != approval["requirements_hash"]:
        raise ValueError("The request requirement binding is inconsistent.")
    return binding
