#!/usr/bin/env python3
"""Live MinIO/PostgreSQL gate for exact-version orphan cleanup.

The fixture uses two immutable versions of one canonical artifact key.  The
older version is referenced by PostgreSQL and the newer version is not.  A
future logical clock makes the test deterministic without changing either
MinIO's clock or the production grace-period defaults.

Only a unique fixture key and its matching database rows are ever mutated.
The caller must explicitly identify the stack as disposable, and a baseline
preview refuses to proceed when any pre-existing orphan is visible.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from collections.abc import Mapping
from typing import Any, Callable, Optional
from uuid import UUID, uuid4

import psycopg
import urllib3
from minio import Minio
from minio.error import S3Error

from hbcb_service.maintenance import (
    MaintenanceService,
    MinioVersionedObjectClient,
    PostgresMaintenanceStore,
)
from hbcb_service.maintenance_main import run as run_maintenance_cli


EXPECTED_BUCKET = "hbcb-artifacts"
EXPECTED_NAMESPACE = "local"
SHA256_METADATA_KEYS = ("sha256", "x-amz-meta-sha256")


class GateFailure(RuntimeError):
    """Safe-to-display contract failure without dependency exception text."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise GateFailure(code)


def required(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "" or "\n" in value or "\r" in value:
        raise GateFailure("required_environment_missing_or_invalid")
    return value


def secure_value() -> bool:
    value = required("HBCB_STORAGE_INTERNAL_SECURE")
    if value == "true":
        return True
    if value == "false":
        return False
    raise GateFailure("storage_secure_flag_invalid")


def connection_factory(dsn: str) -> Callable[[], Any]:
    def connect() -> Any:
        return psycopg.connect(
            dsn,
            connect_timeout=5,
            options="-c statement_timeout=5000 -c lock_timeout=5000",
        )

    return connect


def client(endpoint: str, access_key: str, secret_key: str, secure: bool, region: str):
    pool = urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=3.0, read=5.0),
        retries=False,
    )
    return (
        Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
            http_client=pool,
        ),
        pool,
    )


def metadata_sha256(observed: Any) -> Optional[str]:
    metadata = getattr(observed, "metadata", None)
    if not isinstance(metadata, Mapping):
        return None
    for key, value in metadata.items():
        if str(key).lower() in SHA256_METADATA_KEYS:
            return str(value)
    return None


def exact_version_absent(storage: Minio, bucket: str, key: str, version_id: str) -> bool:
    try:
        storage.stat_object(bucket, key, version_id=version_id)
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchVersion"}:
            return True
        raise GateFailure("deleted_version_probe_failed") from None
    return False


