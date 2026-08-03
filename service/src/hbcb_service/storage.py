"""Artifact storage interface, safe key policy, and MinIO adapter."""

from __future__ import annotations

import hashlib
import hmac
import os
import stat
from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import RLock
from typing import Any, BinaryIO, Dict, Optional, Protocol
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from .config import BUCKET_PATTERN, NAMESPACE_PATTERN
from .errors import StorageError
from .models import (
    ARTIFACT_CONTENT_TYPES,
    MAX_PUBLISHED_BYTES,
    REQUIRED_PUBLISHED_ARTIFACTS,
    ArtifactRecord,
)


HASH_CHUNK_BYTES = 1024 * 1024


def artifact_object_key(
    namespace: str,
    build_id: UUID,
    attempt_id: UUID,
    relative_path: str,
) -> str:
    if not isinstance(namespace, str) or NAMESPACE_PATTERN.fullmatch(namespace) is None:
        raise StorageError("invalid_namespace", "storage namespace is outside policy")
    if not isinstance(build_id, UUID) or not isinstance(attempt_id, UUID):
        raise StorageError("invalid_artifact_owner", "artifact owner is invalid")
    if relative_path not in ARTIFACT_CONTENT_TYPES:
        raise StorageError("invalid_artifact_path", "artifact path is outside the fixed allowlist")
    return (
        f"{namespace}/v1/builds/{build_id}/attempts/{attempt_id}/"
        f"complete-v1/{relative_path}"
    )


def publication_order(records: tuple[ArtifactRecord, ...]) -> tuple[ArtifactRecord, ...]:
    """Require one coherent exact set and place the success manifest last."""

    by_name = {record.relative_path: record for record in records}
    if len(records) != len(by_name) or set(by_name) != set(REQUIRED_PUBLISHED_ARTIFACTS):
        raise StorageError("artifact_set_mismatch", "publication requires the exact nine artifacts")
    build_ids = {record.build_id for record in records}
    attempt_ids = {record.attempt_id for record in records}
    buckets = {record.bucket for record in records}
    if len(build_ids) != 1 or len(attempt_ids) != 1 or len(buckets) != 1:
        raise StorageError("artifact_owner_mismatch", "publication artifacts do not share one owner")
    return tuple(
        by_name[name]
        for name in REQUIRED_PUBLISHED_ARTIFACTS
        if name != "manifest.json"
    ) + (by_name["manifest.json"],)


def _open_regular_file(path: Path, expected_bytes: int) -> BinaryIO:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise StorageError("artifact_unavailable", "artifact file is unavailable") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise StorageError("unsafe_artifact_file", "artifact source must be a regular file")
    if metadata.st_size != expected_bytes:
        raise StorageError("artifact_size_mismatch", "artifact byte count changed before upload")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise StorageError("artifact_unavailable", "artifact file could not be opened safely") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size != expected_bytes
            or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
        ):
            raise StorageError("artifact_changed", "artifact file changed while it was opened")
        return os.fdopen(descriptor, "rb")
    except Exception:
        os.close(descriptor)
        raise


def _hash_open_file(stream: BinaryIO, expected_bytes: int) -> str:
    digest = hashlib.sha256()
    consumed = 0
    try:
        stream.seek(0)
        while True:
            chunk = stream.read(HASH_CHUNK_BYTES)
            if not chunk:
                break
            consumed += len(chunk)
            if consumed > expected_bytes:
                raise StorageError("artifact_size_mismatch", "artifact grew during upload validation")
            digest.update(chunk)
        stream.seek(0)
    except OSError as exc:
        raise StorageError("artifact_unavailable", "artifact file could not be read") from exc
    if consumed != expected_bytes:
        raise StorageError("artifact_size_mismatch", "artifact byte count changed during validation")
    return digest.hexdigest()


