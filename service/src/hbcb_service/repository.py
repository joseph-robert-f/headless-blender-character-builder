"""Transactional PostgreSQL repository for the asynchronous service.

PostgreSQL is authoritative for builds, attempts, events, artifacts, retries,
and the queue outbox. Redis messages contain only a build UUID and may be
delivered more than once; every worker mutation is fenced by a random lease
token whose SHA-256 digest is stored in the database.
"""

from __future__ import annotations

import hmac
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Callable, Iterator, Mapping, Optional, Sequence, Tuple, Union
from uuid import UUID, uuid4

from shared.character_spec import BuildRequest

from .config import BUCKET_PATTERN, NAMESPACE_PATTERN
from .errors import IdempotencyConflict, ServiceError, StateConflict
from .idempotency import (
    RequestFingerprint,
    digest_idempotency_key,
    require_same_request,
)
from .models import (
    MAX_PUBLISHED_BYTES,
    REQUIRED_PUBLISHED_ARTIFACTS,
    AttemptRecord,
    AttemptStatus,
    ArtifactRecord,
    BuildEvent,
    BuildRecord,
    BuildStatus,
    OutboxRecord,
    TERMINAL_BUILD_STATUSES,
    require_safe_code,
    require_transition,
)
from .state import (
    AttemptCompletion,
    AttemptHeartbeat,
    AttemptLease,
    BuildReservation,
    _lease_digest,
    _lease_duration,
    _retry_delay,
)
from .storage import artifact_object_key


ConnectionFactory = Callable[[], Any]
EnqueueCallback = Callable[[UUID], str]

_BUILD_COLUMNS = """
    id, request_sha256, spec_sha256, request_canonical, status,
    state_version, max_attempts, cancel_requested_at, terminal_code,
    manifest_object_key, manifest_sha256, manifest_bytes, created_at,
    updated_at, finished_at, published_at
"""
_QUALIFIED_BUILD_COLUMNS = """
    b.id, b.request_sha256, b.spec_sha256, b.request_canonical, b.status,
    b.state_version, b.max_attempts, b.cancel_requested_at, b.terminal_code,
    b.manifest_object_key, b.manifest_sha256, b.manifest_bytes, b.created_at,
    b.updated_at, b.finished_at, b.published_at
"""
_ATTEMPT_COLUMNS = """
    id, build_id, attempt_number, status, worker_id, lease_token_sha256,
    lease_expires_at, heartbeat_at, started_at, finished_at, exit_code,
    reason_code
"""
_QUALIFIED_ATTEMPT_COLUMNS = """
    a.id, a.build_id, a.attempt_number, a.status, a.worker_id,
    a.lease_token_sha256, a.lease_expires_at, a.heartbeat_at,
    a.started_at, a.finished_at, a.exit_code, a.reason_code
"""
_ARTIFACT_COLUMNS = """
    build_id, attempt_id, relative_path, bucket, object_key, sha256, bytes,
    content_type, created_at, etag, version_id
"""