def cleanup_database(admin_dsn: str, build_id: UUID) -> None:
    with psycopg.connect(
        admin_dsn,
        connect_timeout=5,
        options="-c statement_timeout=5000 -c lock_timeout=5000",
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM hbcb.artifact_deletion_attempts
                WHERE deletion_id IN (
                    SELECT id FROM hbcb.artifact_deletion_queue
                    WHERE namespace = %s AND build_id = %s
                )
                """,
                (EXPECTED_NAMESPACE, build_id),
            )
            cursor.execute(
                """
                DELETE FROM hbcb.artifact_deletion_queue
                WHERE namespace = %s AND build_id = %s
                """,
                (EXPECTED_NAMESPACE, build_id),
            )
            cursor.execute(
                "DELETE FROM hbcb.builds WHERE namespace = %s AND id = %s",
                (EXPECTED_NAMESPACE, build_id),
            )
        connection.commit()


def cleanup_versions(storage: Minio, bucket: str, key: str) -> None:
    versions = tuple(
        storage.list_objects(
            bucket,
            prefix=key,
            recursive=True,
            include_version=True,
        )
    )
    for item in versions:
        if getattr(item, "object_name", None) != key:
            continue
        version_id = getattr(item, "version_id", None)
        if not isinstance(version_id, str) or not version_id or version_id == "null":
            raise GateFailure("fixture_cleanup_inventory_invalid")
        storage.remove_object(bucket, key, version_id=version_id)


def seed_reference(
    admin_dsn: str,
    *,
    build_id: UUID,
    attempt_id: UUID,
    key: str,
    version_id: str,
    sha256: str,
    size: int,
    now: datetime,
) -> None:
    with psycopg.connect(
        admin_dsn,
        connect_timeout=5,
        options="-c statement_timeout=5000 -c lock_timeout=5000",
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO hbcb.builds (
                    id, namespace, request_canonical, request_sha256, spec_sha256,
                    status, state_version, max_attempts, manifest_object_key,
                    manifest_sha256, manifest_bytes, created_at, updated_at,
                    finished_at, published_at
                ) VALUES (%s,%s,%s,%s,%s,'succeeded',2,2,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    build_id,
                    EXPECTED_NAMESPACE,
                    b"{}",
                    "a" * 64,
                    "b" * 64,
                    key,
                    sha256,
                    size,
                    now,
                    now,
                    now,
                    now,
                ),
            )
            cursor.execute(
                """
                INSERT INTO hbcb.build_attempts (
                    id, build_id, attempt_number, status, worker_id,
                    lease_token_sha256, lease_expires_at, heartbeat_at,
                    started_at, finished_at, exit_code, created_at
                ) VALUES (%s,%s,1,'succeeded','g8-orphan-minio-gate',%s,%s,%s,%s,%s,0,%s)
                """,
                (
                    attempt_id,
                    build_id,
                    "c" * 64,
                    now,
                    now,
                    now,
                    now,
                    now,
                ),
            )
            cursor.execute(
                """
                INSERT INTO hbcb.artifacts (
                    build_id, attempt_id, relative_path, bucket, object_key,
                    sha256, bytes, content_type, version_id, created_at
                ) VALUES (%s,%s,'manifest.json',%s,%s,%s,%s,'application/json',%s,%s)
                """,
                (
                    build_id,
                    attempt_id,
                    EXPECTED_BUCKET,
                    key,
                    sha256,
                    size,
                    version_id,
                    now,
                ),
            )
        connection.commit()


def queue_evidence(admin_dsn: str, build_id: UUID) -> tuple[Any, ...]:
    with psycopg.connect(
        admin_dsn,
        connect_timeout=5,
        options="-c statement_timeout=5000 -c lock_timeout=5000",
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT bucket, object_key, version_id, sha256, bytes,
                       evidence_origin, object_last_modified, status
                FROM hbcb.artifact_deletion_queue
                WHERE namespace = %s AND build_id = %s
                """,
                (EXPECTED_NAMESPACE, build_id),
            )
            rows = cursor.fetchall()
    require(len(rows) == 1, "durable_queue_cardinality_mismatch")
    return tuple(rows[0])


