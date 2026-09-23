"""Exact-version MinIO adapter and private backup-file I/O.

Clients are injected; importing this module does not require the MinIO SDK.
Backup/restore orchestration remains in maintenance.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Iterator, Mapping, Optional

from .maintenance_common import (
    BACKUP_FILE_MODE,
    MAX_BACKUP_OBJECT_BYTES,
    MAX_BACKUP_PATH_BYTES,
    MAX_ORPHAN_SCAN_VERSIONS,
    ArtifactVersionEvidence,
    MaintenanceError,
    StoredObjectVersion,
    VersionedObjectClient,
    _artifact_owner_from_key,
    _bucket,
    _object_key,
    _sha256,
    _utc,
    _version_id,
    bounded_integer,
    validate_namespace,
)
from .models import ARTIFACT_CONTENT_TYPES, MAX_PUBLISHED_BYTES


def _absolute_backup_path(value: Any, label: str) -> Path:
    try:
        raw = os.fspath(value)
    except TypeError as exc:
        raise MaintenanceError("invalid_backup_path", f"{label} is invalid") from exc
    if (
        not isinstance(raw, str)
        or not raw
        or "\x00" in raw
        or len(raw.encode("utf-8")) > MAX_BACKUP_PATH_BYTES
    ):
        raise MaintenanceError("invalid_backup_path", f"{label} is invalid")
    path = Path(raw)
    if (
        not path.is_absolute()
        or path == Path(path.anchor)
        or raw != os.path.normpath(raw)
    ):
        raise MaintenanceError("ambiguous_backup_path", f"{label} must be an unambiguous absolute path")
    return path


def _safe_directory(path: Path, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise MaintenanceError("backup_path_unavailable", f"{label} is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise MaintenanceError("unsafe_backup_path", f"{label} must be a regular directory")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise MaintenanceError("unsafe_backup_mode", f"{label} must not be group/world writable")
    return metadata


@contextmanager
def _open_backup_file(path: Path, expected_bytes: int, label: str) -> Iterator[BinaryIO]:
    bounded_integer(
        expected_bytes,
        f"{label} bytes",
        minimum=1,
        maximum=MAX_BACKUP_OBJECT_BYTES,
    )
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise MaintenanceError("backup_file_unavailable", f"{label} is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise MaintenanceError("unsafe_backup_file", f"{label} must be a regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise MaintenanceError("unsafe_backup_mode", f"{label} must not be group/world writable")
    if metadata.st_size != expected_bytes:
        raise MaintenanceError("backup_size_mismatch", f"{label} size does not match inventory")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise MaintenanceError("backup_file_unavailable", f"{label} could not be opened safely") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size != expected_bytes
            or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
            or stat.S_IMODE(opened.st_mode) & 0o022
        ):
            raise MaintenanceError("backup_file_changed", f"{label} changed while being opened")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            yield stream
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_private_file(path: Path, payload: bytes) -> None:
    if not isinstance(payload, bytes) or not payload:
        raise MaintenanceError("invalid_backup_payload", "backup file payload is invalid")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, BACKUP_FILE_MODE)
    except OSError as exc:
        raise MaintenanceError("backup_write_failed", "backup file could not be created safely") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            written = stream.write(payload)
            if written != len(payload):
                raise MaintenanceError("backup_write_failed", "backup file write was incomplete")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _verify_backup_object(path: Path, evidence: ArtifactVersionEvidence) -> None:
    digest = hashlib.sha256()
    consumed = 0
    with _open_backup_file(path, evidence.bytes, "backup object") as stream:
        try:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise MaintenanceError("invalid_backup_object", "backup object returned invalid bytes")
                consumed += len(chunk)
                if consumed > evidence.bytes:
                    raise MaintenanceError("backup_size_mismatch", "backup object exceeds inventory")
                digest.update(chunk)
        except OSError as exc:
            raise MaintenanceError("backup_read_failed", "backup object could not be read") from exc
    if consumed != evidence.bytes or not hmac.compare_digest(digest.hexdigest(), evidence.sha256):
        raise MaintenanceError("backup_evidence_mismatch", "backup object does not match inventory")


def _copy_version_to_backup(
    client: VersionedObjectClient,
    evidence: ArtifactVersionEvidence,
    destination: Path,
) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(destination, flags, BACKUP_FILE_MODE)
    except OSError as exc:
        raise MaintenanceError("backup_write_failed", "backup object could not be created safely") from exc
    digest = hashlib.sha256()
    consumed = 0
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            try:
                chunks = client.iter_version(
                    evidence.bucket,
                    evidence.object_key,
                    evidence.version_id,
                )
                for chunk in chunks:
                    if not isinstance(chunk, bytes) or not chunk:
                        raise MaintenanceError(
                            "invalid_object_stream",
                            "artifact reader returned invalid bytes",
                        )
                    consumed += len(chunk)
                    if consumed > evidence.bytes:
                        raise MaintenanceError(
                            "artifact_size_mismatch",
                            "artifact version exceeds recorded bytes",
                        )
                    if stream.write(chunk) != len(chunk):
                        raise MaintenanceError(
                            "backup_write_failed",
                            "backup object write was incomplete",
                        )
                    digest.update(chunk)
            except MaintenanceError:
                raise
            except Exception as exc:
                raise MaintenanceError(
                    "storage_read_failed",
                    "artifact version could not be read",
                ) from exc
            if consumed != evidence.bytes or not hmac.compare_digest(
                digest.hexdigest(), evidence.sha256
            ):
                raise MaintenanceError(
                    "artifact_evidence_mismatch",
                    "artifact version does not match PostgreSQL evidence",
                )
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


class _UploadHashingReader:
    def __init__(self, source: BinaryIO, expected_bytes: int) -> None:
        self._source = source
        self._expected_bytes = expected_bytes
        self._digest = hashlib.sha256()
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        try:
            chunk = self._source.read(size)
        except OSError as exc:
            raise MaintenanceError("backup_read_failed", "backup object could not be read") from exc
        if not isinstance(chunk, bytes):
            raise MaintenanceError("invalid_backup_object", "backup object returned invalid bytes")
        self.bytes_read += len(chunk)
        if self.bytes_read > self._expected_bytes:
            raise MaintenanceError("backup_size_mismatch", "backup object exceeds inventory")
        self._digest.update(chunk)
        return chunk

    def verified(self, expected_sha256: str) -> bool:
        return self.bytes_read == self._expected_bytes and hmac.compare_digest(
            self._digest.hexdigest(), expected_sha256
        )


class MinioVersionedObjectClient:
    """minio-py-compatible exact-version reader/deleter."""

    def __init__(self, client: Any) -> None:
        if client is None:
            raise MaintenanceError("invalid_storage_client", "versioned object client is invalid")
        self._client = client

    def delete_version(self, bucket: str, object_key: str, version_id: str) -> None:
        _bucket(bucket)
        _object_key(object_key)
        _version_id(version_id)
        try:
            self._client.remove_object(bucket, object_key, version_id=version_id)
        except Exception as exc:
            raise MaintenanceError("storage_delete_failed", "exact artifact version deletion failed") from exc

    def inventory_namespace_versions(
        self,
        bucket: str,
        namespace: str,
        *,
        limit: int,
    ) -> tuple[StoredObjectVersion, ...]:
        """List a complete bounded namespace and verify each exact version.

        MinIO's iterator paginates ListObjectVersions internally.  We consume
        it to exhaustion and fail before reconciliation if the deployment is
        larger than the explicit scan ceiling, or if any row is a delete
        marker, malformed, duplicated, outside the canonical artifact key
        grammar, or inconsistent with exact-version HEAD evidence.
        """

        selected_bucket = _bucket(bucket)
        selected_namespace = validate_namespace(namespace)
        bounded_integer(
            limit,
            "orphan scan limit",
            minimum=1,
            maximum=MAX_ORPHAN_SCAN_VERSIONS,
        )
        prefix = f"{selected_namespace}/v1/builds/"
        collected: list[StoredObjectVersion] = []
        seen: set[tuple[str, str, str]] = set()
        try:
            iterator = self._client.list_objects(
                selected_bucket,
                prefix=prefix,
                recursive=True,
                include_version=True,
            )
            for listed in iterator:
                if len(collected) >= limit:
                    raise MaintenanceError(
                        "object_inventory_too_large",
                        "object inventory exceeds the configured scan limit",
                    )
                if getattr(listed, "is_delete_marker", None) is not False:
                    raise MaintenanceError(
                        "ambiguous_object_inventory",
                        "object inventory contains a delete marker",
                    )
                object_key = getattr(listed, "object_name", None)
                version_id = getattr(listed, "version_id", None)
                last_modified = getattr(listed, "last_modified", None)
                listed_size = getattr(listed, "size", None)
                if not isinstance(object_key, str) or not isinstance(version_id, str):
                    raise MaintenanceError(
                        "invalid_object_inventory",
                        "object inventory entry is incomplete",
                    )
                build_id, attempt_id, relative_path = _artifact_owner_from_key(
                    selected_namespace, object_key
                )
                exact_version = _version_id(version_id)
                if exact_version == "null":
                    raise MaintenanceError(
                        "ambiguous_object_inventory",
                        "object inventory contains an unversioned object",
                    )
                modified = _utc(last_modified, "object last_modified")
                listed_bytes = bounded_integer(
                    listed_size,
                    "listed artifact bytes",
                    minimum=1,
                    maximum=MAX_PUBLISHED_BYTES,
                )
                identity = (selected_bucket, object_key, exact_version)
                if identity in seen:
                    raise MaintenanceError(
                        "duplicate_object_version",
                        "object inventory contains duplicate versions",
                    )
                observed = self._client.stat_object(
                    selected_bucket,
                    object_key,
                    version_id=exact_version,
                )
                observed_version = _version_id(
                    getattr(observed, "version_id", None),
                    "observed version ID",
                )
                observed_size = bounded_integer(
                    getattr(observed, "size", None),
                    "artifact bytes",
                    minimum=1,
                    maximum=MAX_PUBLISHED_BYTES,
                )
                observed_modified = _utc(
                    getattr(observed, "last_modified", None),
                    "observed object last_modified",
                )
                # S3's version-list and exact-HEAD representations can differ
                # in sub-second timestamp precision.  Compare their stable UTC
                # second; identity, size, version ID, and digest still bind the
                # exact immutable object.
                if (
                    observed_version != exact_version
                    or listed_bytes != observed_size
                    or observed_modified.replace(microsecond=0)
                    != modified.replace(microsecond=0)
                ):
                    raise MaintenanceError(
                        "object_inventory_changed",
                        "object version changed during inventory",
                    )
                sha256 = self._metadata_sha256(observed)
                if sha256 is None:
                    raise MaintenanceError(
                        "object_evidence_missing",
                        "object version lacks required digest evidence",
                    )
                collected.append(
                    StoredObjectVersion(
                        namespace=selected_namespace,
                        build_id=build_id,
                        attempt_id=attempt_id,
                        relative_path=relative_path,
                        bucket=selected_bucket,
                        object_key=object_key,
                        version_id=exact_version,
                        sha256=sha256,
                        bytes=observed_size,
                        last_modified=modified,
                    )
                )
                seen.add(identity)
        except MaintenanceError:
            raise
        except Exception as exc:
            raise MaintenanceError(
                "storage_inspection_failed",
                "object version inventory could not be completed",
            ) from exc
        return tuple(sorted(collected, key=lambda item: item.identity))

    @staticmethod
    def _metadata_sha256(observed: Any) -> Optional[str]:
        metadata = getattr(observed, "metadata", None)
        if not isinstance(metadata, Mapping):
            return None
        for key, value in metadata.items():
            if str(key).lower() in ("sha256", "x-amz-meta-sha256"):
                try:
                    return _sha256(str(value))
                except MaintenanceError:
                    return None
        return None

    def assert_namespace_empty(self, bucket: str, namespace: str) -> None:
        _bucket(bucket)
        selected_namespace = validate_namespace(namespace)
        try:
            versions = self._client.list_objects(
                bucket,
                prefix=f"{selected_namespace}/v1/builds/",
                recursive=True,
                include_version=True,
            )
            for _version in versions:
                raise MaintenanceError(
                    "restore_target_not_empty",
                    "restore target namespace already contains object versions",
                )
        except MaintenanceError:
            raise
        except Exception as exc:
            raise MaintenanceError(
                "storage_inspection_failed",
                "restore target namespace could not be inspected",
            ) from exc

    def upload_version(
        self,
        bucket: str,
        object_key: str,
        source: BinaryIO,
        bytes: int,
        sha256: str,
        content_type: str,
    ) -> str:
        _bucket(bucket)
        _object_key(object_key)
        bounded_integer(
            bytes,
            "restore object bytes",
            minimum=1,
            maximum=MAX_PUBLISHED_BYTES,
        )
        _sha256(sha256)
        if content_type not in ARTIFACT_CONTENT_TYPES.values():
            raise MaintenanceError("invalid_content_type", "restore content type is outside policy")
        if not callable(getattr(source, "read", None)):
            raise MaintenanceError("invalid_backup_object", "backup object stream is invalid")
        try:
            self._client.stat_object(bucket, object_key)
        except Exception as exc:
            if getattr(exc, "code", None) not in (
                "NoSuchKey",
                "NoSuchObject",
                "NoSuchFile",
                "NotFound",
            ):
                raise MaintenanceError(
                    "storage_inspection_failed",
                    "restore target key could not be inspected",
                ) from exc
        else:
            raise MaintenanceError(
                "restore_target_not_empty",
                "restore target key already exists",
            )

        reader = _UploadHashingReader(source, bytes)
        try:
            result = self._client.put_object(
                bucket,
                object_key,
                reader,
                bytes,
                content_type=content_type,
                metadata={"sha256": sha256},
            )
        except MaintenanceError:
            raise
        except Exception as exc:
            raise MaintenanceError("storage_upload_failed", "backup object upload failed") from exc
        if not reader.verified(sha256):
            raise MaintenanceError("backup_evidence_mismatch", "uploaded backup bytes changed")
        version_id = getattr(result, "version_id", None)
        return _version_id(version_id, "restored version ID")

    def iter_version(self, bucket: str, object_key: str, version_id: str) -> Iterable[bytes]:
        _bucket(bucket)
        _object_key(object_key)
        _version_id(version_id)
        response = None
        try:
            response = self._client.get_object(bucket, object_key, version_id=version_id)
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise MaintenanceError("invalid_object_stream", "artifact reader returned invalid bytes")
                yield chunk
        except MaintenanceError:
            raise
        except Exception as exc:
            raise MaintenanceError("storage_read_failed", "exact artifact version read failed") from exc
        finally:
            if response is not None:
                try:
                    response.close()
                finally:
                    release = getattr(response, "release_conn", None)
                    if callable(release):
                        release()
