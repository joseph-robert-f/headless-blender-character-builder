"""Fail-closed conversion of a trusted builder output into upload records."""

from __future__ import annotations

import hashlib
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Callable, Tuple
from uuid import UUID

from shared.build_manifest import BuildManifest, REQUIRED_ARTIFACTS
from shared.json_contract import ContractValidationError

from .errors import WorkerError
from .models import ARTIFACT_CONTENT_TYPES, ArtifactRecord, utc_now
from .storage import artifact_object_key


MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_PUBLISHED_BYTES = 2 * 1024 * 1024 * 1024
EXACT_FILES = frozenset((*REQUIRED_ARTIFACTS, "manifest.json"))
EXACT_DIRECTORIES = frozenset({"diagnostics"})


def _hash_regular_file(path: Path, expected_bytes: int) -> str:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise WorkerError("artifact_unreadable", "builder artifact could not be opened") from exc
    digest = hashlib.sha256()
    consumed = 0
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode) or observed.st_size != expected_bytes:
            raise WorkerError("artifact_size_mismatch", "builder artifact size does not match manifest")
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, expected_bytes - consumed + 1))
            if not chunk:
                break
            consumed += len(chunk)
            if consumed > expected_bytes:
                raise WorkerError("artifact_size_mismatch", "builder artifact size does not match manifest")
            digest.update(chunk)
    except OSError as exc:
        raise WorkerError("artifact_unreadable", "builder artifact could not be read") from exc
    finally:
        os.close(descriptor)
    if consumed != expected_bytes:
        raise WorkerError("artifact_size_mismatch", "builder artifact size does not match manifest")
    return digest.hexdigest()


def _read_manifest(path: Path) -> tuple[bytes, BuildManifest]:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_MANIFEST_BYTES:
            raise WorkerError("manifest_invalid", "builder manifest is outside policy")
        payload = path.read_bytes()
    except WorkerError:
        raise
    except OSError as exc:
        raise WorkerError("manifest_unreadable", "builder manifest could not be read") from exc
    try:
        manifest = BuildManifest.from_json(payload)
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise WorkerError("manifest_invalid", "builder manifest is invalid") from exc
    if payload != manifest.canonical_bytes + b"\n":
        raise WorkerError("manifest_not_canonical", "builder manifest is not canonical")
    return payload, manifest


def _require_exact_tree(root: Path) -> None:
    try:
        root_metadata = root.lstat()
        if not stat.S_ISDIR(root_metadata.st_mode):
            raise WorkerError("artifact_tree_invalid", "builder output is not a directory")
        files = set()
        directories = set()
        for index, path in enumerate(root.rglob("*"), start=1):
            if index > len(EXACT_FILES) + len(EXACT_DIRECTORIES):
                raise WorkerError("artifact_tree_invalid", "builder output contains unexpected entries")
            relative = path.relative_to(root).as_posix()
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise WorkerError("artifact_tree_invalid", "builder output contains a symlink")
            if stat.S_ISDIR(metadata.st_mode):
                directories.add(relative)
            elif stat.S_ISREG(metadata.st_mode):
                if metadata.st_size <= 0:
                    raise WorkerError("artifact_tree_invalid", "builder output contains an empty file")
                files.add(relative)
            else:
                raise WorkerError("artifact_tree_invalid", "builder output contains a special file")
    except WorkerError:
        raise
    except OSError as exc:
        raise WorkerError("artifact_tree_unreadable", "builder output could not be inspected") from exc
    if files != set(EXACT_FILES) or directories != set(EXACT_DIRECTORIES):
        raise WorkerError("artifact_tree_invalid", "builder output differs from complete-v1")


def records_from_output(
    root: Path,
    *,
    build_id: UUID,
    attempt_id: UUID,
    request_sha256: str,
    spec_sha256: str,
    namespace: str,
    bucket: str,
    now: Callable[[], datetime] = utc_now,
) -> Tuple[ArtifactRecord, ...]:
    """Verify every local byte and return the exact nine upload records."""

    _require_exact_tree(root)
    manifest_payload, manifest = _read_manifest(root / "manifest.json")
    if manifest.request_sha256 != request_sha256 or manifest.spec_sha256 != spec_sha256:
        raise WorkerError("manifest_provenance_mismatch", "builder manifest does not belong to the build")
    created_at = now()
    records = []
    total = 0
    for relative_path in (*REQUIRED_ARTIFACTS, "manifest.json"):
        path = root / relative_path
        if relative_path == "manifest.json":
            expected_bytes = len(manifest_payload)
            expected_sha256 = hashlib.sha256(manifest_payload).hexdigest()
        else:
            entry = manifest.artifacts[relative_path]
            expected_bytes = int(entry["bytes"])
            expected_sha256 = str(entry["sha256"])
        actual_sha256 = _hash_regular_file(path, expected_bytes)
        if actual_sha256 != expected_sha256:
            raise WorkerError("artifact_hash_mismatch", "builder artifact hash does not match manifest")
        total += expected_bytes
        if total > MAX_PUBLISHED_BYTES:
            raise WorkerError("artifact_budget", "builder artifacts exceed the aggregate budget")
        records.append(
            ArtifactRecord(
                build_id=build_id,
                attempt_id=attempt_id,
                relative_path=relative_path,
                bucket=bucket,
                object_key=artifact_object_key(
                    namespace,
                    build_id,
                    attempt_id,
                    relative_path,
                ),
                sha256=expected_sha256,
                bytes=expected_bytes,
                content_type=ARTIFACT_CONTENT_TYPES[relative_path],
                created_at=created_at,
                etag=None,
                version_id=None,
            )
        )
    return tuple(records)


__all__ = ["records_from_output"]