class _HashingReader:
    """Record the exact byte stream consumed by the storage client."""

    def __init__(self, stream: BinaryIO, expected_bytes: int) -> None:
        self._stream = stream
        self._expected_bytes = expected_bytes
        self._digest = hashlib.sha256()
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)
        if not isinstance(chunk, bytes):
            raise StorageError("artifact_read_failed", "artifact stream returned invalid bytes")
        self.bytes_read += len(chunk)
        if self.bytes_read > self._expected_bytes:
            raise StorageError("artifact_size_mismatch", "artifact grew while it was uploaded")
        self._digest.update(chunk)
        return chunk

    def verified(self, expected_sha256: str) -> bool:
        return self.bytes_read == self._expected_bytes and hmac.compare_digest(
            self._digest.hexdigest(), expected_sha256
        )


class ArtifactStorage(Protocol):
    def store_file(self, record: ArtifactRecord, source: Path) -> ArtifactRecord:
        ...

    def presign_get(self, record: ArtifactRecord, *, expires_seconds: int) -> str:
        ...


class MinioArtifactStorage:
    """minio-py-compatible storage with fail-closed immutable writes.

    The caller constructs separately scoped internal and signing clients.  This
    keeps the internal service endpoint out of URLs returned to host clients.
    """

    def __init__(
        self,
        internal_client: Any,
        signing_client: Any,
        *,
        namespace: str,
        bucket: str,
    ) -> None:
        if NAMESPACE_PATTERN.fullmatch(namespace) is None:
            raise StorageError("invalid_namespace", "storage namespace is outside policy")
        if BUCKET_PATTERN.fullmatch(bucket) is None or ".." in bucket:
            raise StorageError("invalid_bucket", "storage bucket is outside policy")
        self._client = internal_client
        self._signer = signing_client
        self.namespace = namespace
        self.bucket = bucket

    def require_bucket(self) -> None:
        try:
            exists = self._client.bucket_exists(self.bucket)
        except Exception as exc:
            raise StorageError("storage_unavailable", "artifact bucket could not be inspected") from exc
        if exists is not True:
            raise StorageError("bucket_unavailable", "artifact bucket is not initialized")
        try:
            versioning = self._client.get_bucket_versioning(self.bucket)
        except Exception as exc:
            raise StorageError(
                "storage_unavailable", "artifact bucket versioning could not be inspected"
            ) from exc
        if getattr(versioning, "status", None) != "Enabled":
            raise StorageError(
                "bucket_versioning_required", "artifact bucket must have versioning enabled"
            )

    def store_file(self, record: ArtifactRecord, source: Path) -> ArtifactRecord:
        self._validate_record(record)
        self.require_bucket()
        source_path = Path(source)
        with _open_regular_file(source_path, record.bytes) as stream:
            digest = _hash_open_file(stream, record.bytes)
            if not hmac.compare_digest(digest, record.sha256):
                raise StorageError("artifact_hash_mismatch", "artifact hash changed before upload")

            existing = self._stat_or_none(record.object_key, record.version_id)
            if existing is not None:
                return self._reconcile_existing(record, existing)

            reader = _HashingReader(stream, record.bytes)
            try:
                result = self._client.put_object(
                    self.bucket,
                    record.object_key,
                    reader,
                    record.bytes,
                    content_type=record.content_type,
                    metadata={"sha256": record.sha256},
                )
            except StorageError:
                raise
            except Exception as exc:
                raise StorageError("storage_unavailable", "artifact upload failed") from exc
            version_id = getattr(result, "version_id", None)
            if not isinstance(version_id, str) or not version_id:
                raise StorageError(
                    "storage_version_missing", "artifact upload did not return a version ID"
                )
            if not reader.verified(record.sha256):
                raise StorageError(
                    "artifact_hash_mismatch", "artifact bytes changed while they were uploaded"
                )
        observed = self._stat_or_none(record.object_key, version_id)
        if observed is None:
            raise StorageError("storage_verification_failed", "uploaded artifact is not visible")
        return self._reconcile_existing(record, observed)

    def presign_get(self, record: ArtifactRecord, *, expires_seconds: int) -> str:
        self._validate_record(record)
        if not record.version_id:
            raise StorageError(
                "artifact_version_required", "published artifact lacks an immutable version ID"
            )
        if (
            isinstance(expires_seconds, bool)
            or not isinstance(expires_seconds, int)
            or not 30 <= expires_seconds <= 900
        ):
            raise StorageError("invalid_signed_url_ttl", "signed URL TTL is outside policy")
        try:
            value = self._signer.presigned_get_object(
                self.bucket,
                record.object_key,
                expires=timedelta(seconds=expires_seconds),
                version_id=record.version_id,
            )
        except Exception as exc:
            raise StorageError("storage_unavailable", "artifact URL could not be signed") from exc
        if not isinstance(value, str) or len(value) > 4096:
            raise StorageError("invalid_signed_url", "storage returned an invalid signed URL")
        try:
            parsed = urlsplit(value)
        except ValueError as exc:
            raise StorageError("invalid_signed_url", "storage returned an invalid signed URL") from exc
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
            raise StorageError("invalid_signed_url", "storage returned an invalid signed URL")
        return value

    def _validate_record(self, record: ArtifactRecord) -> None:
        if not isinstance(record, ArtifactRecord):
            raise StorageError("invalid_artifact", "artifact record is invalid")
        if record.bucket != self.bucket:
            raise StorageError("artifact_bucket_mismatch", "artifact bucket does not match adapter")
        expected = artifact_object_key(
            self.namespace, record.build_id, record.attempt_id, record.relative_path
        )
        if record.object_key != expected:
            raise StorageError("artifact_key_mismatch", "artifact object key is not canonical")

    def _stat_or_none(self, object_key: str, version_id: Optional[str] = None) -> Optional[Any]:
        try:
            return self._client.stat_object(
                self.bucket,
                object_key,
                version_id=version_id,
            )
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code in ("NoSuchKey", "NoSuchObject", "NoSuchFile", "NotFound"):
                return None
            raise StorageError("storage_unavailable", "artifact metadata could not be inspected") from exc

    @staticmethod
    def _metadata_sha256(observed: Any) -> Optional[str]:
        metadata = getattr(observed, "metadata", None)
        if not isinstance(metadata, Mapping):
            return None
        for key, value in metadata.items():
            if str(key).lower() in ("sha256", "x-amz-meta-sha256"):
                return str(value)
        return None

    def _reconcile_existing(self, expected: ArtifactRecord, observed: Any) -> ArtifactRecord:
        size = getattr(observed, "size", None)
        sha256 = self._metadata_sha256(observed)
        if size != expected.bytes or sha256 != expected.sha256:
            raise StorageError("immutable_object_conflict", "artifact object already exists with different evidence")
        etag = getattr(observed, "etag", None)
        version_id = getattr(observed, "version_id", None)
        if not isinstance(version_id, str) or not version_id:
            raise StorageError(
                "storage_version_missing", "artifact object does not expose a version ID"
            )
        if expected.version_id is not None and expected.version_id != version_id:
            raise StorageError(
                "immutable_object_conflict", "artifact version does not match stored evidence"
            )
        remote_sha256, remote_bytes = self._hash_remote_object(expected.object_key, version_id)
        if remote_bytes != expected.bytes or not hmac.compare_digest(
            remote_sha256, expected.sha256
        ):
            raise StorageError(
                "immutable_object_conflict", "artifact object body does not match stored evidence"
            )
        return replace(
            expected,
            etag=str(etag) if etag else None,
            version_id=version_id,
        )

    def _hash_remote_object(self, object_key: str, version_id: str) -> tuple[str, int]:
        response = None
        digest = hashlib.sha256()
        consumed = 0
        try:
            response = self._client.get_object(
                self.bucket,
                object_key,
                version_id=version_id,
            )
            while True:
                chunk = response.read(HASH_CHUNK_BYTES)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise StorageError(
                        "storage_verification_failed", "artifact storage returned invalid bytes"
                    )
                consumed += len(chunk)
                if consumed > MAX_PUBLISHED_BYTES:
                    raise StorageError(
                        "storage_verification_failed", "artifact object exceeds the byte budget"
                    )
                digest.update(chunk)
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(
                "storage_unavailable", "artifact body could not be verified"
            ) from exc
        finally:
            if response is not None:
                try:
                    response.close()
                finally:
                    release = getattr(response, "release_conn", None)
                    if callable(release):
                        release()
        return digest.hexdigest(), consumed