def _uuid(value: Any, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise StateConflict("invalid_database_state", f"database returned an invalid {label}") from exc


def _build_from_row(row: Sequence[Any]) -> BuildRecord:
    if not isinstance(row, Sequence) or len(row) != 16:
        raise StateConflict("invalid_database_state", "database returned an invalid build")
    canonical = row[3]
    try:
        canonical_bytes = bytes(canonical)
        status = BuildStatus(str(row[4]))
    except (TypeError, ValueError) as exc:
        raise StateConflict("invalid_database_state", "database returned an invalid build") from exc
    return BuildRecord(
        build_id=_uuid(row[0], "build ID"),
        request_sha256=str(row[1]),
        spec_sha256=str(row[2]),
        canonical_request=canonical_bytes,
        status=status,
        state_version=int(row[5]),
        max_attempts=int(row[6]),
        cancel_requested_at=row[7],
        terminal_code=row[8],
        manifest_object_key=row[9],
        manifest_sha256=row[10],
        manifest_bytes=None if row[11] is None else int(row[11]),
        created_at=row[12],
        updated_at=row[13],
        finished_at=row[14],
        published_at=row[15],
    )


def _attempt_from_row(row: Sequence[Any]) -> AttemptRecord:
    if not isinstance(row, Sequence) or len(row) != 12:
        raise StateConflict("invalid_database_state", "database returned an invalid attempt")
    try:
        status = AttemptStatus(str(row[3]))
    except ValueError as exc:
        raise StateConflict("invalid_database_state", "database returned an invalid attempt") from exc
    return AttemptRecord(
        attempt_id=_uuid(row[0], "attempt ID"),
        build_id=_uuid(row[1], "build ID"),
        attempt_number=int(row[2]),
        status=status,
        worker_id=str(row[4]),
        lease_token_sha256=str(row[5]),
        lease_expires_at=row[6],
        heartbeat_at=row[7],
        started_at=row[8],
        finished_at=row[9],
        exit_code=None if row[10] is None else int(row[10]),
        reason_code=row[11],
    )


def _artifact_from_row(row: Sequence[Any]) -> ArtifactRecord:
    if not isinstance(row, Sequence) or len(row) != 11:
        raise StateConflict("invalid_database_state", "database returned an invalid artifact")
    return ArtifactRecord(
        build_id=_uuid(row[0], "build ID"),
        attempt_id=_uuid(row[1], "attempt ID"),
        relative_path=str(row[2]),
        bucket=str(row[3]),
        object_key=str(row[4]),
        sha256=str(row[5]),
        bytes=int(row[6]),
        content_type=str(row[7]),
        created_at=row[8],
        etag=row[9],
        version_id=row[10],
    )


class PostgresRepository:
    """Synchronous, transaction-per-operation durable service repository."""

    def __init__(
        self,
        connect: ConnectionFactory,
        *,
        deployment_namespace: str,
        idempotency_secret: Optional[bytes],
        storage_bucket: str,
        max_attempts: int = 2,
        build_id_factory: Callable[[], UUID] = uuid4,
        attempt_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if not callable(connect):
            raise StateConflict("invalid_database_factory", "database connection factory is invalid")
        if NAMESPACE_PATTERN.fullmatch(deployment_namespace) is None:
            raise StateConflict("invalid_namespace", "deployment namespace is outside policy")
        if idempotency_secret is not None and (
            not isinstance(idempotency_secret, bytes)
            or not 32 <= len(idempotency_secret) <= 128
        ):
            raise StateConflict("invalid_idempotency_secret", "idempotency secret is outside policy")
        if BUCKET_PATTERN.fullmatch(storage_bucket) is None or ".." in storage_bucket:
            raise StateConflict("invalid_bucket", "storage bucket is outside policy")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 5:
            raise StateConflict("invalid_max_attempts", "maximum attempts is outside policy")
        self._connect = connect
        self._namespace = deployment_namespace
        self._idempotency_secret = idempotency_secret
        self._storage_bucket = storage_bucket
        self._max_attempts = max_attempts
        self._build_id_factory = build_id_factory
        self._attempt_id_factory = attempt_id_factory

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
            raise StateConflict("database_unavailable", "database operation failed") from exc
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

    def _select_build(
        self, cursor: Any, build_id: UUID, *, for_update: bool = False
    ) -> BuildRecord:
        suffix = " FOR UPDATE" if for_update else ""
        cursor.execute(
            f"SELECT {_BUILD_COLUMNS} FROM hbcb.builds WHERE namespace = %s AND id = %s{suffix}",
            (self._namespace, build_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise StateConflict("build_not_found", "build does not exist")
        return _build_from_row(row)

    def _select_attempt(
        self, cursor: Any, attempt_id: UUID, *, for_update: bool = False
    ) -> AttemptRecord:
        suffix = " FOR UPDATE OF a" if for_update else ""
        cursor.execute(
            f"""
            SELECT {_QUALIFIED_ATTEMPT_COLUMNS}
            FROM hbcb.build_attempts AS a
            JOIN hbcb.builds AS b ON b.id = a.build_id
            WHERE b.namespace = %s AND a.id = %s{suffix}
            """,
            (self._namespace, attempt_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise StateConflict("attempt_not_found", "attempt does not exist")
        return _attempt_from_row(row)

    @staticmethod
    def _database_now(cursor: Any) -> datetime:
        cursor.execute("SELECT CURRENT_TIMESTAMP")
        row = cursor.fetchone()
        if row is None or len(row) != 1 or not isinstance(row[0], datetime):
            raise StateConflict("invalid_database_state", "database returned an invalid timestamp")
        return row[0]

    @staticmethod
    def _next_sequence(cursor: Any, build_id: UUID) -> int:
        cursor.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM hbcb.build_events WHERE build_id = %s",
            (build_id,),
        )
        row = cursor.fetchone()
        if row is None or len(row) != 1:
            raise StateConflict("invalid_database_state", "database returned an invalid event sequence")
        return int(row[0])

    @classmethod
    def _insert_event(
        cls,
        cursor: Any,
        *,
        build_id: UUID,
        attempt_id: Optional[UUID],
        event_type: str,
        from_status: Optional[BuildStatus],
        to_status: BuildStatus,
        reason_code: Optional[str],
    ) -> None:
        sequence = cls._next_sequence(cursor, build_id)
        cursor.execute(
            """
            INSERT INTO hbcb.build_events (
                build_id, attempt_id, sequence, event_type, from_status,
                to_status, reason_code, details, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, '{}'::jsonb, CURRENT_TIMESTAMP)
            """,
            (
                build_id,
                attempt_id,
                sequence,
                event_type,
                None if from_status is None else from_status.value,
                to_status.value,
                reason_code,
            ),
        )

    def submit(
        self, request: Union[BuildRequest, bytes, str], idempotency_key: Optional[str]
    ) -> BuildReservation:
        if self._idempotency_secret is None:
            raise StateConflict("operation_not_permitted", "repository role cannot submit builds")
        fingerprint = RequestFingerprint.from_request(request)
        key_digest = (
            digest_idempotency_key(idempotency_key, self._idempotency_secret)
            if idempotency_key is not None
            else None
        )
        with self._transaction() as cursor:
            if key_digest is not None:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (self._namespace + ":" + key_digest,),
                )
                cursor.execute(
                    f"""
                    SELECT {_QUALIFIED_BUILD_COLUMNS}
                    FROM hbcb.idempotency_keys AS i
                    JOIN hbcb.builds AS b ON b.namespace = i.namespace AND b.id = i.build_id
                    WHERE i.namespace = %s AND i.key_sha256 = %s
                    """,
                    (self._namespace, key_digest),
                )
                row = cursor.fetchone()
                if row is not None:
                    build = _build_from_row(row)
                    require_same_request(build.request_sha256, fingerprint.request_sha256)
                    if build.canonical_request != fingerprint.canonical_request:
                        raise IdempotencyConflict(
                            "idempotency_conflict",
                            "Idempotency-Key was already used for a different request",
                        )
                    return BuildReservation(build, False)

            build_id = self._build_id_factory()
            if not isinstance(build_id, UUID):
                raise StateConflict("build_id_collision", "build identifier could not be allocated")
            cursor.execute(
                f"""
                INSERT INTO hbcb.builds (
                    id, namespace, request_canonical, request_sha256, spec_sha256,
                    status, state_version, max_attempts, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, 'queued', 1, %s,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                ) RETURNING {_BUILD_COLUMNS}
                """,
                (
                    build_id,
                    self._namespace,
                    fingerprint.canonical_request,
                    fingerprint.request_sha256,
                    fingerprint.spec_sha256,
                    self._max_attempts,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise StateConflict("invalid_database_state", "database did not return the created build")
            build = _build_from_row(row)
            self._insert_event(
                cursor,
                build_id=build_id,
                attempt_id=None,
                event_type="validated",
                from_status=None,
                to_status=BuildStatus.VALIDATING,
                reason_code=None,
            )
            self._insert_event(
                cursor,
                build_id=build_id,
                attempt_id=None,
                event_type="queued",
                from_status=BuildStatus.VALIDATING,
                to_status=BuildStatus.QUEUED,
                reason_code=None,
            )
            if key_digest is not None:
                cursor.execute(
                    """
                    INSERT INTO hbcb.idempotency_keys (
                        namespace, key_sha256, request_sha256, build_id, created_at
                    ) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    """,
                    (
                        self._namespace,
                        key_digest,
                        fingerprint.request_sha256,
                        build_id,
                    ),
                )
            cursor.execute(
                """
                INSERT INTO hbcb.queue_outbox (
                    build_id, build_version, available_at, created_at
                ) VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (build_id, build.state_version),
            )
            return BuildReservation(build, True)

    def get_build(self, build_id: UUID) -> BuildRecord:
        if not isinstance(build_id, UUID):
            raise StateConflict("build_not_found", "build does not exist")
        with self._transaction() as cursor:
            return self._select_build(cursor, build_id)

    def ping(self) -> bool:
        with self._transaction() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            if row is None or int(row[0]) != 1:
                raise StateConflict("database_unavailable", "database readiness check failed")
        return True

    def events_for(self, build_id: UUID) -> Tuple[BuildEvent, ...]:
        with self._transaction() as cursor:
            self._select_build(cursor, build_id)
            cursor.execute(
                """
                SELECT build_id, sequence, event_type, from_status, to_status,
                       reason_code, created_at, attempt_id
                FROM hbcb.build_events
                WHERE build_id = %s ORDER BY sequence
                """,
                (build_id,),
            )
            events = []
            for row in cursor.fetchall():
                events.append(
                    BuildEvent(
                        build_id=_uuid(row[0], "build ID"),
                        sequence=int(row[1]),
                        event_type=str(row[2]),
                        from_status=None if row[3] is None else BuildStatus(str(row[3])),
                        to_status=BuildStatus(str(row[4])),
                        reason_code=row[5],
                        created_at=row[6],
                        attempt_id=None if row[7] is None else _uuid(row[7], "attempt ID"),
                    )
                )
            return tuple(events)

    def artifacts_for(self, build_id: UUID) -> Mapping[str, ArtifactRecord]:
        with self._transaction() as cursor:
            self._select_build(cursor, build_id)
            cursor.execute(
                f"SELECT {_ARTIFACT_COLUMNS} FROM hbcb.artifacts WHERE build_id = %s ORDER BY relative_path",
                (build_id,),
            )
            records = tuple(_artifact_from_row(row) for row in cursor.fetchall())
            return {record.relative_path: record for record in records}

    def attempts_for(self, build_id: UUID) -> Tuple[AttemptRecord, ...]:
        with self._transaction() as cursor:
            self._select_build(cursor, build_id)
            cursor.execute(
                f"SELECT {_ATTEMPT_COLUMNS} FROM hbcb.build_attempts WHERE build_id = %s ORDER BY attempt_number",
                (build_id,),
            )
            return tuple(_attempt_from_row(row) for row in cursor.fetchall())

    def request_cancel(self, build_id: UUID, expected_version: int) -> BuildRecord:
        with self._transaction() as cursor:
            build = self._select_build(cursor, build_id, for_update=True)
            if isinstance(expected_version, bool) or expected_version != build.state_version:
                raise StateConflict("stale_state_version", "build state was updated concurrently")
            if build.status in TERMINAL_BUILD_STATUSES:
                raise StateConflict("terminal_build", "terminal build cannot be canceled")
            if build.cancel_requested_at is not None:
                return build
            immediate = build.status in (BuildStatus.VALIDATING, BuildStatus.QUEUED)
            target = BuildStatus.CANCELED if immediate else build.status
            cursor.execute(
                f"""
                UPDATE hbcb.builds
                SET status = %s,
                    state_version = state_version + 1,
                    cancel_requested_at = CURRENT_TIMESTAMP,
                    terminal_code = %s,
                    updated_at = CURRENT_TIMESTAMP,
                    finished_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END
                WHERE namespace = %s AND id = %s
                RETURNING {_BUILD_COLUMNS}
                """,
                (
                    target.value,
                    "canceled_by_operator" if immediate else None,
                    immediate,
                    self._namespace,
                    build_id,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise StateConflict("invalid_database_state", "database did not return canceled build")
            updated = _build_from_row(row)
            self._insert_event(
                cursor,
                build_id=build_id,
                attempt_id=None,
                event_type="canceled" if immediate else "cancel_requested",
                from_status=build.status,
                to_status=target,
                reason_code="canceled_by_operator",
            )
            return updated

    def lease_build(
        self,
        build_id: UUID,
        worker_id: str,
        lease_token: str,
        *,
        lease_seconds: int,
    ) -> Optional[AttemptLease]:
        token_sha256 = _lease_digest(lease_token)
        duration = _lease_duration(lease_seconds)
        if not isinstance(build_id, UUID):
            raise StateConflict("build_not_found", "build does not exist")
        with self._transaction() as cursor:
            build = self._select_build(cursor, build_id, for_update=True)
            if build.status is not BuildStatus.QUEUED:
                return None
            cursor.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) FROM hbcb.build_attempts WHERE build_id = %s",
                (build_id,),
            )
            row = cursor.fetchone()
            attempt_number = 1 if row is None else int(row[0]) + 1
            if attempt_number > build.max_attempts:
                raise StateConflict("retry_policy_exhausted", "build has no attempts remaining")
            attempt_id = self._attempt_id_factory()
            if not isinstance(attempt_id, UUID):
                raise StateConflict("attempt_id_collision", "attempt identifier could not be allocated")
            cursor.execute(
                f"""
                INSERT INTO hbcb.build_attempts (
                    id, build_id, attempt_number, status, worker_id,
                    lease_token_sha256, lease_expires_at, heartbeat_at,
                    started_at, created_at
                ) VALUES (
                    %s, %s, %s, 'running', %s, %s,
                    CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                ) RETURNING {_ATTEMPT_COLUMNS}
                """,
                (
                    attempt_id,
                    build_id,
                    attempt_number,
                    worker_id,
                    token_sha256,
                    int(duration.total_seconds()),
                ),
            )
            attempt_row = cursor.fetchone()
            if attempt_row is None:
                raise StateConflict("invalid_database_state", "database did not return the leased attempt")
            attempt = _attempt_from_row(attempt_row)
            cursor.execute(
                f"""
                UPDATE hbcb.builds
                SET status = 'running', state_version = state_version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE namespace = %s AND id = %s
                RETURNING {_BUILD_COLUMNS}
                """,
                (self._namespace, build_id),
            )
            build_row = cursor.fetchone()
            if build_row is None:
                raise StateConflict("invalid_database_state", "database did not return the running build")
            updated = _build_from_row(build_row)
            self._insert_event(
                cursor,
                build_id=build_id,
                attempt_id=attempt_id,
                event_type="attempt_started",
                from_status=BuildStatus.QUEUED,
                to_status=BuildStatus.RUNNING,
                reason_code=None,
            )
            return AttemptLease(updated, attempt)

    def heartbeat_attempt(
        self,
        attempt_id: UUID,
        lease_token: str,
        *,
        lease_seconds: int,
    ) -> AttemptHeartbeat:
        token_sha256 = _lease_digest(lease_token)
        duration = _lease_duration(lease_seconds)
        with self._transaction() as cursor:
            attempt = self._select_attempt(cursor, attempt_id, for_update=True)
            if attempt.status not in (AttemptStatus.LEASED, AttemptStatus.RUNNING):
                raise StateConflict("lease_not_active", "attempt lease is no longer active")
            if not hmac.compare_digest(attempt.lease_token_sha256, token_sha256):
                raise StateConflict("lease_fence_mismatch", "attempt lease fence does not match")
            now = self._database_now(cursor)
            if attempt.lease_expires_at <= now:
                raise StateConflict("lease_expired", "attempt lease has expired")
            cursor.execute(
                f"""
                UPDATE hbcb.build_attempts
                SET heartbeat_at = CURRENT_TIMESTAMP,
                    lease_expires_at = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second')
                WHERE id = %s
                RETURNING {_ATTEMPT_COLUMNS}
                """,
                (int(duration.total_seconds()), attempt_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise StateConflict("invalid_database_state", "database did not return renewed attempt")
            updated = _attempt_from_row(row)
            build = self._select_build(cursor, attempt.build_id)
            return AttemptHeartbeat(
                build_id=build.build_id,
                attempt_id=attempt_id,
                lease_expires_at=updated.lease_expires_at,
                cancel_requested=build.cancel_requested_at is not None,
            )

    def complete_attempt(
        self,
        attempt_id: UUID,
        lease_token: str,
        *,
        status: AttemptStatus,
        exit_code: Optional[int],
        reason_code: str,
        retryable: bool,
        retry_delay_seconds: int = 0,
    ) -> AttemptCompletion:
        token_sha256 = _lease_digest(lease_token)
        delay = _retry_delay(retry_delay_seconds)
        if status not in (
            AttemptStatus.FAILED,
            AttemptStatus.NEEDS_REVIEW,
            AttemptStatus.CANCELED,
            AttemptStatus.TIMED_OUT,
        ):
            raise StateConflict("invalid_attempt_outcome", "attempt outcome is outside policy")
        if not isinstance(retryable, bool):
            raise StateConflict("invalid_retry_policy", "retry policy is outside policy")
        require_safe_code(reason_code, "reason_code", required=True)
        with self._transaction() as cursor:
            attempt = self._select_attempt(cursor, attempt_id, for_update=True)
            if attempt.status not in (AttemptStatus.LEASED, AttemptStatus.RUNNING):
                raise StateConflict("lease_not_active", "attempt lease is no longer active")
            if not hmac.compare_digest(attempt.lease_token_sha256, token_sha256):
                raise StateConflict("lease_fence_mismatch", "attempt lease fence does not match")
            now = self._database_now(cursor)
            if attempt.lease_expires_at <= now:
                raise StateConflict("lease_expired", "attempt lease has expired")
            build = self._select_build(cursor, attempt.build_id, for_update=True)
            if build.status is not BuildStatus.RUNNING:
                raise StateConflict("invalid_attempt", "attempt build is not running")
            cancel_wins = build.cancel_requested_at is not None
            if status is AttemptStatus.CANCELED and not cancel_wins:
                raise StateConflict("cancel_requires_request", "cancellation was not requested")
            final_attempt_status = AttemptStatus.CANCELED if cancel_wins else status
            final_reason = "canceled_by_operator" if cancel_wins else reason_code
            can_retry = (
                not cancel_wins
                and status in (AttemptStatus.FAILED, AttemptStatus.TIMED_OUT)
                and retryable
                and attempt.attempt_number < build.max_attempts
            )
            if can_retry:
                target = BuildStatus.QUEUED
            elif final_attempt_status is AttemptStatus.CANCELED:
                target = BuildStatus.CANCELED
            elif final_attempt_status is AttemptStatus.NEEDS_REVIEW:
                target = BuildStatus.NEEDS_REVIEW
            else:
                target = BuildStatus.FAILED
            terminal = target in TERMINAL_BUILD_STATUSES
            cursor.execute(
                f"""
                UPDATE hbcb.build_attempts
                SET status = %s, finished_at = CURRENT_TIMESTAMP,
                    exit_code = %s, reason_code = %s
                WHERE id = %s
                RETURNING {_ATTEMPT_COLUMNS}
                """,
                (final_attempt_status.value, exit_code, final_reason, attempt_id),
            )
            attempt_row = cursor.fetchone()
            if attempt_row is None:
                raise StateConflict("invalid_database_state", "database did not return completed attempt")
            updated_attempt = _attempt_from_row(attempt_row)
            cursor.execute(
                f"""
                UPDATE hbcb.builds
                SET status = %s,
                    state_version = state_version + 1,
                    terminal_code = %s,
                    updated_at = CURRENT_TIMESTAMP,
                    finished_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END
                WHERE namespace = %s AND id = %s
                RETURNING {_BUILD_COLUMNS}
                """,
                (
                    target.value,
                    final_reason if terminal else None,
                    terminal,
                    self._namespace,
                    build.build_id,
                ),
            )
            build_row = cursor.fetchone()
            if build_row is None:
                raise StateConflict("invalid_database_state", "database did not return completed build")
            updated_build = _build_from_row(build_row)
            self._insert_event(
                cursor,
                build_id=build.build_id,
                attempt_id=attempt_id,
                event_type="retry_queued" if can_retry else target.value,
                from_status=BuildStatus.RUNNING,
                to_status=target,
                reason_code=final_reason,
            )
            if can_retry:
                cursor.execute(
                    """
                    INSERT INTO hbcb.queue_outbox (
                        build_id, build_version, available_at, created_at
                    ) VALUES (
                        %s, %s,
                        CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
                        CURRENT_TIMESTAMP
                    )
                    """,
                    (
                        build.build_id,
                        updated_build.state_version,
                        int(delay.total_seconds()),
                    ),
                )
            return AttemptCompletion(
                build=updated_build,
                attempt=updated_attempt,
                requeued=can_retry,
                exhausted=(
                    not can_retry
                    and retryable
                    and not cancel_wins
                    and status in (AttemptStatus.FAILED, AttemptStatus.TIMED_OUT)
                ),
            )

    def _validate_publication(
        self,
        build_id: UUID,
        attempt_id: UUID,
        artifacts: Sequence[ArtifactRecord],
    ) -> Tuple[ArtifactRecord, ...]:
        records = tuple(artifacts)
        by_name = {record.relative_path: record for record in records}
        if len(records) != len(by_name) or set(by_name) != set(REQUIRED_PUBLISHED_ARTIFACTS):
            raise StateConflict("artifact_set_mismatch", "success requires the exact nine artifacts")
        if any(record.build_id != build_id for record in records):
            raise StateConflict("artifact_owner_mismatch", "artifact owner does not match build")
        if any(record.attempt_id != attempt_id for record in records):
            raise StateConflict("artifact_attempt_mismatch", "artifacts do not belong to the active attempt")
        if any(record.bucket != self._storage_bucket for record in records):
            raise StateConflict("artifact_bucket_mismatch", "artifact bucket is not canonical")
        if any(not record.version_id for record in records):
            raise StateConflict("artifact_version_missing", "durable artifact version evidence is required")
        for record in records:
            expected_key = artifact_object_key(
                self._namespace,
                build_id,
                attempt_id,
                record.relative_path,
            )
            if record.object_key != expected_key:
                raise StateConflict("artifact_key_mismatch", "artifact object key is not canonical")
        if sum(record.bytes for record in records) > MAX_PUBLISHED_BYTES:
            raise StateConflict("artifact_budget", "published artifacts exceed the aggregate budget")
        return records

    def publish_attempt_success(
        self,
        attempt_id: UUID,
        lease_token: str,
        artifacts: Sequence[ArtifactRecord],
    ) -> BuildRecord:
        token_sha256 = _lease_digest(lease_token)
        with self._transaction() as cursor:
            attempt = self._select_attempt(cursor, attempt_id, for_update=True)
            records = self._validate_publication(attempt.build_id, attempt_id, artifacts)
            if attempt.status is not AttemptStatus.RUNNING:
                raise StateConflict("lease_not_active", "attempt lease is no longer active")
            if not hmac.compare_digest(attempt.lease_token_sha256, token_sha256):
                raise StateConflict("lease_fence_mismatch", "attempt lease fence does not match")
            now = self._database_now(cursor)
            if attempt.lease_expires_at <= now:
                raise StateConflict("lease_expired", "attempt lease has expired")
            build = self._select_build(cursor, attempt.build_id, for_update=True)
            if build.status is not BuildStatus.RUNNING:
                raise StateConflict("invalid_transition", "success cannot be published from current state")
            if build.cancel_requested_at is not None:
                raise StateConflict("cancel_requested", "success cannot race an accepted cancellation")
            cursor.execute(
                "SELECT COUNT(*) FROM hbcb.artifacts WHERE build_id = %s",
                (build.build_id,),
            )
            existing_row = cursor.fetchone()
            if existing_row is None or int(existing_row[0]) != 0:
                raise StateConflict("artifacts_already_published", "build artifacts are immutable")
            for record in records:
                cursor.execute(
                    """
                    INSERT INTO hbcb.artifacts (
                        build_id, attempt_id, relative_path, bucket, object_key,
                        sha256, bytes, content_type, etag, version_id, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.build_id,
                        record.attempt_id,
                        record.relative_path,
                        record.bucket,
                        record.object_key,
                        record.sha256,
                        record.bytes,
                        record.content_type,
                        record.etag,
                        record.version_id,
                        record.created_at,
                    ),
                )
            manifest = next(
                record for record in records if record.relative_path == "manifest.json"
            )
            cursor.execute(
                f"""
                UPDATE hbcb.build_attempts
                SET status = 'succeeded', finished_at = CURRENT_TIMESTAMP,
                    exit_code = 0, reason_code = NULL
                WHERE id = %s
                RETURNING {_ATTEMPT_COLUMNS}
                """,
                (attempt_id,),
            )
            if cursor.fetchone() is None:
                raise StateConflict("invalid_database_state", "database did not return successful attempt")
            cursor.execute(
                f"""
                UPDATE hbcb.builds
                SET status = 'succeeded', state_version = state_version + 1,
                    terminal_code = NULL,
                    manifest_object_key = %s,
                    manifest_sha256 = %s,
                    manifest_bytes = %s,
                    updated_at = CURRENT_TIMESTAMP,
                    finished_at = CURRENT_TIMESTAMP,
                    published_at = CURRENT_TIMESTAMP
                WHERE namespace = %s AND id = %s
                RETURNING {_BUILD_COLUMNS}
                """,
                (
                    manifest.object_key,
                    manifest.sha256,
                    manifest.bytes,
                    self._namespace,
                    build.build_id,
                ),
            )
            build_row = cursor.fetchone()
            if build_row is None:
                raise StateConflict("invalid_database_state", "database did not return successful build")
            updated = _build_from_row(build_row)
            self._insert_event(
                cursor,
                build_id=build.build_id,
                attempt_id=attempt_id,
                event_type="succeeded",
                from_status=BuildStatus.RUNNING,
                to_status=BuildStatus.SUCCEEDED,
                reason_code=None,
            )
            return updated

    def recover_expired_attempts(
        self, *, retry_delay_seconds: int = 0, limit: int = 100
    ) -> Tuple[AttemptCompletion, ...]:
        delay = _retry_delay(retry_delay_seconds)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise StateConflict("invalid_recovery_limit", "recovery limit is outside policy")
        with self._transaction() as cursor:
            cursor.execute(
                f"""
                SELECT {_QUALIFIED_ATTEMPT_COLUMNS}
                FROM hbcb.build_attempts AS a
                JOIN hbcb.builds AS b ON b.id = a.build_id
                WHERE b.namespace = %s
                  AND a.status IN ('leased', 'running')
                  AND a.lease_expires_at <= CURRENT_TIMESTAMP
                ORDER BY a.lease_expires_at, a.id
                FOR UPDATE OF a SKIP LOCKED
                LIMIT %s
                """,
                (self._namespace, limit),
            )
            candidates = tuple(_attempt_from_row(row) for row in cursor.fetchall())
            results = []
            for attempt in candidates:
                build = self._select_build(cursor, attempt.build_id, for_update=True)
                if build.status is not BuildStatus.RUNNING:
                    cursor.execute(
                        f"""
                        UPDATE hbcb.build_attempts
                        SET status = 'lost', finished_at = CURRENT_TIMESTAMP,
                            reason_code = 'worker_lost'
                        WHERE id = %s
                        RETURNING {_ATTEMPT_COLUMNS}
                        """,
                        (attempt.attempt_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise StateConflict("invalid_database_state", "database did not return recovered attempt")
                    results.append(
                        AttemptCompletion(
                            build=build,
                            attempt=_attempt_from_row(row),
                            requeued=False,
                            exhausted=False,
                        )
                    )
                    continue
                cancel_wins = build.cancel_requested_at is not None
                can_retry = not cancel_wins and attempt.attempt_number < build.max_attempts
                if cancel_wins:
                    attempt_status = AttemptStatus.CANCELED
                    target = BuildStatus.CANCELED
                    reason = "canceled_by_operator"
                elif can_retry:
                    attempt_status = AttemptStatus.LOST
                    target = BuildStatus.QUEUED
                    reason = "worker_lost"
                else:
                    attempt_status = AttemptStatus.LOST
                    target = BuildStatus.FAILED
                    reason = "worker_lost"
                cursor.execute(
                    f"""
                    UPDATE hbcb.build_attempts
                    SET status = %s, finished_at = CURRENT_TIMESTAMP,
                        reason_code = %s
                    WHERE id = %s
                    RETURNING {_ATTEMPT_COLUMNS}
                    """,
                    (attempt_status.value, reason, attempt.attempt_id),
                )
                attempt_row = cursor.fetchone()
                if attempt_row is None:
                    raise StateConflict("invalid_database_state", "database did not return recovered attempt")
                terminal = target in TERMINAL_BUILD_STATUSES
                cursor.execute(
                    f"""
                    UPDATE hbcb.builds
                    SET status = %s, state_version = state_version + 1,
                        terminal_code = %s,
                        updated_at = CURRENT_TIMESTAMP,
                        finished_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END
                    WHERE namespace = %s AND id = %s
                    RETURNING {_BUILD_COLUMNS}
                    """,
                    (
                        target.value,
                        reason if terminal else None,
                        terminal,
                        self._namespace,
                        build.build_id,
                    ),
                )
                build_row = cursor.fetchone()
                if build_row is None:
                    raise StateConflict("invalid_database_state", "database did not return recovered build")
                updated_build = _build_from_row(build_row)
                self._insert_event(
                    cursor,
                    build_id=build.build_id,
                    attempt_id=attempt.attempt_id,
                    event_type="retry_queued" if can_retry else target.value,
                    from_status=BuildStatus.RUNNING,
                    to_status=target,
                    reason_code=reason,
                )
                if can_retry:
                    cursor.execute(
                        """
                        INSERT INTO hbcb.queue_outbox (
                            build_id, build_version, available_at, created_at
                        ) VALUES (
                            %s, %s,
                            CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
                            CURRENT_TIMESTAMP
                        )
                        """,
                        (
                            build.build_id,
                            updated_build.state_version,
                            int(delay.total_seconds()),
                        ),
                    )
                results.append(
                    AttemptCompletion(
                        build=updated_build,
                        attempt=_attempt_from_row(attempt_row),
                        requeued=can_retry,
                        exhausted=not can_retry and not cancel_wins,
                    )
                )
            return tuple(results)

    def pending_outbox(self, *, limit: int = 100) -> Tuple[OutboxRecord, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise StateConflict("invalid_outbox_limit", "outbox limit is outside policy")
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT o.id, o.build_id, o.build_version, o.available_at,
                       o.dispatched_at, o.dispatch_count, o.last_error_code
                FROM hbcb.queue_outbox AS o
                JOIN hbcb.builds AS b ON b.id = o.build_id
                WHERE b.namespace = %s AND o.dispatched_at IS NULL
                ORDER BY o.available_at, o.id
                LIMIT %s
                """,
                (self._namespace, limit),
            )
            return tuple(
                OutboxRecord(
                    outbox_id=int(row[0]),
                    build_id=_uuid(row[1], "build ID"),
                    build_version=int(row[2]),
                    available_at=row[3],
                    dispatched_at=row[4],
                    dispatch_count=int(row[5]),
                    last_error_code=row[6],
                )
                for row in cursor.fetchall()
            )

    def dispatch_outbox(
        self,
        enqueue: EnqueueCallback,
        *,
        limit: int = 100,
        retry_delay_seconds: int = 1,
    ) -> Tuple[int, int]:
        if not callable(enqueue):
            raise StateConflict("invalid_queue_callback", "queue callback is invalid")
        delay = _retry_delay(retry_delay_seconds)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise StateConflict("invalid_outbox_limit", "outbox limit is outside policy")
        dispatched = 0
        failed = 0
        processed_ids: list[int] = []
        for _index in range(limit):
            with self._transaction() as cursor:
                cursor.execute(
                    """
                    SELECT o.id, o.build_id, b.status
                    FROM hbcb.queue_outbox AS o
                    JOIN hbcb.builds AS b ON b.id = o.build_id
                    WHERE b.namespace = %s
                      AND o.dispatched_at IS NULL
                      AND o.available_at <= CURRENT_TIMESTAMP
                      AND o.id <> ALL(%s::bigint[])
                    ORDER BY o.available_at, o.id
                    FOR UPDATE OF o SKIP LOCKED
                    LIMIT 1
                    """,
                    (self._namespace, processed_ids),
                )
                row = cursor.fetchone()
                if row is None:
                    break
                outbox_id = int(row[0])
                processed_ids.append(outbox_id)
                build_id = _uuid(row[1], "build ID")
                build_status = BuildStatus(str(row[2]))
                if build_status is not BuildStatus.QUEUED:
                    cursor.execute(
                        """
                        UPDATE hbcb.queue_outbox
                        SET dispatched_at = CURRENT_TIMESTAMP,
                            dispatch_count = CASE
                                WHEN dispatch_count < 9223372036854775807
                                THEN dispatch_count + 1 ELSE dispatch_count END,
                            last_error_code = NULL
                        WHERE id = %s
                        """,
                        (outbox_id,),
                    )
                    dispatched += 1
                    continue
                try:
                    enqueue(build_id)
                except Exception:
                    cursor.execute(
                        """
                        UPDATE hbcb.queue_outbox
                        SET available_at = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
                            dispatch_count = CASE
                                WHEN dispatch_count < 9223372036854775807
                                THEN dispatch_count + 1 ELSE dispatch_count END,
                            last_error_code = 'redis_unavailable'
                        WHERE id = %s
                        """,
                        (int(delay.total_seconds()), outbox_id),
                    )
                    failed += 1
                    continue
                cursor.execute(
                    """
                    UPDATE hbcb.queue_outbox
                    SET dispatched_at = CURRENT_TIMESTAMP,
                        dispatch_count = CASE
                            WHEN dispatch_count < 9223372036854775807
                            THEN dispatch_count + 1 ELSE dispatch_count END,
                        last_error_code = NULL
                    WHERE id = %s
                    """,
                    (outbox_id,),
                )
                dispatched += 1
        return dispatched, failed


__all__ = ["PostgresRepository"]
