"""Deterministic source-revision digests used in build provenance."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable


def _selected_files(root: Path, *, include_launcher: bool) -> Iterable[Path]:
    package_names = ("blender", "shared", "builder_cli") if include_launcher else ("blender", "shared")
    files = [
        path
        for package_name in package_names
        for path in root.joinpath(package_name).rglob("*.py")
    ]
    if include_launcher:
        files.extend((root / "pyproject.toml", root / "scripts" / "builder"))
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def source_revision(root: Path, *, include_launcher: bool) -> str:
    """Hash selected source names and bytes with unambiguous framing.

    Native execution records the deterministic Blender/shared implementation.
    A container additionally records its trusted CLI and packaging entrypoint.
    """

    resolved = root.resolve(strict=True)
    files = tuple(_selected_files(resolved, include_launcher=include_launcher))
    if not files:
        raise OSError("source revision contains no files")
    digest = hashlib.sha256()
    for path in files:
        if not path.is_file() or path.is_symlink():
            raise OSError("source revision contains a missing or unsafe file")
        relative = path.relative_to(resolved).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


__all__ = ["source_revision"]
