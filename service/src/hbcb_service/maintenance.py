"""Bounded retention, recovery, backup, and restore maintenance primitives.

PostgreSQL is authoritative.  Redis is reconstructed only from rows whose
current PostgreSQL status is ``queued``.  Artifact deletion work is durable and
contains the exact S3 bucket, object key, version ID, digest, and byte count
captured before a build row is deleted.

The module deliberately accepts injected DB, S3, Redis, and database-export
clients.  A deployment should give the process a separately scoped maintenance
database role; the API and worker roles intentionally lack deletion authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, BinaryIO, Callable, Iterable, Iterator, Mapping, Optional, Protocol, Sequence
from uuid import UUID, uuid4

from .config import BUCKET_PATTERN, NAMESPACE_PATTERN
from .errors import ServiceError
from .models import (
    ARTIFACT_CONTENT_TYPES,
    MAX_PUBLISHED_BYTES,
    OBJECT_KEY_PATTERN,
    SAFE_CODE_PATTERN,
    SHA256_PATTERN,
    WORKER_ID_PATTERN,
    BuildStatus,
    require_utc,
)


DEFAULT_SUCCEEDED_RETENTION_DAYS = 30
DEFAULT_FAILURE_RETENTION_DAYS = 7
DEFAULT_ORPHAN_GRACE_DAYS = 7
MAX_RETENTION_DAYS = 3650
MAX_MAINTENANCE_BATCH = 1000
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


def _artifact_relative_path(evidence: "ArtifactVersionEvidence") -> str:
    """Return the allowlisted relative path only for an exact canonical key."""

    prefix = f"{evidence.namespace}/v1/builds/{evidence.build_id}/attempts/"
    if not evidence.object_key.startswith(prefix):
        raise MaintenanceError("noncanonical_object_key", "artifact key is not canonical")
    remainder = evidence.object_key[len(prefix) :]
    attempt_text, separator, relative_path = remainder.partition("/complete-v1/")
    if not separator or relative_path not in ARTIFACT_CONTENT_TYPES:
        raise MaintenanceError("noncanonical_object_key", "artifact key is not canonical")
    attempt_id = _uuid(attempt_text, "artifact attempt ID")
    expected = (
        f"{evidence.namespace}/v1/builds/{evidence.build_id}/attempts/"
        f"{attempt_id}/complete-v1/{relative_path}"
    )
    if not hmac.compare_digest(expected, evidence.object_key):
        raise MaintenanceError("noncanonical_object_key", "artifact key is not canonical")
    return relative_path


def _backup_object_name(index: int) -> str:
    bounded_integer(
        index,
        "backup object index",
        minimum=0,
        maximum=MAX_MAINTENANCE_BATCH * 256 - 1,
    )
    return f"{index:08d}.bin"


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
class RetentionRunResult:
    dry_run: bool
    candidates: tuple[RetentionCandidate, ...]
    deleted_build_ids: tuple[UUID, ...]
    queued_artifact_versions: int


@dataclass(frozen=True)
class DeletionRunResult:
    dry_run: bool
    considered: int
    deleted: int
    failed: int


@dataclass(frozen=True)
class RedisReconstructionResult:
    dry_run: bool
    derived_queued_builds: int
    enqueued: int

    def __post_init__(self) -> None:
        bounded_integer(
            self.derived_queued_builds,
            "derived queued builds",
            minimum=0,
            maximum=MAX_QUEUE_RECONSTRUCTION_BUILDS,
        )
        bounded_integer(
            self.enqueued,
            "reconstructed queue entries",
            minimum=0,
            maximum=self.derived_queued_builds,
        )
        if self.dry_run and self.enqueued != 0:
            raise MaintenanceError(
                "invalid_queue_reconstruction",
                "dry-run queue reconstruction mutated Redis",
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


def _reject_duplicate_pairs(pairs: Sequence[tuple[str, Any]]) -> Mapping[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MaintenanceError("duplicate_json_key", "backup inventory has duplicate keys")
        result[key] = value
    return result


@dataclass(frozen=True)
class BackupInventory:
    namespace: str
    generated_at: datetime
    artifacts: tuple[ArtifactVersionEvidence, ...]
    inventory_version: str = BACKUP_INVENTORY_VERSION

    def __post_init__(self) -> None:
        validate_namespace(self.namespace)
        _utc(self.generated_at, "generated_at")
        if self.inventory_version != BACKUP_INVENTORY_VERSION:
            raise MaintenanceError("unsupported_inventory", "backup inventory version is unsupported")
        if len(self.artifacts) > MAX_MAINTENANCE_BATCH * 256:
            raise MaintenanceError("inventory_too_large", "backup inventory is outside policy")
        identities = set()
        for artifact in self.artifacts:
            if not isinstance(artifact, ArtifactVersionEvidence) or artifact.namespace != self.namespace:
                raise MaintenanceError("invalid_inventory", "backup artifact evidence is invalid")
            if artifact.identity in identities:
                raise MaintenanceError("duplicate_inventory_item", "backup inventory has duplicate artifacts")
            identities.add(artifact.identity)

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "artifacts": [
                {
                    "build_id": str(item.build_id),
                    "bucket": item.bucket,
                    "bytes": item.bytes,
                    "namespace": item.namespace,
                    "object_key": item.object_key,
                    "sha256": item.sha256,
                    "version_id": item.version_id,
                }
                for item in self.artifacts
            ],
            "generated_at": self.generated_at.isoformat().replace("+00:00", "Z"),
            "inventory_version": self.inventory_version,
            "namespace": self.namespace,
        }

    def to_json_bytes(self) -> bytes:
        payload = json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(payload) > MAX_INVENTORY_BYTES:
            raise MaintenanceError("inventory_too_large", "backup inventory is outside policy")
        return payload

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> "BackupInventory":
        if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_INVENTORY_BYTES:
            raise MaintenanceError("invalid_inventory", "backup inventory payload is outside policy")
        try:
            raw = json.loads(
                payload.decode("utf-8", "strict"),
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=lambda _value: (_ for _ in ()).throw(
                    MaintenanceError("invalid_inventory", "backup inventory number is invalid")
                ),
            )
        except MaintenanceError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise MaintenanceError("invalid_inventory", "backup inventory is invalid") from exc
        if not isinstance(raw, Mapping) or set(raw) != {
            "artifacts",
            "generated_at",
            "inventory_version",
            "namespace",
        }:
            raise MaintenanceError("invalid_inventory", "backup inventory shape is invalid")
        artifacts_raw = raw["artifacts"]
        if not isinstance(artifacts_raw, list):
            raise MaintenanceError("invalid_inventory", "backup artifact list is invalid")
        artifacts = []
        expected_fields = {
            "build_id",
            "bucket",
            "bytes",
            "namespace",
            "object_key",
            "sha256",
            "version_id",
        }
        for item in artifacts_raw:
            if not isinstance(item, Mapping) or set(item) != expected_fields:
                raise MaintenanceError("invalid_inventory", "backup artifact entry is invalid")
            artifacts.append(
                ArtifactVersionEvidence(
                    namespace=item["namespace"],
                    build_id=_uuid(item["build_id"], "backup build ID"),
                    bucket=item["bucket"],
                    object_key=item["object_key"],
                    version_id=item["version_id"],
                    sha256=item["sha256"],
                    bytes=bounded_integer(
                        item["bytes"],
                        "artifact bytes",
                        minimum=1,
                        maximum=MAX_PUBLISHED_BYTES,
                    ),
                )
            )
        generated = raw["generated_at"]
        if not isinstance(generated, str) or not generated.endswith("Z"):
            raise MaintenanceError("invalid_inventory", "backup timestamp is invalid")
        try:
            generated_at = datetime.fromisoformat(generated[:-1] + "+00:00")
        except ValueError as exc:
            raise MaintenanceError("invalid_inventory", "backup timestamp is invalid") from exc
        return cls(
            namespace=raw["namespace"],
            generated_at=generated_at,
            artifacts=tuple(artifacts),
            inventory_version=raw["inventory_version"],
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_json_bytes()).hexdigest()


@dataclass(frozen=True)
class DatabaseExportEvidence:
    sha256: str
    bytes: int

    def __post_init__(self) -> None:
        _sha256(self.sha256)
        bounded_integer(
            self.bytes,
            "database export bytes",
            minimum=1,
            maximum=MAX_DATABASE_EXPORT_BYTES,
        )


@dataclass(frozen=True)
class BackupExportEvidence:
    inventory: BackupInventory
    inventory_sha256: str
    inventory_bytes: int
    database: DatabaseExportEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.inventory, BackupInventory):
            raise MaintenanceError("invalid_inventory", "backup inventory is invalid")
        _sha256(self.inventory_sha256)
        payload = self.inventory.to_json_bytes()
        if self.inventory_sha256 != hashlib.sha256(payload).hexdigest():
            raise MaintenanceError("inventory_hash_mismatch", "backup inventory hash is invalid")
        if self.inventory_bytes != len(payload):
            raise MaintenanceError("inventory_size_mismatch", "backup inventory size is invalid")
        if not isinstance(self.database, DatabaseExportEvidence):
            raise MaintenanceError("invalid_database_export", "database export evidence is invalid")


@dataclass(frozen=True)
class ObjectBackupEvidence:
    inventory_sha256: str
    artifact_count: int
    artifact_bytes: int

    def __post_init__(self) -> None:
        _sha256(self.inventory_sha256)
        bounded_integer(
            self.artifact_count,
            "backup artifact count",
            minimum=0,
            maximum=MAX_MAINTENANCE_BATCH * 256,
        )
        bounded_integer(
            self.artifact_bytes,
            "backup artifact bytes",
            minimum=0,
            maximum=MAX_BACKUP_OBJECT_BYTES,
        )


@dataclass(frozen=True)
class ObjectRestoreResult:
    dry_run: bool
    artifact_count: int
    artifact_bytes: int
    uploaded: int
    remapped: int
    remaps: tuple[VersionRemap, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.dry_run, bool):
            raise MaintenanceError("invalid_restore_result", "restore dry-run state is invalid")
        bounded_integer(
            self.artifact_count,
            "restore artifact count",
            minimum=0,
            maximum=MAX_MAINTENANCE_BATCH * 256,
        )
        bounded_integer(
            self.artifact_bytes,
            "restore artifact bytes",
            minimum=0,
            maximum=MAX_BACKUP_OBJECT_BYTES,
        )
        bounded_integer(
            self.uploaded,
            "restore uploaded count",
            minimum=0,
            maximum=self.artifact_count,
        )
        bounded_integer(
            self.remapped,
            "restore remapped count",
            minimum=0,
            maximum=self.artifact_count,
        )
        if len(self.remaps) != self.uploaded or self.remapped > self.uploaded:
            raise MaintenanceError("invalid_restore_result", "restore result counts are invalid")
        if self.dry_run and (self.uploaded or self.remapped or self.remaps):
            raise MaintenanceError("invalid_restore_result", "dry-run restore mutated state")


class MaintenanceStore(Protocol):
    """PostgreSQL-authoritative interface for a dedicated maintenance role."""

    def select_retention_candidates(
        self, policy: RetentionPolicy, now: datetime, limit: int
    ) -> tuple[RetentionCandidate, ...]: ...

    def queue_and_delete_builds(
        self,
        policy: RetentionPolicy,
        now: datetime,
        build_ids: tuple[UUID, ...],
    ) -> RetentionApplyResult: ...

    def preview_deletions(
        self, eligible_before: datetime, now: datetime, limit: int
    ) -> tuple[DeletionWorkItem, ...]: ...

    def claim_deletions(
        self,
        eligible_before: datetime,
        now: datetime,
        limit: int,
        claim_token: UUID,
        lease_expires_at: datetime,
    ) -> tuple[DeletionWorkItem, ...]: ...

    def record_deletion_attempt(
        self,
        item: DeletionWorkItem,
        worker_id: str,
        outcome: str,
        error_code: Optional[str],
        attempted_at: datetime,
    ) -> None: ...

    def iter_queued_build_ids(self, page_size: int) -> Iterable[tuple[UUID, ...]]: ...

    def artifact_inventory(self) -> tuple[ArtifactVersionEvidence, ...]: ...

    def apply_version_remaps(self, remaps: tuple[VersionRemap, ...]) -> int: ...


class QueuePublisher(Protocol):
    def enqueue(self, build_id: UUID) -> str: ...


class VersionedObjectClient(Protocol):
    def delete_version(self, bucket: str, object_key: str, version_id: str) -> None: ...

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


class DatabaseExporter(Protocol):
    def export_namespace(self, namespace: str, destination: BinaryIO) -> None: ...


class _HashingWriter:
    def __init__(self, destination: BinaryIO) -> None:
        if not callable(getattr(destination, "write", None)):
            raise MaintenanceError("invalid_backup_destination", "backup destination is invalid")
        self._destination = destination
        self._digest = hashlib.sha256()
        self.bytes_written = 0

    def write(self, payload: bytes) -> int:
        if not isinstance(payload, bytes):
            raise MaintenanceError("invalid_database_export", "database exporter returned invalid bytes")
        total = self.bytes_written + len(payload)
        if total > MAX_DATABASE_EXPORT_BYTES:
            raise MaintenanceError("database_export_too_large", "database export exceeds policy")
        written = self._destination.write(payload)
        if written is None:
            written = len(payload)
        if written != len(payload):
            raise MaintenanceError("database_export_write_failed", "database export write was incomplete")
        self._digest.update(payload)
        self.bytes_written = total
        return written

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()


def _hash_version(
    client: VersionedObjectClient, evidence: ArtifactVersionEvidence, *, version_id: Optional[str] = None
) -> tuple[str, int]:
    selected_version = evidence.version_id if version_id is None else _version_id(version_id)
    digest = hashlib.sha256()
    consumed = 0
    try:
        chunks = client.iter_version(evidence.bucket, evidence.object_key, selected_version)
        for chunk in chunks:
            if not isinstance(chunk, bytes) or not chunk:
                raise MaintenanceError("invalid_object_stream", "artifact reader returned invalid bytes")
            consumed += len(chunk)
            if consumed > evidence.bytes or consumed > MAX_PUBLISHED_BYTES:
                raise MaintenanceError("artifact_size_mismatch", "artifact version exceeds recorded bytes")
            digest.update(chunk)
    except MaintenanceError:
        raise
    except Exception as exc:
        raise MaintenanceError("storage_read_failed", "artifact version could not be read") from exc
    return digest.hexdigest(), consumed


def validate_inventory_objects(
    inventory: BackupInventory, client: VersionedObjectClient
) -> int:
    if not isinstance(inventory, BackupInventory):
        raise MaintenanceError("invalid_inventory", "backup inventory is invalid")
    verified = 0
    for evidence in inventory.artifacts:
        digest, consumed = _hash_version(client, evidence)
        if consumed != evidence.bytes or not hmac.compare_digest(digest, evidence.sha256):
            raise MaintenanceError("artifact_evidence_mismatch", "artifact version does not match inventory")
        verified += 1
    return verified


@dataclass(frozen=True)
class _LoadedObjectBackup:
    inventory: BackupInventory
    object_paths: tuple[Path, ...]
    artifact_bytes: int


def _bounded_total(current: int, addition: int) -> int:
    total = current + addition
    return bounded_integer(
        total,
        "backup artifact bytes",
        minimum=0,
        maximum=MAX_BACKUP_OBJECT_BYTES,
    )


def _read_backup_inventory(path: Path) -> BackupInventory:
    try:
        size = path.lstat().st_size
    except OSError as exc:
        raise MaintenanceError("backup_file_unavailable", "backup inventory is unavailable") from exc
    bounded_integer(
        size,
        "backup inventory bytes",
        minimum=1,
        maximum=MAX_INVENTORY_BYTES,
    )
    with _open_backup_file(path, size, "backup inventory") as stream:
        try:
            payload = stream.read(size + 1)
        except OSError as exc:
            raise MaintenanceError("backup_read_failed", "backup inventory could not be read") from exc
    if len(payload) != size:
        raise MaintenanceError("backup_file_changed", "backup inventory changed while being read")
    return BackupInventory.from_json_bytes(payload)


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


def _load_object_backup(value: Any) -> _LoadedObjectBackup:
    root = _absolute_backup_path(value, "backup input")
    _safe_directory(root, "backup input")
    try:
        root_entries = {entry.name for entry in os.scandir(root)}
    except OSError as exc:
        raise MaintenanceError("backup_path_unavailable", "backup input could not be listed") from exc
    if root_entries != {BACKUP_INVENTORY_NAME, BACKUP_OBJECTS_DIRECTORY}:
        raise MaintenanceError("ambiguous_backup", "backup input contains unexpected entries")

    objects_directory = root / BACKUP_OBJECTS_DIRECTORY
    _safe_directory(objects_directory, "backup objects directory")
    inventory = _read_backup_inventory(root / BACKUP_INVENTORY_NAME)
    expected_names = {_backup_object_name(index) for index in range(len(inventory.artifacts))}
    try:
        observed_names = {entry.name for entry in os.scandir(objects_directory)}
    except OSError as exc:
        raise MaintenanceError("backup_path_unavailable", "backup objects could not be listed") from exc
    if observed_names != expected_names:
        raise MaintenanceError("ambiguous_backup", "backup object set does not match inventory")

    paths = []
    total = 0
    for index, evidence in enumerate(inventory.artifacts):
        _artifact_relative_path(evidence)
        path = objects_directory / _backup_object_name(index)
        _verify_backup_object(path, evidence)
        paths.append(path)
        total = _bounded_total(total, evidence.bytes)
    return _LoadedObjectBackup(inventory, tuple(paths), total)


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


class MaintenanceService:
    def __init__(
        self,
        store: MaintenanceStore,
        *,
        namespace: str,
        bucket: Optional[str] = None,
        objects: Optional[VersionedObjectClient] = None,
        queue: Optional[QueuePublisher] = None,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if store is None:
            raise MaintenanceError("invalid_store", "maintenance store is required")
        if not callable(uuid_factory):
            raise MaintenanceError("invalid_uuid_factory", "UUID factory is invalid")
        self._store = store
        self.namespace = validate_namespace(namespace)
        self.bucket = None if bucket is None else _bucket(bucket)
        self._objects = objects
        self._queue = queue
        self._uuid_factory = uuid_factory

    @staticmethod
    def _apply_flag(apply: bool) -> bool:
        if not isinstance(apply, bool):
            raise MaintenanceError("invalid_apply_flag", "apply flag must be boolean")
        return apply

    def run_retention(
        self,
        *,
        policy: Optional[RetentionPolicy] = None,
        apply: bool = False,
        limit: int = 100,
        now: Optional[datetime] = None,
    ) -> RetentionRunResult:
        policy = RetentionPolicy() if policy is None else policy
        if not isinstance(policy, RetentionPolicy):
            raise MaintenanceError("invalid_retention_policy", "retention policy is invalid")
        self._apply_flag(apply)
        bounded_integer(limit, "retention limit", minimum=1, maximum=MAX_MAINTENANCE_BATCH)
        current = _utc(now or datetime.now(timezone.utc), "retention time")
        candidates = tuple(self._store.select_retention_candidates(policy, current, limit))
        if any(not isinstance(item, RetentionCandidate) for item in candidates):
            raise MaintenanceError("invalid_retention_result", "PostgreSQL returned invalid retention candidates")
        if len(candidates) > limit or len({item.build_id for item in candidates}) != len(candidates):
            raise MaintenanceError("invalid_retention_result", "PostgreSQL returned invalid retention candidates")
        if any(item.status in ACTIVE_STATUSES for item in candidates):
            raise MaintenanceError("active_build_selected", "retention selected an active build")
        cutoffs = policy.cutoffs(current)
        if any(item.finished_at > cutoffs[item.status] for item in candidates):
            raise MaintenanceError("invalid_retention_result", "PostgreSQL returned an ineligible build")
        if not apply:
            return RetentionRunResult(True, candidates, (), 0)
        applied = self._store.queue_and_delete_builds(
            policy,
            current,
            tuple(item.build_id for item in candidates),
        )
        if not isinstance(applied, RetentionApplyResult):
            raise MaintenanceError("invalid_retention_result", "PostgreSQL returned an invalid apply result")
        return RetentionRunResult(
            False,
            candidates,
            applied.deleted_build_ids,
            applied.queued_artifact_versions,
        )

    def run_artifact_deletion(
        self,
        *,
        policy: Optional[RetentionPolicy] = None,
        worker_id: str = "maintenance-v1",
        apply: bool = False,
        limit: int = 100,
        now: Optional[datetime] = None,
    ) -> DeletionRunResult:
        policy = RetentionPolicy() if policy is None else policy
        if not isinstance(policy, RetentionPolicy):
            raise MaintenanceError("invalid_retention_policy", "retention policy is invalid")
        if not isinstance(worker_id, str) or WORKER_ID_PATTERN.fullmatch(worker_id) is None:
            raise MaintenanceError("invalid_worker_id", "maintenance worker ID is outside policy")
        self._apply_flag(apply)
        bounded_integer(limit, "deletion limit", minimum=1, maximum=MAX_MAINTENANCE_BATCH)
        current = _utc(now or datetime.now(timezone.utc), "deletion time")
        eligible_before = current - timedelta(days=policy.orphan_grace_days)
        if not apply:
            preview = tuple(self._store.preview_deletions(eligible_before, current, limit))
            if (
                len(preview) > limit
                or any(not isinstance(item, DeletionWorkItem) for item in preview)
                or any(item.evidence.namespace != self.namespace for item in preview)
                or any(item.queued_at > eligible_before for item in preview)
            ):
                raise MaintenanceError("invalid_deletion_result", "PostgreSQL returned invalid deletion work")
            return DeletionRunResult(True, len(preview), 0, 0)
        if self._objects is None:
            raise MaintenanceError("storage_not_configured", "versioned object client is required")
        claim_token = self._uuid_factory()
        if not isinstance(claim_token, UUID):
            raise MaintenanceError("invalid_uuid_factory", "UUID factory returned an invalid token")
        claimed = tuple(
            self._store.claim_deletions(
                eligible_before,
                current,
                limit,
                claim_token,
                current + timedelta(seconds=DELETION_LEASE_SECONDS),
            )
        )
        if (
            len(claimed) > limit
            or any(not isinstance(item, DeletionWorkItem) for item in claimed)
            or any(item.evidence.namespace != self.namespace for item in claimed)
            or any(item.queued_at > eligible_before for item in claimed)
        ):
            raise MaintenanceError("invalid_deletion_result", "PostgreSQL returned invalid deletion work")
        deleted = 0
        failed = 0
        for item in claimed:
            if item.status != "deleting" or item.claim_token != claim_token:
                raise MaintenanceError("invalid_deletion_claim", "PostgreSQL returned an invalid claim")
            evidence = item.evidence
            try:
                self._objects.delete_version(
                    evidence.bucket,
                    evidence.object_key,
                    evidence.version_id,
                )
            except Exception:
                self._store.record_deletion_attempt(
                    item,
                    worker_id,
                    "failed",
                    "storage_delete_failed",
                    current,
                )
                failed += 1
            else:
                self._store.record_deletion_attempt(
                    item,
                    worker_id,
                    "deleted",
                    None,
                    current,
                )
                deleted += 1
        return DeletionRunResult(False, len(claimed), deleted, failed)

    def reconstruct_redis(
        self,
        *,
        apply: bool = False,
        limit: int = 1000,
    ) -> RedisReconstructionResult:
        self._apply_flag(apply)
        bounded_integer(limit, "Redis reconstruction limit", minimum=1, maximum=MAX_MAINTENANCE_BATCH)
        if apply and self._queue is None:
            raise MaintenanceError("redis_not_configured", "Redis queue client is required")
        derived = 0
        enqueued = 0
        previous: Optional[UUID] = None
        short_page_seen = False
        for page in self._store.iter_queued_build_ids(limit):
            if (
                not isinstance(page, tuple)
                or not page
                or len(page) > limit
                or short_page_seen
            ):
                raise MaintenanceError(
                    "invalid_queue_reconstruction",
                    "PostgreSQL returned invalid queued build pages",
                )
            if len(page) < limit:
                short_page_seen = True
            for build_id in page:
                if not isinstance(build_id, UUID):
                    raise MaintenanceError(
                        "invalid_build_id",
                        "PostgreSQL returned an invalid queued build ID",
                    )
                if previous is not None and build_id.int <= previous.int:
                    raise MaintenanceError(
                        "invalid_queue_reconstruction",
                        "PostgreSQL returned unordered queued builds",
                    )
                previous = build_id
                derived += 1
                if derived > MAX_QUEUE_RECONSTRUCTION_BUILDS:
                    raise MaintenanceError(
                        "queue_reconstruction_too_large",
                        "queued build set exceeds the bounded recovery policy",
                    )
                if apply:
                    assert self._queue is not None
                    self._queue.enqueue(build_id)
                    enqueued += 1
        return RedisReconstructionResult(not apply, derived, enqueued)

    def backup_inventory(self, *, now: Optional[datetime] = None) -> BackupInventory:
        current = _utc(now or datetime.now(timezone.utc), "backup time")
        artifacts = tuple(self._store.artifact_inventory())
        if self.bucket is not None and any(item.bucket != self.bucket for item in artifacts):
            raise MaintenanceError("bucket_mismatch", "backup artifact bucket does not match")
        return BackupInventory(self.namespace, current, artifacts)

    def export_object_backup(
        self,
        output: Any,
        *,
        now: Optional[datetime] = None,
    ) -> ObjectBackupEvidence:
        """Download every exact referenced object version into a new private directory."""

        if self._objects is None:
            raise MaintenanceError("storage_not_configured", "versioned object client is required")
        root = _absolute_backup_path(output, "backup output")
        _safe_directory(root.parent, "backup output parent")
        try:
            root.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise MaintenanceError("backup_path_unavailable", "backup output is unavailable") from exc
        else:
            raise MaintenanceError("backup_target_exists", "backup output must not already exist")

        inventory = self.backup_inventory(now=now)
        for evidence in inventory.artifacts:
            _artifact_relative_path(evidence)
        try:
            os.mkdir(root, BACKUP_DIRECTORY_MODE)
            os.mkdir(root / BACKUP_OBJECTS_DIRECTORY, BACKUP_DIRECTORY_MODE)
        except OSError as exc:
            raise MaintenanceError("backup_write_failed", "backup output could not be created safely") from exc
        _safe_directory(root, "backup output")
        objects_directory = root / BACKUP_OBJECTS_DIRECTORY
        _safe_directory(objects_directory, "backup objects directory")

        total = 0
        for index, evidence in enumerate(inventory.artifacts):
            _copy_version_to_backup(
                self._objects,
                evidence,
                objects_directory / _backup_object_name(index),
            )
            total = _bounded_total(total, evidence.bytes)
        inventory_payload = inventory.to_json_bytes()
        _write_private_file(root / BACKUP_INVENTORY_NAME, inventory_payload)
        return ObjectBackupEvidence(
            inventory_sha256=hashlib.sha256(inventory_payload).hexdigest(),
            artifact_count=len(inventory.artifacts),
            artifact_bytes=total,
        )

    def restore_object_backup(
        self,
        input_path: Any,
        *,
        apply: bool = False,
    ) -> ObjectRestoreResult:
        """Validate a private object backup, then upload and atomically remap on apply."""

        self._apply_flag(apply)
        if self._objects is None:
            raise MaintenanceError("storage_not_configured", "versioned object client is required")
        loaded = _load_object_backup(input_path)
        inventory = loaded.inventory
        if inventory.namespace != self.namespace:
            raise MaintenanceError("namespace_mismatch", "restore inventory namespace does not match")
        buckets = {item.bucket for item in inventory.artifacts}
        if self.bucket is not None:
            if buckets and buckets != {self.bucket}:
                raise MaintenanceError("bucket_mismatch", "restore artifact bucket does not match")
            buckets = {self.bucket}
        if not buckets:
            raise MaintenanceError("empty_restore_bucket", "empty backup lacks a configured bucket")
        for bucket in sorted(buckets):
            try:
                self._objects.assert_namespace_empty(bucket, self.namespace)
            except MaintenanceError:
                raise
            except Exception as exc:
                raise MaintenanceError(
                    "storage_inspection_failed",
                    "restore target namespace could not be inspected",
                ) from exc
        if not apply:
            return ObjectRestoreResult(
                dry_run=True,
                artifact_count=len(inventory.artifacts),
                artifact_bytes=loaded.artifact_bytes,
                uploaded=0,
                remapped=0,
                remaps=(),
            )

        remaps = []
        for evidence, path in zip(inventory.artifacts, loaded.object_paths):
            relative_path = _artifact_relative_path(evidence)
            with _open_backup_file(path, evidence.bytes, "backup object") as source:
                try:
                    restored_version_id = self._objects.upload_version(
                        evidence.bucket,
                        evidence.object_key,
                        source,
                        evidence.bytes,
                        evidence.sha256,
                        ARTIFACT_CONTENT_TYPES[relative_path],
                    )
                except MaintenanceError:
                    raise
                except Exception as exc:
                    raise MaintenanceError(
                        "storage_upload_failed",
                        "backup object could not be restored",
                    ) from exc
            remaps.append(
                VersionRemap(
                    namespace=evidence.namespace,
                    build_id=evidence.build_id,
                    bucket=evidence.bucket,
                    object_key=evidence.object_key,
                    source_version_id=evidence.version_id,
                    restored_version_id=_version_id(restored_version_id, "restored version ID"),
                    sha256=evidence.sha256,
                    bytes=evidence.bytes,
                )
            )
        validated = self.restore_version_ids(inventory, remaps, apply=True)
        return ObjectRestoreResult(
            dry_run=False,
            artifact_count=len(inventory.artifacts),
            artifact_bytes=loaded.artifact_bytes,
            uploaded=len(validated),
            remapped=len(validated),
            remaps=validated,
        )

    def validate_backup(self, inventory: BackupInventory) -> int:
        if inventory.namespace != self.namespace:
            raise MaintenanceError("namespace_mismatch", "backup inventory namespace does not match")
        if self._objects is None:
            raise MaintenanceError("storage_not_configured", "versioned object client is required")
        return validate_inventory_objects(inventory, self._objects)

    def export_backup(
        self,
        exporter: DatabaseExporter,
        destination: BinaryIO,
        *,
        now: Optional[datetime] = None,
    ) -> BackupExportEvidence:
        if exporter is None or not callable(getattr(exporter, "export_namespace", None)):
            raise MaintenanceError("invalid_database_exporter", "database exporter is invalid")
        inventory = self.backup_inventory(now=now)
        writer = _HashingWriter(destination)
        try:
            exporter.export_namespace(self.namespace, writer)
        except MaintenanceError:
            raise
        except Exception as exc:
            raise MaintenanceError("database_export_failed", "database export failed") from exc
        if writer.bytes_written < 1:
            raise MaintenanceError("empty_database_export", "database export is empty")
        inventory_payload = inventory.to_json_bytes()
        return BackupExportEvidence(
            inventory=inventory,
            inventory_sha256=hashlib.sha256(inventory_payload).hexdigest(),
            inventory_bytes=len(inventory_payload),
            database=DatabaseExportEvidence(writer.sha256, writer.bytes_written),
        )

    def prepare_restore_remaps(
        self,
        inventory: BackupInventory,
        restored: Sequence[VersionRemap],
    ) -> tuple[VersionRemap, ...]:
        if inventory.namespace != self.namespace:
            raise MaintenanceError("namespace_mismatch", "restore inventory namespace does not match")
        if self._objects is None:
            raise MaintenanceError("storage_not_configured", "versioned object client is required")
        remaps = tuple(restored)
        expected = {item.identity: item for item in inventory.artifacts}
        observed: dict[tuple[str, UUID, str, str, str], VersionRemap] = {}
        for remap in remaps:
            if not isinstance(remap, VersionRemap) or remap.namespace != self.namespace:
                raise MaintenanceError("invalid_restore_remap", "restore remap is invalid")
            if remap.source_identity in observed:
                raise MaintenanceError("duplicate_restore_remap", "restore remap is duplicated")
            observed[remap.source_identity] = remap
        if set(observed) != set(expected):
            raise MaintenanceError("restore_set_mismatch", "restore remaps do not match backup inventory")
        for identity, remap in observed.items():
            evidence = expected[identity]
            if remap.sha256 != evidence.sha256 or remap.bytes != evidence.bytes:
                raise MaintenanceError("restore_evidence_mismatch", "restore remap evidence changed")
            digest, consumed = _hash_version(
                self._objects,
                evidence,
                version_id=remap.restored_version_id,
            )
            if consumed != evidence.bytes or not hmac.compare_digest(digest, evidence.sha256):
                raise MaintenanceError("restore_evidence_mismatch", "restored object does not match inventory")
        return tuple(sorted(remaps, key=lambda item: (str(item.build_id), item.object_key)))

    def restore_version_ids(
        self,
        inventory: BackupInventory,
        restored: Sequence[VersionRemap],
        *,
        apply: bool = False,
    ) -> tuple[VersionRemap, ...]:
        self._apply_flag(apply)
        remaps = self.prepare_restore_remaps(inventory, restored)
        if apply:
            updated = self._store.apply_version_remaps(remaps)
            if updated != len(remaps):
                raise MaintenanceError("restore_update_mismatch", "PostgreSQL remap count is invalid")
        return remaps


class PostgresMaintenanceStore:
    """DB-API implementation intended for a separately scoped maintenance role."""

    def __init__(self, connect: Callable[[], Any], *, namespace: str) -> None:
        if not callable(connect):
            raise MaintenanceError("invalid_database_factory", "database connection factory is invalid")
        self._connect = connect
        self.namespace = validate_namespace(namespace)

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        connection = None
        cursor = None
        try:
            connection = self._connect()
            cursor = connection.cursor()
            yield cursor
            connection.commit()
        except Exception as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            if isinstance(exc, ServiceError):
                raise
            raise MaintenanceError("database_unavailable", "maintenance database operation failed") from exc
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    @staticmethod
    def _candidate(row: Sequence[Any]) -> RetentionCandidate:
        if len(row) != 5:
            raise MaintenanceError("invalid_database_state", "retention row is invalid")
        return RetentionCandidate(
            build_id=_uuid(row[0], "retention build ID"),
            status=BuildStatus(str(row[1])),
            finished_at=row[2],
            artifact_count=int(row[3]),
            artifact_bytes=int(row[4]),
        )

    @staticmethod
    def _deletion(row: Sequence[Any]) -> DeletionWorkItem:
        if len(row) != 12:
            raise MaintenanceError("invalid_database_state", "deletion row is invalid")
        claim = None if row[11] is None else _uuid(row[11], "deletion claim token")
        evidence = ArtifactVersionEvidence(
            namespace=str(row[1]),
            build_id=_uuid(row[2], "artifact build ID"),
            bucket=str(row[3]),
            object_key=str(row[4]),
            version_id=str(row[5]),
            sha256=str(row[6]),
            bytes=int(row[7]),
        )
        return DeletionWorkItem(
            queue_id=int(row[0]),
            evidence=evidence,
            status=str(row[8]),
            attempt_count=int(row[9]),
            queued_at=row[10],
            claim_token=claim,
        )

    @staticmethod
    def _cutoff_parameters(
        namespace: str,
        policy: RetentionPolicy,
        now: datetime,
    ) -> tuple[Any, ...]:
        cutoffs = policy.cutoffs(now)
        return (
            namespace,
            cutoffs[BuildStatus.SUCCEEDED],
            cutoffs[BuildStatus.FAILED],
            cutoffs[BuildStatus.CANCELED],
            cutoffs[BuildStatus.NEEDS_REVIEW],
        )

    @staticmethod
    def _retention_predicate() -> str:
        return """
            b.namespace = %s AND (
                (b.status = 'succeeded' AND b.finished_at <= %s) OR
                (b.status = 'failed' AND b.finished_at <= %s) OR
                (b.status = 'canceled' AND b.finished_at <= %s) OR
                (b.status = 'needs_review' AND b.finished_at <= %s)
            )
        """

    def select_retention_candidates(
        self, policy: RetentionPolicy, now: datetime, limit: int
    ) -> tuple[RetentionCandidate, ...]:
        bounded_integer(limit, "retention limit", minimum=1, maximum=MAX_MAINTENANCE_BATCH)
        with self._transaction() as cursor:
            cursor.execute(
                f"""
                SELECT b.id, b.status, b.finished_at,
                       COUNT(a.build_id), COALESCE(SUM(a.bytes), 0)
                FROM hbcb.builds AS b
                LEFT JOIN hbcb.artifacts AS a ON a.build_id = b.id
                WHERE {self._retention_predicate()}
                GROUP BY b.id, b.status, b.finished_at
                ORDER BY b.finished_at, b.id
                LIMIT %s
                """,
                self._cutoff_parameters(self.namespace, policy, now) + (limit,),
            )
            return tuple(self._candidate(row) for row in cursor.fetchall())

    def queue_and_delete_builds(
        self,
        policy: RetentionPolicy,
        now: datetime,
        build_ids: tuple[UUID, ...],
    ) -> RetentionApplyResult:
        ids = tuple(build_ids)
        if len(ids) > MAX_MAINTENANCE_BATCH or len(set(ids)) != len(ids):
            raise MaintenanceError("invalid_build_ids", "retention build IDs are outside policy")
        if any(not isinstance(build_id, UUID) for build_id in ids):
            raise MaintenanceError("invalid_build_id", "retention build ID is invalid")
        if not ids:
            return RetentionApplyResult((), 0)
        with self._transaction() as cursor:
            cursor.execute(
                f"""
                SELECT b.id, b.status, b.finished_at
                FROM hbcb.builds AS b
                WHERE b.id = ANY(%s::uuid[]) AND {self._retention_predicate()}
                ORDER BY b.id
                FOR UPDATE OF b
                """,
                (list(ids),) + self._cutoff_parameters(self.namespace, policy, now),
            )
            locked = tuple(_uuid(row[0], "retention build ID") for row in cursor.fetchall())
            if not locked:
                return RetentionApplyResult((), 0)
            cursor.execute(
                "SELECT COUNT(*) FROM hbcb.artifacts WHERE build_id = ANY(%s::uuid[])",
                (list(locked),),
            )
            artifact_count = int(cursor.fetchone()[0])
            cursor.execute(
                """
                INSERT INTO hbcb.artifact_deletion_queue (
                    namespace, build_id, bucket, object_key, version_id,
                    sha256, bytes, queued_at
                )
                SELECT b.namespace, a.build_id, a.bucket, a.object_key,
                       a.version_id, a.sha256, a.bytes, %s
                FROM hbcb.artifacts AS a
                JOIN hbcb.builds AS b ON b.id = a.build_id
                WHERE b.namespace = %s AND b.id = ANY(%s::uuid[])
                ON CONFLICT (namespace, bucket, object_key, version_id) DO NOTHING
                """,
                (now, self.namespace, list(locked)),
            )
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM hbcb.artifact_deletion_queue
                WHERE namespace = %s AND build_id = ANY(%s::uuid[])
                """,
                (self.namespace, list(locked)),
            )
            queued_count = int(cursor.fetchone()[0])
            if queued_count != artifact_count:
                raise MaintenanceError(
                    "deletion_queue_mismatch",
                    "exact artifact versions were not durably queued before deletion",
                )
            cursor.execute(
                """
                DELETE FROM hbcb.builds
                WHERE namespace = %s AND id = ANY(%s::uuid[])
                  AND status IN ('succeeded', 'failed', 'canceled', 'needs_review')
                RETURNING id
                """,
                (self.namespace, list(locked)),
            )
            deleted = tuple(_uuid(row[0], "deleted build ID") for row in cursor.fetchall())
            if set(deleted) != set(locked):
                raise MaintenanceError("retention_delete_mismatch", "retention deletion was incomplete")
            return RetentionApplyResult(tuple(sorted(deleted, key=str)), queued_count)

    def preview_deletions(
        self, eligible_before: datetime, now: datetime, limit: int
    ) -> tuple[DeletionWorkItem, ...]:
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT id, namespace, build_id, bucket, object_key, version_id,
                       sha256, bytes, status, attempt_count, queued_at, claim_token
                FROM hbcb.artifact_deletion_queue
                WHERE namespace = %s AND queued_at <= %s AND (
                    status IN ('pending', 'failed') OR
                    (status = 'deleting' AND lease_expires_at <= %s)
                ) AND attempt_count < 1000000
                ORDER BY queued_at, id
                LIMIT %s
                """,
                (self.namespace, eligible_before, now, limit),
            )
            return tuple(self._deletion(row) for row in cursor.fetchall())

    def claim_deletions(
        self,
        eligible_before: datetime,
        now: datetime,
        limit: int,
        claim_token: UUID,
        lease_expires_at: datetime,
    ) -> tuple[DeletionWorkItem, ...]:
        with self._transaction() as cursor:
            cursor.execute(
                """
                WITH candidates AS (
                    SELECT id
                    FROM hbcb.artifact_deletion_queue
                    WHERE namespace = %s AND queued_at <= %s AND (
                        status IN ('pending', 'failed') OR
                        (status = 'deleting' AND lease_expires_at <= %s)
                    ) AND attempt_count < 1000000
                    ORDER BY queued_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                UPDATE hbcb.artifact_deletion_queue AS queue
                SET status = 'deleting', claim_token = %s,
                    lease_expires_at = %s, last_error_code = NULL
                FROM candidates
                WHERE queue.id = candidates.id
                RETURNING queue.id, queue.namespace, queue.build_id, queue.bucket,
                          queue.object_key, queue.version_id, queue.sha256, queue.bytes,
                          queue.status, queue.attempt_count, queue.queued_at,
                          queue.claim_token
                """,
                (
                    self.namespace,
                    eligible_before,
                    now,
                    limit,
                    claim_token,
                    lease_expires_at,
                ),
            )
            return tuple(self._deletion(row) for row in cursor.fetchall())

    def record_deletion_attempt(
        self,
        item: DeletionWorkItem,
        worker_id: str,
        outcome: str,
        error_code: Optional[str],
        attempted_at: datetime,
    ) -> None:
        if item.status != "deleting" or not isinstance(item.claim_token, UUID):
            raise MaintenanceError("invalid_deletion_claim", "deletion attempt lacks a claim")
        if not isinstance(worker_id, str) or WORKER_ID_PATTERN.fullmatch(worker_id) is None:
            raise MaintenanceError("invalid_worker_id", "maintenance worker ID is outside policy")
        if outcome not in ("deleted", "failed"):
            raise MaintenanceError("invalid_deletion_outcome", "deletion outcome is outside policy")
        error = _safe_code(error_code, "deletion error code", required=outcome == "failed")
        if outcome == "deleted" and error is not None:
            raise MaintenanceError("invalid_deletion_outcome", "deleted attempt cannot have an error")
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT attempt_count
                FROM hbcb.artifact_deletion_queue
                WHERE namespace = %s AND id = %s AND status = 'deleting'
                  AND claim_token = %s
                FOR UPDATE
                """,
                (self.namespace, item.queue_id, item.claim_token),
            )
            row = cursor.fetchone()
            if row is None:
                raise MaintenanceError("deletion_claim_lost", "deletion claim is no longer current")
            attempt_number = bounded_integer(
                int(row[0]) + 1,
                "deletion attempt number",
                minimum=1,
                maximum=MAX_DELETION_ATTEMPTS,
            )
            cursor.execute(
                """
                INSERT INTO hbcb.artifact_deletion_attempts (
                    deletion_id, attempt_number, worker_id, claim_token,
                    outcome, error_code, attempted_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    item.queue_id,
                    attempt_number,
                    worker_id,
                    item.claim_token,
                    outcome,
                    error,
                    attempted_at,
                ),
            )
            cursor.execute(
                """
                UPDATE hbcb.artifact_deletion_queue
                SET status = %s, attempt_count = %s,
                    claim_token = NULL, lease_expires_at = NULL,
                    completed_at = CASE WHEN %s = 'deleted' THEN %s ELSE NULL END,
                    last_error_code = %s
                WHERE namespace = %s AND id = %s AND status = 'deleting'
                  AND claim_token = %s
                """,
                (
                    outcome,
                    attempt_number,
                    outcome,
                    attempted_at,
                    error,
                    self.namespace,
                    item.queue_id,
                    item.claim_token,
                ),
            )
            if cursor.rowcount != 1:
                raise MaintenanceError("deletion_claim_lost", "deletion claim update failed")

    def iter_queued_build_ids(self, page_size: int) -> Iterable[tuple[UUID, ...]]:
        bounded_integer(
            page_size,
            "Redis reconstruction page size",
            minimum=1,
            maximum=MAX_MAINTENANCE_BATCH,
        )
        with self._transaction() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            after: Optional[UUID] = None
            while True:
                if after is None:
                    cursor.execute(
                        """
                        SELECT id
                        FROM hbcb.builds
                        WHERE namespace = %s AND status = 'queued'
                        ORDER BY id
                        LIMIT %s
                        """,
                        (self.namespace, page_size),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id
                        FROM hbcb.builds
                        WHERE namespace = %s AND status = 'queued' AND id > %s
                        ORDER BY id
                        LIMIT %s
                        """,
                        (self.namespace, after, page_size),
                    )
                page = tuple(
                    _uuid(row[0], "queued build ID") for row in cursor.fetchall()
                )
                if not page:
                    return
                yield page
                if len(page) < page_size:
                    return
                after = page[-1]

    def artifact_inventory(self) -> tuple[ArtifactVersionEvidence, ...]:
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM hbcb.builds
                WHERE namespace = %s AND status IN (
                    'validating', 'queued', 'running', 'geometry_qa', 'rendering'
                )
                """,
                (self.namespace,),
            )
            active_count = int(cursor.fetchone()[0])
            if active_count != 0:
                raise MaintenanceError(
                    "backup_not_quiescent",
                    "backup requires no active builds",
                )
            cursor.execute(
                """
                SELECT b.namespace, a.build_id, a.bucket, a.object_key,
                       a.version_id, a.sha256, a.bytes
                FROM hbcb.artifacts AS a
                JOIN hbcb.builds AS b ON b.id = a.build_id
                WHERE b.namespace = %s
                ORDER BY a.build_id, a.object_key
                """,
                (self.namespace,),
            )
            return tuple(
                ArtifactVersionEvidence(
                    namespace=str(row[0]),
                    build_id=_uuid(row[1], "artifact build ID"),
                    bucket=str(row[2]),
                    object_key=str(row[3]),
                    version_id=str(row[4]),
                    sha256=str(row[5]),
                    bytes=int(row[6]),
                )
                for row in cursor.fetchall()
            )

    def apply_version_remaps(self, remaps: tuple[VersionRemap, ...]) -> int:
        if len(remaps) > MAX_MAINTENANCE_BATCH * 256:
            raise MaintenanceError("restore_set_too_large", "restore remap set is outside policy")
        with self._transaction() as cursor:
            updated = 0
            for remap in remaps:
                if remap.namespace != self.namespace:
                    raise MaintenanceError("namespace_mismatch", "restore remap namespace does not match")
                cursor.execute(
                    """
                    UPDATE hbcb.artifacts AS artifact
                    SET version_id = %s
                    FROM hbcb.builds AS build
                    WHERE artifact.build_id = build.id
                      AND build.namespace = %s
                      AND artifact.build_id = %s
                      AND artifact.bucket = %s
                      AND artifact.object_key = %s
                      AND artifact.version_id = %s
                      AND artifact.sha256 = %s
                      AND artifact.bytes = %s
                    """,
                    (
                        remap.restored_version_id,
                        self.namespace,
                        remap.build_id,
                        remap.bucket,
                        remap.object_key,
                        remap.source_version_id,
                        remap.sha256,
                        remap.bytes,
                    ),
                )
                if cursor.rowcount != 1:
                    raise MaintenanceError("restore_source_mismatch", "PostgreSQL restore source changed")
                cursor.execute(
                    """
                    INSERT INTO hbcb.artifact_restore_remaps (
                        namespace, build_id, bucket, object_key,
                        source_version_id, restored_version_id,
                        sha256, bytes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self.namespace,
                        remap.build_id,
                        remap.bucket,
                        remap.object_key,
                        remap.source_version_id,
                        remap.restored_version_id,
                        remap.sha256,
                        remap.bytes,
                    ),
                )
                updated += 1
            return updated


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


__all__ = [
    "ArtifactVersionEvidence",
    "BACKUP_INVENTORY_VERSION",
    "BackupExportEvidence",
    "BackupInventory",
    "DatabaseExportEvidence",
    "DeletionRunResult",
    "DeletionWorkItem",
    "MaintenanceError",
    "MaintenanceService",
    "MinioVersionedObjectClient",
    "ObjectBackupEvidence",
    "ObjectRestoreResult",
    "PostgresMaintenanceStore",
    "RedisReconstructionResult",
    "RetentionApplyResult",
    "RetentionCandidate",
    "RetentionPolicy",
    "RetentionRunResult",
    "VersionRemap",
    "bounded_integer",
    "validate_inventory_objects",
    "validate_namespace",
]
