#!/usr/bin/env python3
"""Live least-privilege denial gate for the G7 local service stack.

The gate runs in the one-shot ``service-test`` container.  Database probes are
transactional and always rolled back.  Storage probes target a reserved object
key beneath the configured deployment prefix and exercise forbidden broad
operations without creating an object version.
"""

from __future__ import annotations

import io
import json
import os
import sys
from typing import Callable


POSTGRES_INSUFFICIENT_PRIVILEGE = "42501"
S3_ACCESS_DENIED = "AccessDenied"
EXPECTED_BUCKET = "hbcb-artifacts"
EXPECTED_NAMESPACE = "local"
RESERVED_BUILD_ID = "00000000-0000-0000-0000-000000000000"
RESERVED_ATTEMPT_ID = "00000000-0000-0000-0000-000000000000"


class GateFailure(RuntimeError):
    """A safe-to-display gate failure that never contains a credential."""


def required(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        raise GateFailure(f"required environment variable {name} is missing")
    if "\n" in value or "\r" in value:
        raise GateFailure(f"required environment variable {name} is invalid")
    return value


def parse_secure(name: str, value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise GateFailure(f"{name} must be exactly true or false")


def expect_database_denied(dsn: str, label: str, statement: str) -> str:
    """Execute one no-effect statement and require PostgreSQL privilege denial."""

    try:
        import psycopg
    except Exception as exc:
        raise GateFailure(
            f"{label}: psycopg is unavailable ({type(exc).__name__})"
        ) from None

    connection = None
    cursor = None
    denied = False
    role = ""
    try:
        connection = psycopg.connect(
            dsn,
            connect_timeout=5,
            options="-c statement_timeout=5000 -c lock_timeout=5000",
            application_name="hbcb-g7-iam-gate",
        )
        cursor = connection.cursor()
        cursor.execute("SELECT current_user")
        row = cursor.fetchone()
        if row is None or not isinstance(row[0], str) or row[0] == "":
            raise GateFailure(f"{label}: database identity could not be verified")
        role = row[0]
        try:
            cursor.execute(statement)
        except psycopg.Error as exc:
            if exc.sqlstate != POSTGRES_INSUFFICIENT_PRIVILEGE:
                state = exc.sqlstate or "none"
                raise GateFailure(
                    f"{label}: expected SQLSTATE 42501, received {state}"
                ) from None
            denied = True
    except GateFailure:
        raise
    except Exception as exc:
        raise GateFailure(
            f"{label}: database probe failed unexpectedly ({type(exc).__name__})"
        ) from None
    finally:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
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

    if not denied:
        raise GateFailure(f"{label}: forbidden database operation unexpectedly succeeded")
    return role


def expect_storage_denied(label: str, operation: Callable[[], object]) -> None:
    """Require an authenticated S3 request to fail specifically as AccessDenied."""

    try:
        from minio.error import S3Error
    except Exception as exc:
        raise GateFailure(
            f"{label}: MinIO client is unavailable ({type(exc).__name__})"
        ) from None

    try:
        operation()
    except S3Error as exc:
        if exc.code != S3_ACCESS_DENIED:
            raise GateFailure(
                f"{label}: expected AccessDenied, received {exc.code or 'unknown'}"
            ) from None
        return
    except Exception as exc:
        raise GateFailure(
            f"{label}: storage probe failed unexpectedly ({type(exc).__name__})"
        ) from None
    raise GateFailure(f"{label}: forbidden storage operation unexpectedly succeeded")


def main() -> None:
    api_database_url = required("HBCB_IAM_DATABASE_API_URL")
    worker_database_url = required("HBCB_IAM_DATABASE_WORKER_URL")
    maintenance_database_url = required("HBCB_IAM_DATABASE_MAINTENANCE_URL")
    endpoint = required("HBCB_STORAGE_INTERNAL_ENDPOINT")
    bucket = required("HBCB_STORAGE_BUCKET")
    namespace = required("HBCB_DEPLOYMENT_NAMESPACE")
    secure = parse_secure(
        "HBCB_STORAGE_INTERNAL_SECURE",
        required("HBCB_STORAGE_INTERNAL_SECURE"),
    )
    region = required("HBCB_STORAGE_REGION")
    api_access_key = required("HBCB_STORAGE_API_ACCESS_KEY")
    api_secret_key = required("HBCB_STORAGE_API_SECRET_KEY")
    worker_access_key = required("HBCB_STORAGE_WORKER_ACCESS_KEY")
    worker_secret_key = required("HBCB_STORAGE_WORKER_SECRET_KEY")
    maintenance_access_key = required("HBCB_STORAGE_MAINTENANCE_ACCESS_KEY")
    maintenance_secret_key = required("HBCB_STORAGE_MAINTENANCE_SECRET_KEY")

    if bucket != EXPECTED_BUCKET or namespace != EXPECTED_NAMESPACE:
        raise GateFailure("storage target does not match the fixed G7 local policy scope")
    if len({api_access_key, worker_access_key, maintenance_access_key}) != 3:
        raise GateFailure("storage identities are not distinct")

    api_role = expect_database_denied(
        api_database_url,
        "API INSERT artifacts",
        "INSERT INTO hbcb.artifacts SELECT * FROM hbcb.artifacts WHERE false",
    )
    expect_database_denied(
        api_database_url,
        "API DELETE builds",
        "DELETE FROM hbcb.builds WHERE false",
    )
    expect_database_denied(
        api_database_url,
        "API CREATE TEMP TABLE",
        "CREATE TEMP TABLE hbcb_g7_iam_probe (value integer) ON COMMIT DROP",
    )
    worker_role = expect_database_denied(
        worker_database_url,
        "worker SELECT idempotency_keys",
        "SELECT 1 FROM hbcb.idempotency_keys WHERE false",
    )
    expect_database_denied(
        worker_database_url,
        "worker DELETE builds",
        "DELETE FROM hbcb.builds WHERE false",
    )
    maintenance_role = expect_database_denied(
        maintenance_database_url,
        "maintenance SELECT idempotency_keys",
        "SELECT 1 FROM hbcb.idempotency_keys WHERE false",
    )
    expect_database_denied(
        maintenance_database_url,
        "maintenance SELECT deletion attempts",
        "SELECT 1 FROM hbcb.artifact_deletion_attempts WHERE false",
    )
    expect_database_denied(
        maintenance_database_url,
        "maintenance UPDATE build status",
        "UPDATE hbcb.builds SET status = status WHERE false",
    )
    expect_database_denied(
        maintenance_database_url,
        "maintenance UPDATE artifact hash",
        "UPDATE hbcb.artifacts SET sha256 = sha256 WHERE false",
    )
    expect_database_denied(
        maintenance_database_url,
        "maintenance CREATE TEMP TABLE",
        "CREATE TEMP TABLE hbcb_g8_maintenance_probe (value integer) ON COMMIT DROP",
    )
    if len({api_role, worker_role, maintenance_role}) != 3:
        raise GateFailure("runtime database identities are not distinct")

    try:
        import urllib3
        from minio import Minio
    except Exception as exc:
        raise GateFailure(
            f"storage dependencies are unavailable ({type(exc).__name__})"
        ) from None

    api_http = urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=3.0, read=5.0),
        retries=False,
    )
    worker_http = urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=3.0, read=5.0),
        retries=False,
    )
    maintenance_http = urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=3.0, read=5.0),
        retries=False,
    )
    api_client = Minio(
        endpoint,
        access_key=api_access_key,
        secret_key=api_secret_key,
        secure=secure,
        region=region,
        http_client=api_http,
    )
    worker_client = Minio(
        endpoint,
        access_key=worker_access_key,
        secret_key=worker_secret_key,
        secure=secure,
        region=region,
        http_client=worker_http,
    )
    maintenance_client = Minio(
        endpoint,
        access_key=maintenance_access_key,
        secret_key=maintenance_secret_key,
        secure=secure,
        region=region,
        http_client=maintenance_http,
    )
    reserved_key = (
        f"{namespace}/v1/builds/{RESERVED_BUILD_ID}/attempts/"
        f"{RESERVED_ATTEMPT_ID}/complete-v1/qa.json"
    )
    payload = b"{}\n"
    try:
        expect_storage_denied(
            "API PutObject",
            lambda: api_client.put_object(
                bucket,
                reserved_key,
                io.BytesIO(payload),
                len(payload),
                content_type="application/json",
            ),
        )
        expect_storage_denied(
            "worker DeleteObject",
            lambda: worker_client.remove_object(bucket, reserved_key),
        )
        expect_storage_denied(
            "maintenance DeleteObject without exact version",
            lambda: maintenance_client.remove_object(bucket, reserved_key),
        )
    finally:
        api_http.clear()
        worker_http.clear()
        maintenance_http.clear()

    print(
        json.dumps(
            {
                "database_denials": 10,
                "gate": "G7_IAM_GATE",
                "result": "PASS",
                "storage_denials": 3,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def cli() -> int:
    try:
        main()
    except GateFailure as exc:
        print(f"G7_IAM_GATE: FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"G7_IAM_GATE: FAIL: unexpected {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
