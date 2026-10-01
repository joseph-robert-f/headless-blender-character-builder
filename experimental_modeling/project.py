"""Versioned portable project data, independent of OS-specific execution backends."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile

from .platform_io import safe_path as local_path

DESCRIPTOR = "modeling-project.json"
RUNTIME_POLICY = "blender-4.5.12-linux-amd64-v1"
# Keep the existing controller/reviewer evidence layout authoritative.
FOLDERS = {
    "source": "source", "assets": "source/assets", "constraints": "constraints",
    "candidates": "evidence/attempts", "accepted": "evidence/accepted", "evidence": "evidence",
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate project JSON field")
        result[key] = value
    return result


def read_object(path: Path) -> dict:
    path = local_path(path)
    if not path.is_file() or path.stat().st_size > 16384:
        raise ValueError("Expected a regular JSON file of at most 16 KiB")
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Incorrect JSON number')))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def atomic_json(path: Path, value: dict, *, replace: bool = True) -> None:
    """Replace small launcher metadata only; never touches model evidence/pointers."""
    path = local_path(path)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".launcher-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            # Exclusive publication: a concurrent initializer cannot clobber a winner.
            os.link(temporary, path, follow_symlinks=False)
            os.unlink(temporary)
        # Linux execution must not start before its recovery marker is durable.
        # Portable metadata creation on other systems is not a durability claim.
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@dataclass(frozen=True)
class Project:
    root: Path
    name: str

    @classmethod
    def open(cls, root: Path) -> "Project":
        root = local_path(root)
        value = read_object(root / DESCRIPTOR)
        if set(value) != {"schema_version", "name", "folders", "runtime_policy"}:
            raise ValueError("Unknown project fields. Do not put credentials or machine paths in the descriptor.")
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError('Not permitted project schema. The program does not change the schema version.')
        name = value["name"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name):
            raise ValueError("Project name must be 1–80 printable characters")
        if value["folders"] != FOLDERS:
            raise ValueError("The project folder layout must match version 1. Do not use other paths.")
        if value["runtime_policy"] != RUNTIME_POLICY:
            raise ValueError('Not permitted runtime policy. The program does not change the runtime version.')
        project = cls(root, name)
        for role in FOLDERS:
            project.folder(role)  # Reject redirected folders before any other operation.
        return project

    def folder(self, role: str) -> Path:
        return local_path(self.root / FOLDERS[role])

    def input(self, name: str) -> Path:
        if name not in {"params.json", "policy.json", "requirements.json"}:
            raise ValueError("Unknown project input")
        return local_path(self.folder("constraints") / name)

    def validate_folders(self) -> None:
        for role in FOLDERS:
            if not self.folder(role).is_dir():
                raise ValueError(f"Missing project folder {FOLDERS[role]}. Run init again to complete setup.")


def initialize(root: Path, name: str | None = None) -> Project:
    root = local_path(root)
    descriptor = root / DESCRIPTOR
    if descriptor.exists() or descriptor.is_symlink():
        project = Project.open(root)
        if name is not None and name != project.name:
            raise ValueError("The project has a different name. The init command does not replace it.")
    else:
        if root.exists() and (not root.is_dir() or any(root.iterdir())):
            raise ValueError("Use a new or empty folder. The init command does not accept or replace files in that folder.")
        selected_name = name if name is not None else root.name
        if not isinstance(selected_name, str) or not 1 <= len(selected_name.strip()) <= 80 or any(ord(c) < 32 for c in selected_name):
            raise ValueError("Project name must be 1–80 printable characters")
        root.mkdir(parents=True, exist_ok=True)
        try:
            atomic_json(descriptor, {"schema_version": 1, "name": selected_name,
                                    "folders": FOLDERS, "runtime_policy": RUNTIME_POLICY}, replace=False)
        except FileExistsError:
            # A competing init won. Validate it and never replace its descriptor.
            pass
        project = Project.open(root)
        if project.name != selected_name:
            raise ValueError("The project has a different name. The init command does not replace it.")
    # Descriptor first: an interrupted initialization can be resumed safely.
    for role in FOLDERS:
        project.folder(role).mkdir(parents=True, exist_ok=True)
    project.validate_folders()
    return project
