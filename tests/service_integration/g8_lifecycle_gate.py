#!/usr/bin/env python3
"""Real PostgreSQL gate for bounded, fail-closed orphan reconciliation.

This gate intentionally writes fixture rows and therefore refuses to run unless
the caller supplies an explicit test sentinel.  It uses a unique namespace and
removes its database rows on success and through best-effort exception cleanup.
"""

from __future__ import annotations

import hashlib
import json
import os
import atexit
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg

from hbcb_service.maintenance import (
    PostgresMaintenanceStore,
    StoredObjectVersion,
)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def version(namespace: str, bucket: str, build_id, attempt_id, name: str, age_days: int):
    payload = (name + "\n").encode("ascii")
    return StoredObjectVersion(
        namespace=namespace,
        build_id=build_id,
        attempt_id=attempt_id,
        relative_path=name,
        bucket=bucket,
        object_key=(
            f"{namespace}/v1/builds/{build_id}/attempts/{attempt_id}/"
            f"complete-v1/{name}"
        ),
        version_id="version-" + uuid4().hex,
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        last_modified=NOW - timedelta(days=age_days),
    )


NOW = datetime.now(timezone.utc).replace(microsecond=0)


def main() -> None:
    maintenance_dsn = os.environ.get("HBCB_G8_POSTGRES_DSN", "")
    admin_dsn = os.environ.get("HBCB_G8_POSTGRES_ADMIN_DSN", "")
    require(bool(maintenance_dsn), "maintenance_database_url_required")
    require(bool(admin_dsn), "admin_database_url_required")
    require(
        os.environ.get("HBCB_LIFECYCLE_DESTRUCTIVE_DISPOSABLE") == "1",
        "disposable_confirmation_required",
    )
    namespace = "lifecycle-" + uuid4().hex[:12]
    bucket = "hbcb-artifacts"
    active_build = uuid4()
    active_attempt = uuid4()
    referenced_build = uuid4()
    referenced_attempt = uuid4()
    missing_build = uuid4()
    missing_attempt = uuid4()

    active = version(namespace, bucket, active_build, active_attempt, "model.stl", 8)
    referenced = version(
        namespace, bucket, referenced_build, referenced_attempt, "qa.json", 8
    )
    missing = version(namespace, bucket, missing_build, missing_attempt, "model.glb", 8)
    fresh = version(namespace, bucket, uuid4(), uuid4(), "preview.png", 0)

    def cleanup() -> None:
        with psycopg.connect(admin_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM hbcb.artifact_deletion_attempts
                    WHERE deletion_id IN (
                        SELECT id FROM hbcb.artifact_deletion_queue
                        WHERE namespace = %s
                    )
                    """,
                    (namespace,),
                )
                cursor.execute(
                    "DELETE FROM hbcb.artifact_deletion_queue WHERE namespace = %s",
                    (namespace,),
                )
                cursor.execute(
                    "DELETE FROM hbcb.builds WHERE namespace = %s",
                    (namespace,),
                )
            connection.commit()

    atexit.register(cleanup)

    with psycopg.connect(admin_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM hbcb.builds WHERE namespace = %s",
                (namespace,),
            )
            require(cursor.fetchone()[0] == 0, "fixture_namespace_not_empty")
            cursor.execute(
                """
                INSERT INTO hbcb.builds (
                    id, namespace, request_canonical, request_sha256, spec_sha256,
                    status, state_version, max_attempts, created_at, updated_at
                ) VALUES (%s,%s,%s,%s,%s,'queued',1,2,%s,%s)
                """,
                (
                    active_build,
                    namespace,
                    b"{}",
                    "a" * 64,
                    "b" * 64,
                    NOW,
                    NOW,
                ),
            )
            cursor.execute(
                """
                INSERT INTO hbcb.builds (
                    id, namespace, request_canonical, request_sha256, spec_sha256,
                    status, state_version, max_attempts, manifest_object_key,
                    manifest_sha256, manifest_bytes, created_at, updated_at,
                    finished_at, published_at
                ) VALUES (%s,%s,%s,%s,%s,'succeeded',2,2,%s,%s,1,%s,%s,%s,%s)
                """,
                (
                    referenced_build,
                    namespace,
                    b"{}",
                    "c" * 64,
                    "d" * 64,
                    referenced.object_key,
                    "e" * 64,
                    NOW,
                    NOW,
                    NOW,
                    NOW,
                ),
            )
            cursor.execute(
                """
                INSERT INTO hbcb.build_attempts (
                    id, build_id, attempt_number, status, worker_id,
                    lease_token_sha256, lease_expires_at, heartbeat_at,
                    started_at, finished_at, exit_code, created_at
                ) VALUES (%s,%s,1,'succeeded','lifecycle-gate',%s,%s,%s,%s,%s,0,%s)
                """,
                (
                    referenced_attempt,
                    referenced_build,
                    "f" * 64,
                    NOW,
                    NOW,
                    NOW,
                    NOW,
                    NOW,
                ),
            )
            cursor.execute(
                """
                INSERT INTO hbcb.artifacts (
                    build_id, attempt_id, relative_path, bucket, object_key,
                    sha256, bytes, content_type, version_id, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,'application/json',%s,%s)
                """,
                (
                    referenced_build,
                    referenced_attempt,
                    referenced.relative_path,
                    bucket,
                    referenced.object_key,
                    referenced.sha256,
                    referenced.bytes,
                    referenced.version_id,
                    NOW,
                ),
            )
        connection.commit()

    store = PostgresMaintenanceStore(
        lambda: psycopg.connect(maintenance_dsn), namespace=namespace
    )
    candidates = (active, referenced, missing, fresh)
    cutoff = NOW - timedelta(days=7)
    preview = store.reconcile_orphan_versions(candidates, cutoff, NOW, False, 100)
    require(preview == (missing,), "preview_selected_unsafe_version")

    with psycopg.connect(admin_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM hbcb.artifact_deletion_queue WHERE namespace = %s",
                (namespace,),
            )
            require(cursor.fetchone()[0] == 0, "preview_mutated_database")

    applied = store.reconcile_orphan_versions(candidates, cutoff, NOW, True, 100)
    require(applied == (missing,), "apply_selected_unsafe_version")

    # Seed malicious/stale queue evidence for an active and a referenced
    # version. Claiming must independently fail closed even if discovery was
    # bypassed or state changed after it ran.
    with psycopg.connect(admin_dsn) as connection:
        with connection.cursor() as cursor:
            for item in (active, referenced):
                cursor.execute(
                    """
                    INSERT INTO hbcb.artifact_deletion_queue (
                        namespace, build_id, bucket, object_key, version_id,
                        sha256, bytes, queued_at, evidence_origin,
                        object_last_modified
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'orphan_inventory',%s)
                    """,
                    (
                        namespace,
                        item.build_id,
                        bucket,
                        item.object_key,
                        item.version_id,
                        item.sha256,
                        item.bytes,
                        NOW - timedelta(days=8),
                        item.last_modified,
                    ),
                )
        connection.commit()

    deletion_now = NOW + timedelta(days=8)
    claimed = store.claim_deletions(
        deletion_now - timedelta(days=7),
        deletion_now,
        100,
        uuid4(),
        deletion_now + timedelta(minutes=15),
    )
    require(len(claimed) == 1, "claim_did_not_filter_unsafe_versions")
    require(claimed[0].evidence.identity[2:] == (bucket, missing.object_key, missing.version_id),
            "claim_selected_wrong_version")

    with psycopg.connect(admin_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT evidence_origin, object_last_modified, status
                FROM hbcb.artifact_deletion_queue
                WHERE object_key = %s AND version_id = %s
                """,
                (missing.object_key, missing.version_id),
            )
            row = cursor.fetchone()
            require(row == ("orphan_inventory", missing.last_modified, "deleting"),
                    "durable_orphan_evidence_mismatch")

    print(
        json.dumps(
            {
                "active_filtered": 1,
                "fresh_filtered": 1,
                "gate": "G8_LIFECYCLE_GATE",
                "queued": 1,
                "referenced_filtered": 1,
                "result": "PASS",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    cleanup()
    atexit.unregister(cleanup)


if __name__ == "__main__":
    main()
