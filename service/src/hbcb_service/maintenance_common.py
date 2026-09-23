"""Shared maintenance evidence, bounds, and validation.

This module has no adapter or service imports. Keep shared type identity here
so the public maintenance facade and both adapters can be imported in any order.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, BinaryIO, Iterable, Mapping, Optional, Protocol
from uuid import UUID

from .config import BUCKET_PATTERN, NAMESPACE_PATTERN
from .errors import ServiceError
from .models import (
    ARTIFACT_CONTENT_TYPES,
    MAX_PUBLISHED_BYTES,
    OBJECT_KEY_PATTERN,
    SAFE_CODE_PATTERN,
    SHA256_PATTERN,
    BuildStatus,
    require_utc,
)


DEFAULT_SUCCEEDED_RETENTION_DAYS = 30
DEFAULT_FAILURE_RETENTION_DAYS = 7
DEFAULT_ORPHAN_GRACE_DAYS = 7
MAX_RETENTION_DAYS = 3650
MAX_MAINTENANCE_BATCH = 1000
MAX_ORPHAN_SCAN_VERSIONS = 100_000
MAX_QUEUE_RECONSTRUCTION_BUILDS = 10_000_000
MAX_DELETION_ATTEMPTS = 1_000_000
MAX_INVENTORY_BYTES = 64 * 1024 * 1024
MAX_DATABASE_EXPORT_BYTES = 64 * 1024 * 1024 * 1024
MAX_BACKUP_OBJECT_BYTES = (1 << 63) - 1
MAX_BACKUP_PATH_BYTES = 4096
DELETION_LEASE_SECONDS = 15 * 60
BACKUP_INVENTORY_VERSION = "backup-inventory/v1"
BACKUP_INVENTORY_NAME = "inventory.json"
BACKUP_OBJECTS_DIRECTORY = "objects"
BACKUP_DIRECTORY_MODE = 0o700
BACKUP_FILE_MODE = 0o600

RETENTION_STATUSES = (
    BuildStatus.SUCCEEDED,
    BuildStatus.FAILED,
    BuildStatus.CANCELED,
    BuildStatus.NEEDS_REVIEW,
)
ACTIVE_STATUSES = frozenset(
    {
        BuildStatus.VALIDATING,
        BuildStatus.QUEUED,
        BuildStatus.RUNNING,
        BuildStatus.GEOMETRY_QA,
        BuildStatus.RENDERING,
    }
)


class MaintenanceError(ServiceError):
    """Stable maintenance failure which never embeds client exception text."""


def bounded_integer(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise MaintenanceError("invalid_integer", f"{label} is outside policy")
    return value


def validate_namespace(value: Any) -> str:
    if not isinstance(value, str) or NAMESPACE_PATTERN.fullmatch(value) is None:
        raise MaintenanceError("invalid_namespace", "maintenance namespace is outside policy")
    return value


def _uuid(value: Any, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        parsed = UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise MaintenanceError("invalid_uuid", f"{label} is invalid") from exc
    if str(parsed) != str(value):
        raise MaintenanceError("invalid_uuid", f"{label} is invalid")
    return parsed


def _utc(value: Any, label: str) -> datetime:
    try:
        return require_utc(value, label)
    except ServiceError as exc:
        raise MaintenanceError("invalid_timestamp", f"{label} is invalid") from exc


def _bucket(value: Any) -> str:
    if (
        not isinstance(value, str)
        or BUCKET_PATTERN.fullmatch(value) is None
        or ".." in value
    ):
        raise MaintenanceError("invalid_bucket", "artifact bucket is outside policy")
    return value


def _object_key(value: Any) -> str:
    if (
        not isinstance(value, str)
        or OBJECT_KEY_PATTERN.fullmatch(value) is None
        or ".." in value
        or "\\" in value
    ):
        raise MaintenanceError("invalid_object_key", "artifact object key is outside policy")
    return value


def _version_id(value: Any, label: str = "artifact version ID") -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 256
        or any(ord(character) < 33 or ord(character) > 126 for character in value)
    ):
        raise MaintenanceError("invalid_version_id", f"{label} is outside policy")
    return value


def _sha256(value: Any) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise MaintenanceError("invalid_sha256", "artifact digest is outside policy")
    return value


def _safe_code(value: Any, label: str, *, required: bool) -> Optional[str]:
    if value is None and not required:
        return None
    if not isinstance(value, str) or SAFE_CODE_PATTERN.fullmatch(value) is None:
        raise MaintenanceError("invalid_code", f"{label} is outside policy")
    return value


def _artifact_owner_from_key(namespace: str, object_key: str) -> tuple[UUID, UUID, str]:
    """Parse only a canonical, allowlisted artifact key from this namespace."""

    selected_namespace = validate_namespace(namespace)
    selected_key = _object_key(object_key)
    prefix = f"{selected_namespace}/v1/builds/"
    if not selected_key.startswith(prefix):
        raise MaintenanceError("noncanonical_object_key", "artifact key is not canonical")
    remainder = selected_key[len(prefix) :]
    build_text, separator, remainder = remainder.partition("/attempts/")
    if not separator:
        raise MaintenanceError("noncanonical_object_key", "artifact key is not canonical")
    attempt_text, separator, relative_path = remainder.partition("/complete-v1/")
    if not separator or relative_path not in ARTIFACT_CONTENT_TYPES:
        raise MaintenanceError("noncanonical_object_key", "artifact key is not canonical")
    build_id = _uuid(build_text, "artifact build ID")
    attempt_id = _uuid(attempt_text, "artifact attempt ID")
    expected = (
        f"{selected_namespace}/v1/builds/{build_id}/attempts/{attempt_id}/"
        f"complete-v1/{relative_path}"
    )
    if not hmac.compare_digest(expected, selected_key):
        raise MaintenanceError("noncanonical_object_key", "artifact key is not canonical")
    return build_id, attempt_id, relative_path


@dataclass(frozen=True)
class RetentionPolicy:
    succeeded_days: int = DEFAULT_SUCCEEDED_RETENTION_DAYS
    failed_days: int = DEFAULT_FAILURE_RETENTION_DAYS
    canceled_days: int = DEFAULT_FAILURE_RETENTION_DAYS
    needs_review_days: int = DEFAULT_FAILURE_RETENTION_DAYS
    orphan_grace_days: int = DEFAULT_ORPHAN_GRACE_DAYS

    def __post_init__(self) -> None:
        for label, value in (
            ("succeeded retention days", self.succeeded_days),
            ("failed retention days", self.failed_days),
            ("canceled retention days", self.canceled_days),
            ("needs-review retention days", self.needs_review_days),
            ("orphan grace days", self.orphan_grace_days),
        ):
            bounded_integer(value, label, minimum=1, maximum=MAX_RETENTION_DAYS)

    def cutoffs(self, now: datetime) -> Mapping[BuildStatus, datetime]:
        current = _utc(now, "retention time")
        return MappingProxyType(
            {
                BuildStatus.SUCCEEDED: current - timedelta(days=self.succeeded_days),
                BuildStatus.FAILED: current - timedelta(days=self.failed_days),
                BuildStatus.CANCELED: current - timedelta(days=self.canceled_days),
                BuildStatus.NEEDS_REVIEW: current - timedelta(days=self.needs_review_days),
            }
        )


@dataclass(frozen=True)
class RetentionCandidate:
    build_id: UUID
    status: BuildStatus
    finished_at: datetime
    artifact_count: int
    artifact_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.build_id, UUID):
            raise MaintenanceError("invalid_build_id", "retention build ID is invalid")
        if self.status not in RETENTION_STATUSES or self.status in ACTIVE_STATUSES:
            raise MaintenanceError("active_build_selected", "retention selected a non-terminal build")
        _utc(self.finished_at, "finished_at")
        bounded_integer(
            self.artifact_count,
            "artifact count",
            minimum=0,
            maximum=256,
        )
        bounded_integer(
            self.artifact_bytes,
            "artifact bytes",
            minimum=0,
            maximum=MAX_PUBLISHED_BYTES,
        )


@dataclass(frozen=True)
class ArtifactVersionEvidence:
    namespace: str
    build_id: UUID
    bucket: str
    object_key: str
    version_id: str
    sha256: str
    bytes: int

    def __post_init__(self) -> None:
        validate_namespace(self.namespace)
        if not isinstance(self.build_id, UUID):
            raise MaintenanceError("invalid_build_id", "artifact build ID is invalid")
        _bucket(self.bucket)
        _object_key(self.object_key)
        _version_id(self.version_id)
        _sha256(self.sha256)
        bounded_integer(
            self.bytes,
            "artifact bytes",
            minimum=1,
            maximum=MAX_PUBLISHED_BYTES,
        )

    @property
    def identity(self) -> tuple[str, UUID, str, str, str]:
        return (
            self.namespace,
            self.build_id,
            self.bucket,
            self.object_key,
            self.version_id,
        )


@dataclass(frozen=True)
class StoredObjectVersion:
    """Exact immutable object version observed during a bounded inventory."""

    namespace: str
    build_id: UUID
    attempt_id: UUID
    relative_path: str
    bucket: str
    object_key: str
    version_id: str
    sha256: str
    bytes: int
    last_modified: datetime

    def __post_init__(self) -> None:
        validate_namespace(self.namespace)
        if not isinstance(self.build_id, UUID) or not isinstance(self.attempt_id, UUID):
            raise MaintenanceError("invalid_artifact_owner", "artifact owner is invalid")
        if self.relative_path not in ARTIFACT_CONTENT_TYPES:
            raise MaintenanceError("invalid_artifact_path", "artifact path is outside policy")
        _bucket(self.bucket)
        _object_key(self.object_key)
        _version_id(self.version_id)
        _sha256(self.sha256)
        bounded_integer(self.bytes, "artifact bytes", minimum=1, maximum=MAX_PUBLISHED_BYTES)
        _utc(self.last_modified, "object last_modified")
        parsed = _artifact_owner_from_key(self.namespace, self.object_key)
        if parsed != (self.build_id, self.attempt_id, self.relative_path):
            raise MaintenanceError("noncanonical_object_key", "artifact key is not canonical")

    @property
    def identity(self) -> tuple[str, str, str]:
        return (self.bucket, self.object_key, self.version_id)


@dataclass(frozen=True)
class DeletionWorkItem:
    queue_id: int
    evidence: ArtifactVersionEvidence
    status: str
    attempt_count: int
    queued_at: datetime
    claim_token: Optional[UUID] = None

    def __post_init__(self) -> None:
        bounded_integer(self.queue_id, "deletion queue ID", minimum=1, maximum=(1 << 63) - 1)
        if not isinstance(self.evidence, ArtifactVersionEvidence):
            raise MaintenanceError("invalid_deletion_item", "deletion evidence is invalid")
        if self.status not in ("pending", "failed", "deleting"):
            raise MaintenanceError("invalid_deletion_state", "deletion state is outside policy")
        bounded_integer(
            self.attempt_count,
            "deletion attempt count",
            minimum=0,
            maximum=MAX_DELETION_ATTEMPTS,
        )
        _utc(self.queued_at, "queued_at")
        if self.status == "deleting" and not isinstance(self.claim_token, UUID):
            raise MaintenanceError("invalid_deletion_claim", "claimed deletion lacks a token")
        if self.status != "deleting" and self.claim_token is not None:
            raise MaintenanceError("invalid_deletion_claim", "unclaimed deletion has a token")


@dataclass(frozen=True)
class RetentionApplyResult:
    deleted_build_ids: tuple[UUID, ...]
    queued_artifact_versions: int

    def __post_init__(self) -> None:
        if len(set(self.deleted_build_ids)) != len(self.deleted_build_ids):
            raise MaintenanceError("duplicate_build_id", "retention result contains duplicate builds")
        if any(not isinstance(build_id, UUID) for build_id in self.deleted_build_ids):
            raise MaintenanceError("invalid_build_id", "retention result build ID is invalid")
        bounded_integer(
            self.queued_artifact_versions,
            "queued artifact versions",
            minimum=0,
            maximum=MAX_MAINTENANCE_BATCH * 256,
        )


@dataclass(frozen=True)
class VersionRemap:
    namespace: str
    build_id: UUID
    bucket: str
    object_key: str
    source_version_id: str
    restored_version_id: str
    sha256: str
    bytes: int

    def __post_init__(self) -> None:
        validate_namespace(self.namespace)
        if not isinstance(self.build_id, UUID):
            raise MaintenanceError("invalid_build_id", "restore build ID is invalid")
        _bucket(self.bucket)
        _object_key(self.object_key)
        _version_id(self.source_version_id, "source version ID")
        _version_id(self.restored_version_id, "restored version ID")
        if hmac.compare_digest(self.source_version_id, self.restored_version_id):
            raise MaintenanceError("unchanged_version_id", "restore must produce a new version ID")
        _sha256(self.sha256)
        bounded_integer(
            self.bytes,
            "artifact bytes",
            minimum=1,
            maximum=MAX_PUBLISHED_BYTES,
        )

    @property
    def source_identity(self) -> tuple[str, UUID, str, str, str]:
        return (
            self.namespace,
            self.build_id,
            self.bucket,
            self.object_key,
            self.source_version_id,
        )


class VersionedObjectClient(Protocol):
    def delete_version(self, bucket: str, object_key: str, version_id: str) -> None: ...

    def inventory_namespace_versions(
        self,
        bucket: str,
        namespace: str,
        *,
        limit: int,
    ) -> tuple[StoredObjectVersion, ...]: ...

    def iter_version(
        self, bucket: str, object_key: str, version_id: str
    ) -> Iterable[bytes]: ...

    def assert_namespace_empty(self, bucket: str, namespace: str) -> None: ...

    def upload_version(
        self,
        bucket: str,
        object_key: str,
        source: BinaryIO,
        bytes: int,
        sha256: str,
        content_type: str,
    ) -> str: ...
