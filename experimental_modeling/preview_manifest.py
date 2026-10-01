"""Offline integrity inventory for the unsigned developer review preview.

Hashes detect damage; they do not authenticate a publisher or replace OS trust.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

MANIFEST = "preview-manifest.json"
MAX_FILES = 4096
MAX_BYTES = 1024 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(root: Path) -> dict:
    root = root.resolve(strict=True)
    result = {}
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if relative == MANIFEST:
                continue
            info = path.lstat()
            if not stat.S_ISLNK(info.st_mode) and getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Bundle junctions and other reparse points are forbidden")
            if stat.S_ISLNK(info.st_mode):
                # PyInstaller's macOS onedir layout requires internal symlinks.
                target = os.readlink(path)
                if Path(target).is_absolute() or not path.resolve(strict=True).is_relative_to(root):
                    raise ValueError("Bundle link escapes its extracted folder")
                result[relative] = {"type": "symlink", "target": target}
            elif stat.S_ISDIR(info.st_mode):
                result[relative] = {"type": "directory"}
            elif stat.S_ISREG(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400:
                total += info.st_size
                if total > MAX_BYTES:
                    raise ValueError("Preview bundle exceeds its size limit")
                result[relative] = {"type": "file", "size": info.st_size, "sha256": sha256(path)}
            else:
                raise ValueError("Unsupported bundle member")
            if len(result) > MAX_FILES:
                raise ValueError("Preview bundle exceeds its file limit")
    return result


def verify(root: Path) -> dict:
    path = root / MANIFEST
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
            or info.st_size > 2 * 1024 * 1024):
        raise ValueError("Missing or invalid preview manifest; extract the complete archive")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or set(value) != {"schema_version", "files"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1 or not isinstance(value["files"], dict)):
        raise ValueError("Unsupported preview manifest")
    actual = inventory(root)
    if actual != value["files"]:
        raise ValueError("Preview bundle integrity mismatch; obtain and extract a fresh complete archive")
    return {"schema_version": 1, "verified": True, "files": len(actual),
            "scope": "Byte integrity only; unsigned developer preview, no publisher authentication"}