def deletion_evidence(admin_dsn: str, build_id: UUID) -> tuple[Any, ...]:
    with psycopg.connect(
        admin_dsn,
        connect_timeout=5,
        options="-c statement_timeout=5000 -c lock_timeout=5000",
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT q.status, q.attempt_count, a.outcome, a.error_code
                FROM hbcb.artifact_deletion_queue q
                JOIN hbcb.artifact_deletion_attempts a ON a.deletion_id = q.id
                WHERE q.namespace = %s AND q.build_id = %s
                """,
                (EXPECTED_NAMESPACE, build_id),
            )
            rows = cursor.fetchall()
    require(len(rows) == 1, "deletion_audit_cardinality_mismatch")
    return tuple(rows[0])


def run_cli(
    service: MaintenanceService,
    arguments: list[str],
    *,
    now: datetime,
) -> dict[str, Any]:
    output = io.StringIO()
    errors = io.StringIO()
    code = run_maintenance_cli(
        arguments,
        environment={},
        service_factory=lambda _environment: service,
        stdout=output,
        stderr=errors,
        now=now,
    )
    if code != 0 or errors.getvalue() != "":
        try:
            error_payload = json.loads(errors.getvalue())
            error_code = error_payload["error"]["code"]
        except (json.JSONDecodeError, KeyError, TypeError):
            raise GateFailure("maintenance_cli_failed") from None
        if not isinstance(error_code, str) or not error_code.replace("_", "").isalnum():
            raise GateFailure("maintenance_cli_failed")
        raise GateFailure("maintenance_cli_failed_" + error_code)
    try:
        payload = json.loads(output.getvalue())
    except json.JSONDecodeError:
        raise GateFailure("maintenance_cli_output_invalid") from None
    require(isinstance(payload, dict), "maintenance_cli_output_invalid")
    return payload


def execute() -> dict[str, Any]:
    require(
        os.environ.get("HBCB_LIFECYCLE_DESTRUCTIVE_DISPOSABLE") == "1",
        "disposable_confirmation_required",
    )
    require(required("HBCB_DEPLOYMENT_NAMESPACE") == EXPECTED_NAMESPACE, "namespace_mismatch")
    require(required("HBCB_STORAGE_BUCKET") == EXPECTED_BUCKET, "bucket_mismatch")
    maintenance_dsn = required("HBCB_G8_POSTGRES_DSN")
    admin_dsn = required("HBCB_G8_POSTGRES_ADMIN_DSN")
    endpoint = required("HBCB_STORAGE_INTERNAL_ENDPOINT")
    region = required("HBCB_STORAGE_REGION")
    secure = secure_value()
    maintenance_secret = required("HBCB_STORAGE_MAINTENANCE_SECRET_KEY")
    require(
        hashlib.sha256(maintenance_secret.encode("ascii")).hexdigest()
        == required("HBCB_ORPHAN_EXPECTED_MAINTENANCE_SECRET_SHA256"),
        "maintenance_secret_interpolation_changed",
    )
    worker, worker_pool = client(
        endpoint,
        required("HBCB_STORAGE_WORKER_ACCESS_KEY"),
        required("HBCB_STORAGE_WORKER_SECRET_KEY"),
        secure,
        region,
    )
    maintenance, maintenance_pool = client(
        endpoint,
        required("HBCB_STORAGE_MAINTENANCE_ACCESS_KEY"),
        maintenance_secret,
        secure,
        region,
    )
    build_id = uuid4()
    attempt_id = uuid4()
    key = (
        f"{EXPECTED_NAMESPACE}/v1/builds/{build_id}/attempts/{attempt_id}/"
        "complete-v1/manifest.json"
    )
    fixture_started = False
    primary: Optional[BaseException] = None
    result: Optional[dict[str, Any]] = None
    try:
        objects = MinioVersionedObjectClient(maintenance)
        service = MaintenanceService(
            PostgresMaintenanceStore(
                connection_factory(maintenance_dsn),
                namespace=EXPECTED_NAMESPACE,
            ),
            namespace=EXPECTED_NAMESPACE,
            bucket=EXPECTED_BUCKET,
            objects=objects,
        )
        direct_baseline: Optional[tuple[Any, ...]] = None
        for attempt in range(30):
            try:
                direct_baseline = tuple(
                    maintenance.list_objects(
                        EXPECTED_BUCKET,
                        prefix=f"{EXPECTED_NAMESPACE}/v1/builds/",
                        recursive=True,
                        include_version=True,
                    )
                )
                break
            except S3Error as exc:
                # A freshly-created MinIO user can briefly authenticate before
                # its attached policy is visible on the data plane.  Both
                # states are bounded here; a persistent authorization failure
                # still fails the gate before any fixture object is created.
                if exc.code not in {"InvalidAccessKeyId", "AccessDenied"} or attempt == 29:
                    code = exc.code if isinstance(exc.code, str) else "unknown"
                    if not code.replace("_", "").isalnum():
                        code = "unknown"
                    raise GateFailure(
                        "live_version_listing_failed_" + code + "_after_readiness_window"
                    ) from None
                time.sleep(1)
            except Exception as exc:
                raise GateFailure(
                    "live_version_listing_failed_" + type(exc).__name__
                ) from None
        require(direct_baseline is not None, "live_version_listing_failed")
        require(not direct_baseline, "baseline_object_versions_present")
        baseline_now = datetime.now(timezone.utc) + timedelta(days=8)
        baseline = run_cli(
            service,
            [
                "discover-orphans",
                "--orphan-grace-days",
                "7",
                "--limit",
                "100",
                "--scan-limit",
                "1000",
            ],
            now=baseline_now,
        )
        require(
            baseline
            == {
                "candidates": 0,
                "dry_run": True,
                "queued": 0,
                "scanned": baseline["scanned"],
            }
            and type(baseline["scanned"]) is int,
            "baseline_orphans_present",
        )

        fixture_started = True
        referenced_payload = b'{"fixture":"referenced"}\n'
        orphan_payload = b'{"fixture":"orphan"}\n'
        referenced_sha = hashlib.sha256(referenced_payload).hexdigest()
        orphan_sha = hashlib.sha256(orphan_payload).hexdigest()
        referenced_upload = worker.put_object(
            EXPECTED_BUCKET,
            key,
            io.BytesIO(referenced_payload),
            len(referenced_payload),
            content_type="application/json",
            metadata={"sha256": referenced_sha},
        )
        orphan_upload = worker.put_object(
            EXPECTED_BUCKET,
            key,
            io.BytesIO(orphan_payload),
            len(orphan_payload),
            content_type="application/json",
            metadata={"sha256": orphan_sha},
        )
        referenced_version = getattr(referenced_upload, "version_id", None)
        orphan_version = getattr(orphan_upload, "version_id", None)
        require(
            isinstance(referenced_version, str)
            and isinstance(orphan_version, str)
            and referenced_version not in {"", "null", orphan_version},
            "immutable_version_ids_invalid",
        )
        referenced_stat = maintenance.stat_object(
            EXPECTED_BUCKET, key, version_id=referenced_version
        )
        orphan_stat = maintenance.stat_object(
            EXPECTED_BUCKET, key, version_id=orphan_version
        )
        require(
            getattr(referenced_stat, "size", None) == len(referenced_payload)
            and metadata_sha256(referenced_stat) == referenced_sha,
            "referenced_version_stat_mismatch",
        )
        require(
            getattr(orphan_stat, "size", None) == len(orphan_payload)
            and metadata_sha256(orphan_stat) == orphan_sha,
            "orphan_version_stat_mismatch",
        )
        referenced_modified = getattr(referenced_stat, "last_modified", None)
        orphan_modified = getattr(orphan_stat, "last_modified", None)
        require(
            isinstance(referenced_modified, datetime)
            and isinstance(orphan_modified, datetime),
            "version_time_missing",
        )
        fixture_time = max(referenced_modified, orphan_modified)
        # The durable queue preserves the ListObjectVersions timestamp exactly;
        # the version-list and HEAD representations can differ at sub-second
        # precision, so capture and validate both sides explicitly.
        orphan_listings = tuple(
            item
            for item in maintenance.list_objects(
                EXPECTED_BUCKET,
                prefix=key,
                recursive=True,
                include_version=True,
            )
            if getattr(item, "object_name", None) == key
            and getattr(item, "version_id", None) == orphan_version
        )
        require(len(orphan_listings) == 1, "orphan_version_listing_mismatch")
        orphan_inventory_modified = getattr(
            orphan_listings[0], "last_modified", None
        )
        require(
            isinstance(orphan_inventory_modified, datetime)
            and orphan_inventory_modified.replace(microsecond=0)
            == orphan_modified.replace(microsecond=0),
            "orphan_version_time_mismatch",
        )
        seed_reference(
            admin_dsn,
            build_id=build_id,
            attempt_id=attempt_id,
            key=key,
            version_id=referenced_version,
            sha256=referenced_sha,
            size=len(referenced_payload),
            now=fixture_time,
        )

        discovery_arguments = [
            "discover-orphans",
            "--orphan-grace-days",
            "1",
            "--limit",
            "10",
            "--scan-limit",
            "1000",
        ]
        grace_preview = run_cli(
            service,
            discovery_arguments,
            now=fixture_time + timedelta(hours=12),
        )
        require(
            grace_preview["dry_run"] is True
            and grace_preview["candidates"] == 0
            and grace_preview["queued"] == 0,
            "object_grace_not_enforced",
        )
        discovery_now = fixture_time + timedelta(days=2)
        preview = run_cli(service, discovery_arguments, now=discovery_now)
        require(
            preview["dry_run"] is True
            and preview["candidates"] == 1
            and preview["queued"] == 0,
            "orphan_preview_mismatch",
        )
        with psycopg.connect(admin_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM hbcb.artifact_deletion_queue
                    WHERE namespace = %s AND build_id = %s
                    """,
                    (EXPECTED_NAMESPACE, build_id),
                )
                require(cursor.fetchone()[0] == 0, "orphan_preview_mutated_database")

        applied = run_cli(
            service,
            [*discovery_arguments, "--apply"],
            now=discovery_now,
        )
        require(
            applied["dry_run"] is False
            and applied["candidates"] == 1
            and applied["queued"] == 1,
            "orphan_apply_mismatch",
        )
        queued = queue_evidence(admin_dsn, build_id)
        expected_queue = (
            EXPECTED_BUCKET,
            key,
            orphan_version,
            orphan_sha,
            len(orphan_payload),
            "orphan_inventory",
            orphan_inventory_modified,
            "pending",
        )
        queue_fields = (
            "bucket",
            "object_key",
            "version_id",
            "sha256",
            "bytes",
            "origin",
            "last_modified",
            "status",
        )
        for field, actual, expected in zip(queue_fields, queued, expected_queue):
            require(actual == expected, f"durable_queue_{field}_mismatch")

        deletion_arguments = [
            "delete-artifacts",
            "--orphan-grace-days",
            "1",
            "--limit",
            "10",
            "--worker-id",
            "g8-orphan-minio-gate",
        ]
        deletion_preview = run_cli(
            service,
            deletion_arguments,
            now=discovery_now + timedelta(hours=12),
        )
        require(
            deletion_preview
            == {"considered": 0, "deleted": 0, "dry_run": True, "failed": 0},
            "deletion_grace_not_enforced",
        )
        deleted = run_cli(
            service,
            [*deletion_arguments, "--apply"],
            now=discovery_now + timedelta(days=2),
        )
        require(
            deleted
            == {"considered": 1, "deleted": 1, "dry_run": False, "failed": 0},
            "exact_version_deletion_mismatch",
        )
        require(
            deletion_evidence(admin_dsn, build_id) == ("deleted", 1, "deleted", None),
            "deletion_audit_mismatch",
        )
        require(
            exact_version_absent(maintenance, EXPECTED_BUCKET, key, orphan_version),
            "orphan_version_survived",
        )
        surviving = maintenance.stat_object(
            EXPECTED_BUCKET, key, version_id=referenced_version
        )
        require(
            getattr(surviving, "version_id", None) == referenced_version
            and getattr(surviving, "size", None) == len(referenced_payload)
            and metadata_sha256(surviving) == referenced_sha,
            "referenced_version_did_not_survive",
        )
        listed_fixture_versions = {
            getattr(item, "version_id", None)
            for item in maintenance.list_objects(
                EXPECTED_BUCKET,
                prefix=key,
                recursive=True,
                include_version=True,
            )
            if getattr(item, "object_name", None) == key
        }
        require(
            listed_fixture_versions == {referenced_version},
            "exact_version_inventory_mismatch",
        )
        result = {
            "deleted_orphan_versions": 1,
            "dry_run_candidates": 1,
            "gate": "G8_ORPHAN_MINIO_GATE",
            "queued_exact_versions": 1,
            "referenced_versions_survived": 1,
            "result": "PASS",
        }
    except BaseException as exc:
        primary = exc
    finally:
        cleanup_failed = False
        if fixture_started:
            try:
                cleanup_versions(maintenance, EXPECTED_BUCKET, key)
            except Exception:
                cleanup_failed = True
            try:
                cleanup_database(admin_dsn, build_id)
            except Exception:
                cleanup_failed = True
        worker_pool.clear()
        maintenance_pool.clear()
        if primary is None and cleanup_failed:
            primary = GateFailure("fixture_cleanup_failed")
    if primary is not None:
        raise primary
    require(result is not None, "result_missing")
    return result


def main() -> int:
    try:
        result = execute()
    except GateFailure as exc:
        print(f"G8_ORPHAN_MINIO_GATE: FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"G8_ORPHAN_MINIO_GATE: FAIL: unexpected {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