class InMemoryArtifactStorage:
    """Reference adapter with the same immutable-key and signing policy."""

    def __init__(self, *, namespace: str, bucket: str, public_base_url: str) -> None:
        if NAMESPACE_PATTERN.fullmatch(namespace) is None:
            raise StorageError("invalid_namespace", "storage namespace is outside policy")
        if BUCKET_PATTERN.fullmatch(bucket) is None or ".." in bucket:
            raise StorageError("invalid_bucket", "storage bucket is outside policy")
        parsed = urlsplit(public_base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
            raise StorageError("invalid_public_endpoint", "public storage endpoint is outside policy")
        self.namespace = namespace
        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/")
        self._lock = RLock()
        self._objects: Dict[str, tuple[ArtifactRecord, bytes]] = {}

    def store_file(self, record: ArtifactRecord, source: Path) -> ArtifactRecord:
        expected_key = artifact_object_key(
            self.namespace, record.build_id, record.attempt_id, record.relative_path
        )
        if record.bucket != self.bucket or record.object_key != expected_key:
            raise StorageError("artifact_key_mismatch", "artifact object key is not canonical")
        source_path = Path(source)
        with _open_regular_file(source_path, record.bytes) as stream:
            digest = _hash_open_file(stream, record.bytes)
            if not hmac.compare_digest(digest, record.sha256):
                raise StorageError("artifact_hash_mismatch", "artifact hash changed before upload")
            payload = stream.read()
        if len(payload) != record.bytes or not hmac.compare_digest(
            hashlib.sha256(payload).hexdigest(), record.sha256
        ):
            raise StorageError("artifact_hash_mismatch", "artifact changed while it was stored")
        with self._lock:
            existing = self._objects.get(record.object_key)
            if existing is not None:
                existing_record, existing_payload = existing
                if (
                    existing_record.sha256 != record.sha256
                    or existing_payload != payload
                    or (
                        record.version_id is not None
                        and record.version_id != existing_record.version_id
                    )
                ):
                    raise StorageError(
                        "immutable_object_conflict", "artifact object already exists with different evidence"
                    )
                return existing_record
            if record.version_id is not None:
                raise StorageError(
                    "artifact_version_conflict", "new artifact cannot preselect a storage version"
                )
            stored = replace(
                record,
                etag=hashlib.md5(payload, usedforsecurity=False).hexdigest(),
                version_id="sha256-" + record.sha256,
            )
            self._objects[record.object_key] = (stored, payload)
            return stored

    def presign_get(self, record: ArtifactRecord, *, expires_seconds: int) -> str:
        if not 30 <= expires_seconds <= 900:
            raise StorageError("invalid_signed_url_ttl", "signed URL TTL is outside policy")
        if not isinstance(record, ArtifactRecord) or not record.version_id:
            raise StorageError(
                "artifact_version_required", "published artifact lacks an immutable version ID"
            )
        with self._lock:
            stored = self._objects.get(record.object_key)
            if stored is None:
                raise StorageError("artifact_not_found", "artifact object does not exist")
            stored_record, _payload = stored
            if stored_record != record:
                raise StorageError(
                    "immutable_object_conflict", "artifact version does not match stored evidence"
                )
        query = urlencode(
            {"expires": str(expires_seconds), "versionId": record.version_id}
        )
        return f"{self.public_base_url}/{self.bucket}/{record.object_key}?{query}"

    def payload(self, object_key: str) -> bytes:
        with self._lock:
            try:
                return self._objects[object_key][1]
            except KeyError as exc:
                raise StorageError("artifact_not_found", "artifact object does not exist") from exc
