"""PostgreSQL maintenance adapter using an injected DB-API connection factory."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Iterable, Iterator, Optional, Sequence
from uuid import UUID

from .errors import ServiceError
from .maintenance_common import (
    ACTIVE_STATUSES,
    MAX_DELETION_ATTEMPTS,
    MAX_MAINTENANCE_BATCH,
    MAX_ORPHAN_SCAN_VERSIONS,
    ArtifactVersionEvidence,
    DeletionWorkItem,
    MaintenanceError,
    RetentionApplyResult,
    RetentionCandidate,
    RetentionPolicy,
    StoredObjectVersion,
    VersionRemap,
    _safe_code,
    _utc,
    _uuid,
    bounded_integer,
    validate_namespace,
)
from .models import BuildStatus, WORKER_ID_PATTERN


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
                FROM hbcb.artifacts AS artifact
                JOIN hbcb.builds AS build ON build.id = artifact.build_id
                JOIN hbcb.artifact_deletion_queue AS queue
                  ON queue.namespace = build.namespace
                 AND queue.bucket = artifact.bucket
                 AND queue.object_key = artifact.object_key
                 AND queue.version_id = artifact.version_id
                WHERE build.namespace = %s
                  AND artifact.build_id = ANY(%s::uuid[])
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
                SELECT queue.id, queue.namespace, queue.build_id, queue.bucket,
                       queue.object_key, queue.version_id, queue.sha256,
                       queue.bytes, queue.status, queue.attempt_count,
                       queue.queued_at, queue.claim_token
                FROM hbcb.artifact_deletion_queue AS queue
                LEFT JOIN hbcb.builds AS build
                  ON build.namespace = queue.namespace
                 AND build.id = queue.build_id
                WHERE queue.namespace = %s AND queue.queued_at <= %s AND (
                    queue.status IN ('pending', 'failed') OR
                    (queue.status = 'deleting' AND queue.lease_expires_at <= %s)
                ) AND queue.attempt_count < 1000000
                  AND (
                      build.id IS NULL OR build.status NOT IN (
                          'validating','queued','running','geometry_qa','rendering'
                      )
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM hbcb.artifacts AS artifact
                      WHERE artifact.bucket = queue.bucket
                        AND artifact.object_key = queue.object_key
                        AND artifact.version_id = queue.version_id
                  )
                ORDER BY queue.queued_at, queue.id
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
                    SELECT queue.id
                    FROM hbcb.artifact_deletion_queue AS queue
                    LEFT JOIN hbcb.builds AS build
                      ON build.namespace = queue.namespace
                     AND build.id = queue.build_id
                    WHERE queue.namespace = %s AND queue.queued_at <= %s AND (
                        queue.status IN ('pending', 'failed') OR
                        (queue.status = 'deleting' AND queue.lease_expires_at <= %s)
                    ) AND queue.attempt_count < 1000000
                      AND (
                          build.id IS NULL OR build.status NOT IN (
                              'validating','queued','running','geometry_qa','rendering'
                          )
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM hbcb.artifacts AS artifact
                          WHERE artifact.bucket = queue.bucket
                            AND artifact.object_key = queue.object_key
                            AND artifact.version_id = queue.version_id
                      )
                    ORDER BY queue.queued_at, queue.id
                    FOR UPDATE OF queue SKIP LOCKED
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

    def reconcile_orphan_versions(
        self,
        versions: tuple[StoredObjectVersion, ...],
        eligible_before: datetime,
        now: datetime,
        apply: bool,
        limit: int,
    ) -> tuple[StoredObjectVersion, ...]:
        """Select absent exact versions under authoritative PostgreSQL locks."""

        self._validate_orphan_reconciliation(versions, eligible_before, now, apply, limit)
        if not versions:
            return ()
        eligible = tuple(version for version in versions if version.last_modified <= eligible_before)
        if not eligible:
            return ()
        build_ids = tuple(sorted({item.build_id for item in eligible}, key=str))
        buckets = tuple(sorted({item.bucket for item in eligible}))
        object_keys = tuple(sorted({item.object_key for item in eligible}))
        with self._transaction() as cursor:
            # Serialize with publication, cancellation, and retention for every
            # build which still exists.  Missing build rows are valid orphan
            # candidates; existing active rows remain protected below.
            cursor.execute(
                """
                SELECT id, status
                FROM hbcb.builds
                WHERE namespace = %s AND id = ANY(%s::uuid[])
                ORDER BY id
                FOR UPDATE
                """,
                (self.namespace, list(build_ids)),
            )
            statuses = {
                _uuid(row[0], "orphan build ID"): BuildStatus(str(row[1]))
                for row in cursor.fetchall()
            }
            cursor.execute(
                """
                SELECT bucket, object_key, version_id
                FROM hbcb.artifacts
                WHERE bucket = ANY(%s::text[])
                  AND object_key = ANY(%s::text[])
                """,
                (list(buckets), list(object_keys)),
            )
            referenced = {
                (str(row[0]), str(row[1]), str(row[2])) for row in cursor.fetchall()
            }
            cursor.execute(
                """
                SELECT bucket, object_key, version_id
                FROM hbcb.artifact_deletion_queue
                WHERE namespace = %s
                  AND bucket = ANY(%s::text[])
                  AND object_key = ANY(%s::text[])
                  AND status <> 'deleted'
                """,
                (self.namespace, list(buckets), list(object_keys)),
            )
            already_queued = {
                (str(row[0]), str(row[1]), str(row[2])) for row in cursor.fetchall()
            }
            selected = tuple(
                item
                for item in eligible
                if item.identity not in referenced
                and item.identity not in already_queued
                and statuses.get(item.build_id) not in ACTIVE_STATUSES
            )[:limit]
            if apply:
                for item in selected:
                    cursor.execute(
                        """
                        INSERT INTO hbcb.artifact_deletion_queue (
                            namespace, build_id, bucket, object_key, version_id,
                            sha256, bytes, queued_at, evidence_origin,
                            object_last_modified
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'orphan_inventory', %s)
                        ON CONFLICT (namespace, bucket, object_key, version_id) DO NOTHING
                        """,
                        (
                            item.namespace,
                            item.build_id,
                            item.bucket,
                            item.object_key,
                            item.version_id,
                            item.sha256,
                            item.bytes,
                            now,
                            item.last_modified,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise MaintenanceError(
                            "orphan_queue_conflict",
                            "orphan evidence changed during reconciliation",
                        )
            return selected

    def _validate_orphan_reconciliation(
        self,
        versions: tuple[StoredObjectVersion, ...],
        eligible_before: datetime,
        now: datetime,
        apply: bool,
        limit: int,
    ) -> None:
        if not isinstance(versions, tuple) or len(versions) > MAX_ORPHAN_SCAN_VERSIONS:
            raise MaintenanceError("invalid_object_inventory", "object inventory is invalid")
        if any(not isinstance(item, StoredObjectVersion) for item in versions):
            raise MaintenanceError("invalid_object_inventory", "object inventory is invalid")
        if any(item.namespace != self.namespace for item in versions):
            raise MaintenanceError("namespace_mismatch", "object inventory namespace does not match")
        if len({item.identity for item in versions}) != len(versions):
            raise MaintenanceError("duplicate_object_version", "object inventory contains duplicates")
        before = _utc(eligible_before, "orphan eligibility cutoff")
        current = _utc(now, "orphan discovery time")
        if before >= current:
            raise MaintenanceError("invalid_orphan_cutoff", "orphan eligibility cutoff is invalid")
        if not isinstance(apply, bool):
            raise MaintenanceError("invalid_apply_flag", "apply flag must be boolean")
        bounded_integer(limit, "orphan limit", minimum=1, maximum=MAX_MAINTENANCE_BATCH)

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
