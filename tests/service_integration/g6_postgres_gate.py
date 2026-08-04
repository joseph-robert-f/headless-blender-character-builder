#!/usr/bin/env python3
"""Disposable PostgreSQL gate for the production G6 repository."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import psycopg

from hbcb_service.errors import IdempotencyConflict, StateConflict
from hbcb_service.migrations import apply_postgres_migrations
from hbcb_service.models import ARTIFACT_CONTENT_TYPES, ArtifactRecord, AttemptStatus, BuildStatus
from hbcb_service.repository import PostgresRepository
from hbcb_service.storage import artifact_object_key


ROOT = Path(__file__).resolve().parents[2]
FIXED_IDS = (
    UUID("11111111-1111-4111-8111-111111111111"),
    UUID("22222222-2222-4222-8222-222222222222"),
    UUID("33333333-3333-4333-8333-333333333333"),
    UUID("44444444-4444-4444-8444-444444444444"),
    UUID("55555555-5555-4555-8555-555555555555"),
)
ATTEMPT_IDS = (
    UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"),
    UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2"),
    UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3"),
    UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa4"),
    UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa5"),
    UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa6"),
)
TOKEN_ONE = "a" * 43
TOKEN_TWO = "b" * 43


def _request(name: str) -> bytes:
    return (ROOT / "examples" / "requests" / name).read_bytes()


def _records(build_id: UUID, attempt_id: UUID) -> tuple[ArtifactRecord, ...]:
    records = []
    for index, (relative_path, content_type) in enumerate(
        ARTIFACT_CONTENT_TYPES.items(), start=1
    ):
        payload = (relative_path + "\n").encode("utf-8")
        records.append(
            ArtifactRecord(
                build_id=build_id,
                attempt_id=attempt_id,
                relative_path=relative_path,
                bucket="hbcb-artifacts",
                object_key=artifact_object_key(
                    "local", build_id, attempt_id, relative_path
                ),
                sha256=hashlib.sha256(payload).hexdigest(),
                bytes=len(payload),
                content_type=content_type,
                created_at=datetime.now(timezone.utc),
                etag=f"etag-{index}",
                version_id=f"version-{index}",
            )
        )
    return tuple(records)


def main() -> None:
    dsn = os.environ.get("HBCB_G6_POSTGRES_DSN")
    if not dsn:
        raise SystemExit("HBCB_G6_POSTGRES_DSN is required")
    connect = lambda: psycopg.connect(dsn, connect_timeout=5)
    with connect() as connection:
        migration = apply_postgres_migrations(connection)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('server_version')")
            postgres_version = str(cursor.fetchone()[0])

    build_ids = iter(FIXED_IDS)
    attempt_ids = iter(ATTEMPT_IDS)
    repository = PostgresRepository(
        connect,
        deployment_namespace="local",
        idempotency_secret=b"s" * 32,
        storage_bucket="hbcb-artifacts",
        max_attempts=2,
        build_id_factory=lambda: next(build_ids),
        attempt_id_factory=lambda: next(attempt_ids),
    )
    facet = _request("facet-bot.json")
    moss = _request("moss-hopper.json")

    created = repository.submit(facet, "facet-request-0001")
    assert created.created and created.build.status is BuildStatus.QUEUED
    replay = repository.submit(facet, "facet-request-0001")
    assert not replay.created and replay.build.build_id == created.build.build_id
    try:
        repository.submit(moss, "facet-request-0001")
    except IdempotencyConflict:
        pass
    else:
        raise AssertionError("conflicting idempotency key was accepted")
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*), MIN(length(key_sha256)) FROM hbcb.idempotency_keys")
        count, digest_length = cursor.fetchone()
        assert count == 1 and digest_length == 64
        cursor.execute(
            "SELECT COUNT(*) FROM hbcb.idempotency_keys WHERE key_sha256 = %s",
            ("facet-request-0001",),
        )
        assert cursor.fetchone()[0] == 0

    enqueued: list[UUID] = []
    dispatched, failed = repository.dispatch_outbox(
        lambda build_id: enqueued.append(build_id) or "1-0",
        retry_delay_seconds=1,
    )
    assert (dispatched, failed) == (1, 0)
    assert enqueued == [created.build.build_id]

    first = repository.lease_build(
        created.build.build_id,
        "worker-1",
        TOKEN_ONE,
        lease_seconds=30,
    )
    assert first is not None and first.attempt.attempt_number == 1
    try:
        repository.heartbeat_attempt(
            first.attempt.attempt_id,
            TOKEN_TWO,
            lease_seconds=30,
        )
    except StateConflict as exc:
        assert exc.code == "lease_fence_mismatch"
    else:
        raise AssertionError("wrong lease fence was accepted")
    heartbeat = repository.heartbeat_attempt(
        first.attempt.attempt_id,
        TOKEN_ONE,
        lease_seconds=30,
    )
    assert not heartbeat.cancel_requested
    retry = repository.complete_attempt(
        first.attempt.attempt_id,
        TOKEN_ONE,
        status=AttemptStatus.FAILED,
        exit_code=10,
        reason_code="blender_failed",
        retryable=True,
        retry_delay_seconds=0,
    )
    assert retry.requeued and retry.build.status is BuildStatus.QUEUED
    dispatched, failed = repository.dispatch_outbox(
        lambda build_id: enqueued.append(build_id) or "2-0",
        retry_delay_seconds=1,
    )
    assert (dispatched, failed) == (1, 0)

    second = repository.lease_build(
        created.build.build_id,
        "worker-1",
        TOKEN_TWO,
        lease_seconds=30,
    )
    assert second is not None and second.attempt.attempt_number == 2
    records = _records(created.build.build_id, second.attempt.attempt_id)
    try:
        repository.publish_attempt_success(
            second.attempt.attempt_id,
            TOKEN_TWO,
            records[:-1],
        )
    except StateConflict as exc:
        assert exc.code == "artifact_set_mismatch"
    else:
        raise AssertionError("partial artifact publication was accepted")
    assert repository.get_build(created.build.build_id).status is BuildStatus.RUNNING
    succeeded = repository.publish_attempt_success(
        second.attempt.attempt_id,
        TOKEN_TWO,
        records,
    )
    assert succeeded.status is BuildStatus.SUCCEEDED
    assert len(repository.artifacts_for(succeeded.build_id)) == 9

    cancel_build = repository.submit(moss, None).build
    repository.dispatch_outbox(lambda _build_id: "3-0")
    cancel_lease = repository.lease_build(
        cancel_build.build_id,
        "worker-1",
        TOKEN_ONE,
        lease_seconds=30,
    )
    assert cancel_lease is not None
    requested = repository.request_cancel(
        cancel_build.build_id,
        cancel_lease.build.state_version,
    )
    assert requested.cancel_requested_at is not None
    try:
        repository.publish_attempt_success(
            cancel_lease.attempt.attempt_id,
            TOKEN_ONE,
            _records(cancel_build.build_id, cancel_lease.attempt.attempt_id),
        )
    except StateConflict as exc:
        assert exc.code == "cancel_requested"
    else:
        raise AssertionError("success raced through accepted cancellation")
    canceled = repository.complete_attempt(
        cancel_lease.attempt.attempt_id,
        TOKEN_ONE,
        status=AttemptStatus.FAILED,
        exit_code=10,
        reason_code="blender_failed",
        retryable=True,
    )
    assert canceled.build.status is BuildStatus.CANCELED

    lost_build = repository.submit(facet, None).build
    repository.dispatch_outbox(lambda _build_id: "4-0")
    lost_lease = repository.lease_build(
        lost_build.build_id,
        "worker-1",
        TOKEN_ONE,
        lease_seconds=30,
    )
    assert lost_lease is not None
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE hbcb.build_attempts
            SET lease_expires_at = CURRENT_TIMESTAMP - INTERVAL '1 second'
            WHERE id = %s
            """,
            (lost_lease.attempt.attempt_id,),
        )
    recovered = repository.recover_expired_attempts(retry_delay_seconds=0)
    assert len(recovered) == 1
    assert recovered[0].attempt.status is AttemptStatus.LOST
    assert recovered[0].build.status is BuildStatus.QUEUED
    assert repository.dispatch_outbox(lambda _build_id: "4-1") == (1, 0)

    timeout_repository = PostgresRepository(
        connect,
        deployment_namespace="local",
        idempotency_secret=b"s" * 32,
        storage_bucket="hbcb-artifacts",
        max_attempts=1,
        build_id_factory=lambda: next(build_ids),
        attempt_id_factory=lambda: next(attempt_ids),
    )
    timeout_build = timeout_repository.submit(facet, None).build
    timeout_repository.dispatch_outbox(lambda _build_id: "5-0")
    timeout_lease = timeout_repository.lease_build(
        timeout_build.build_id,
        "worker-1",
        TOKEN_ONE,
        lease_seconds=30,
    )
    assert timeout_lease is not None
    timed_out = timeout_repository.complete_attempt(
        timeout_lease.attempt.attempt_id,
        TOKEN_ONE,
        status=AttemptStatus.TIMED_OUT,
        exit_code=124,
        reason_code="builder_timeout",
        retryable=True,
    )
    assert timed_out.exhausted and timed_out.build.status is BuildStatus.FAILED

    outbox_build = repository.submit(moss, None).build
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE hbcb.queue_outbox
            SET dispatch_count = 100,
                available_at = CURRENT_TIMESTAMP
            WHERE build_id = %s AND dispatched_at IS NULL
            """,
            (outbox_build.build_id,),
        )
    dispatched, failed = repository.dispatch_outbox(
        lambda _build_id: (_ for _ in ()).throw(RuntimeError("redis unavailable")),
        retry_delay_seconds=0,
    )
    assert (dispatched, failed) == (0, 1)
    pending_after_failure = next(
        item
        for item in repository.pending_outbox()
        if item.build_id == outbox_build.build_id
    )
    assert pending_after_failure.dispatch_count == 101
    dispatched, failed = repository.dispatch_outbox(
        lambda _build_id: "6-0",
        retry_delay_seconds=0,
    )
    assert (dispatched, failed) == (1, 0)
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT dispatch_count, dispatched_at IS NOT NULL FROM hbcb.queue_outbox WHERE build_id = %s",
            (outbox_build.build_id,),
        )
        count_after_recovery, was_dispatched = cursor.fetchone()
        assert count_after_recovery == 102 and was_dispatched

    assert repository.ping()
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM hbcb.builds")
        build_count = int(cursor.fetchone()[0])
        cursor.execute("SELECT COUNT(*) FROM hbcb.build_attempts")
        attempt_count = int(cursor.fetchone()[0])
        cursor.execute("SELECT COUNT(*) FROM hbcb.artifacts")
        artifact_count = int(cursor.fetchone()[0])
        cursor.execute("SELECT COUNT(*) FROM hbcb.build_events")
        event_count = int(cursor.fetchone()[0])

    print(
        json.dumps(
            {
                "gate": "G6_POSTGRES_GATE",
                "result": "PASS",
                "postgres": postgres_version,
                "migrations_applied": list(migration.applied),
                "builds": build_count,
                "attempts": attempt_count,
                "artifacts": artifact_count,
                "events": event_count,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
