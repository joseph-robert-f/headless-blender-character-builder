"""Bounded retention, recovery, backup, and restore maintenance primitives.

PostgreSQL is authoritative.  Redis is reconstructed only from rows whose
current PostgreSQL status is ``queued``.  Artifact deletion work is durable and
contains the exact S3 bucket, object key, version ID, digest, and byte count
captured before a build row is deleted.

The module deliberately accepts injected DB, S3, Redis, and database-export
clients.  A deployment should give the process a separately scoped maintenance
database role; the API and worker roles intentionally lack deletion authority.

Adapter implementations live in maintenance_postgres and maintenance_storage;
their public names remain available here for existing callers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterable, Mapping, Optional, Protocol, Sequence
from uuid import UUID, uuid4

from .errors import ServiceError
# Compatibility facade: existing callers keep importing these names here.
from .maintenance_common import (
    ACTIVE_STATUSES,
    BACKUP_DIRECTORY_MODE,
    BACKUP_FILE_MODE,
    BACKUP_INVENTORY_NAME,
    BACKUP_INVENTORY_VERSION,
    BACKUP_OBJECTS_DIRECTORY,
    DEFAULT_FAILURE_RETENTION_DAYS,
    DEFAULT_ORPHAN_GRACE_DAYS,
    DEFAULT_SUCCEEDED_RETENTION_DAYS,
    DELETION_LEASE_SECONDS,
    MAX_BACKUP_OBJECT_BYTES,
    MAX_BACKUP_PATH_BYTES,
    MAX_DATABASE_EXPORT_BYTES,
    MAX_DELETION_ATTEMPTS,
    MAX_INVENTORY_BYTES,
    MAX_MAINTENANCE_BATCH,
    MAX_ORPHAN_SCAN_VERSIONS,
    MAX_QUEUE_RECONSTRUCTION_BUILDS,
    MAX_RETENTION_DAYS,
    RETENTION_STATUSES,
    ArtifactVersionEvidence,
    DeletionWorkItem,
    MaintenanceError,
    RetentionApplyResult,
    RetentionCandidate,
    RetentionPolicy,
    StoredObjectVersion,
    VersionRemap,
    VersionedObjectClient,
    _artifact_owner_from_key,
    _bucket,
    _object_key,
    _safe_code,
    _sha256,
    _utc,
    _uuid,
    _version_id,
    bounded_integer,
    validate_namespace,
)
from .maintenance_postgres import PostgresMaintenanceStore
from .maintenance_storage import (
    MinioVersionedObjectClient,
    _UploadHashingReader,
    _absolute_backup_path,
    _copy_version_to_backup,
    _open_backup_file,
    _safe_directory,
    _verify_backup_object,
    _write_private_file,
)
from .models import (
    ARTIFACT_CONTENT_TYPES,
    MAX_PUBLISHED_BYTES,
    WORKER_ID_PATTERN,
    BuildStatus,
)


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


@dataclass(frozen=True)
class OrphanDiscoveryResult:
    dry_run: bool
    scanned: int
    candidates: int
    queued: int

    def __post_init__(self) -> None:
        if not isinstance(self.dry_run, bool):
            raise MaintenanceError("invalid_orphan_result", "orphan dry-run state is invalid")
        for label, value in (
            ("scanned object versions", self.scanned),
            ("orphan candidates", self.candidates),
            ("queued orphan versions", self.queued),
        ):
            bounded_integer(value, label, minimum=0, maximum=MAX_ORPHAN_SCAN_VERSIONS)
        if self.candidates > self.scanned or self.queued > self.candidates:
            raise MaintenanceError("invalid_orphan_result", "orphan counts are invalid")
        if self.dry_run and self.queued != 0:
            raise MaintenanceError("invalid_orphan_result", "orphan preview mutated state")


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

    def reconcile_orphan_versions(
        self,
        versions: tuple[StoredObjectVersion, ...],
        eligible_before: datetime,
        now: datetime,
        apply: bool,
        limit: int,
    ) -> tuple[StoredObjectVersion, ...]: ...

    def iter_queued_build_ids(self, page_size: int) -> Iterable[tuple[UUID, ...]]: ...

    def artifact_inventory(self) -> tuple[ArtifactVersionEvidence, ...]: ...

    def apply_version_remaps(self, remaps: tuple[VersionRemap, ...]) -> int: ...


class QueuePublisher(Protocol):
    def enqueue(self, build_id: UUID) -> str: ...


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

    def discover_orphan_versions(
        self,
        *,
        policy: Optional[RetentionPolicy] = None,
        apply: bool = False,
        limit: int = 100,
        scan_limit: int = MAX_ORPHAN_SCAN_VERSIONS,
        now: Optional[datetime] = None,
    ) -> OrphanDiscoveryResult:
        """Inventory and durably queue old object versions absent from PostgreSQL.

        Object storage is only the source of candidates.  PostgreSQL performs
        the authoritative comparison while locking every candidate build row,
        and apply merely inserts exact evidence into the existing deletion
        queue.  A later ``delete-artifacts --apply`` run rechecks references at
        claim time before deleting the exact version.
        """

        policy = RetentionPolicy() if policy is None else policy
        if not isinstance(policy, RetentionPolicy):
            raise MaintenanceError("invalid_retention_policy", "retention policy is invalid")
        self._apply_flag(apply)
        bounded_integer(limit, "orphan limit", minimum=1, maximum=MAX_MAINTENANCE_BATCH)
        bounded_integer(
            scan_limit,
            "orphan scan limit",
            minimum=1,
            maximum=MAX_ORPHAN_SCAN_VERSIONS,
        )
        if self.bucket is None or self._objects is None:
            raise MaintenanceError("storage_not_configured", "versioned object client is required")
        current = _utc(now or datetime.now(timezone.utc), "orphan discovery time")
        eligible_before = current - timedelta(days=policy.orphan_grace_days)
        versions = tuple(
            self._objects.inventory_namespace_versions(
                self.bucket,
                self.namespace,
                limit=scan_limit,
            )
        )
        if (
            len(versions) > scan_limit
            or any(not isinstance(item, StoredObjectVersion) for item in versions)
            or any(item.namespace != self.namespace or item.bucket != self.bucket for item in versions)
            or len({item.identity for item in versions}) != len(versions)
        ):
            raise MaintenanceError("invalid_object_inventory", "object inventory is invalid")
        candidates = tuple(
            self._store.reconcile_orphan_versions(
                versions,
                eligible_before,
                current,
                apply,
                limit,
            )
        )
        inventoried_identities = {version.identity for version in versions}
        if (
            len(candidates) > limit
            or any(not isinstance(item, StoredObjectVersion) for item in candidates)
            or any(item.identity not in inventoried_identities for item in candidates)
            or any(item.last_modified > eligible_before for item in candidates)
            or len({item.identity for item in candidates}) != len(candidates)
        ):
            raise MaintenanceError("invalid_orphan_result", "PostgreSQL returned invalid orphan candidates")
        return OrphanDiscoveryResult(
            dry_run=not apply,
            scanned=len(versions),
            candidates=len(candidates),
            queued=len(candidates) if apply else 0,
        )

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
    "OrphanDiscoveryResult",
    "PostgresMaintenanceStore",
    "RedisReconstructionResult",
    "RetentionApplyResult",
    "RetentionCandidate",
    "RetentionPolicy",
    "RetentionRunResult",
    "StoredObjectVersion",
    "VersionRemap",
    "bounded_integer",
    "validate_inventory_objects",
    "validate_namespace",
]
