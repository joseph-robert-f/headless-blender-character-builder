"""Fixtures for G5 service tests."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Tuple
from uuid import UUID

from hbcb_service.models import (
    ARTIFACT_CONTENT_TYPES,
    ArtifactRecord,
    AttemptRecord,
    AttemptStatus,
)
from hbcb_service.storage import artifact_object_key


ROOT = Path(__file__).resolve().parents[2]
FIXED_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
BUILD_ID = UUID("11111111-1111-4111-8111-111111111111")
ATTEMPT_ID = UUID("22222222-2222-4222-8222-222222222222")


def facet_request_bytes() -> bytes:
    return (ROOT / "examples" / "requests" / "facet-bot.json").read_bytes()


def moss_request_bytes() -> bytes:
    return (ROOT / "examples" / "requests" / "moss-hopper.json").read_bytes()


def valid_environment() -> Dict[str, str]:
    return {
        "HBCB_DEPLOYMENT_NAMESPACE": "local",
        "HBCB_API_TOKEN": "a" * 64,
        "HBCB_IDEMPOTENCY_SECRET": "b" * 64,
        "HBCB_DATABASE_URL": "postgresql://hbcb_api:secret@postgres:5432/hbcb",
        "HBCB_REDIS_URL": "redis://:secret@redis:6379/0",
        "HBCB_STORAGE_INTERNAL_ENDPOINT": "minio:9000",
        "HBCB_STORAGE_PUBLIC_ENDPOINT": "localhost:9000",
        "HBCB_STORAGE_ACCESS_KEY": "hbcb_api_key",
        "HBCB_STORAGE_SECRET_KEY": "c" * 64,
        "HBCB_STORAGE_BUCKET": "hbcb-artifacts",
        "HBCB_STORAGE_SECURE": "false",
        "HBCB_SIGNED_URL_TTL_SECONDS": "300",
    }


def artifact_records(
    *,
    build_id: UUID = BUILD_ID,
    attempt_id: UUID = ATTEMPT_ID,
    namespace: str = "local",
    bucket: str = "hbcb-artifacts",
    version_id: str | None = "fixture-version-1",
) -> Tuple[ArtifactRecord, ...]:
    records = []
    for index, (name, content_type) in enumerate(ARTIFACT_CONTENT_TYPES.items(), start=1):
        payload = (name + "\n").encode("utf-8")
        records.append(
            ArtifactRecord(
                build_id=build_id,
                attempt_id=attempt_id,
                relative_path=name,
                bucket=bucket,
                object_key=artifact_object_key(namespace, build_id, attempt_id, name),
                sha256=hashlib.sha256(payload).hexdigest(),
                bytes=len(payload),
                content_type=content_type,
                created_at=FIXED_NOW,
                version_id=version_id,
            )
        )
    return tuple(records)


def running_attempt(
    *,
    build_id: UUID = BUILD_ID,
    attempt_id: UUID = ATTEMPT_ID,
    attempt_number: int = 1,
) -> AttemptRecord:
    return AttemptRecord(
        attempt_id=attempt_id,
        build_id=build_id,
        attempt_number=attempt_number,
        status=AttemptStatus.RUNNING,
        worker_id="worker-1",
        lease_token_sha256="a" * 64,
        lease_expires_at=FIXED_NOW,
        heartbeat_at=FIXED_NOW,
        started_at=FIXED_NOW,
        finished_at=None,
        exit_code=None,
        reason_code=None,
    )


def write_artifact_files(root: Path, records: Iterable[ArtifactRecord]) -> None:
    for record in records:
        path = root / record.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((record.relative_path + "\n").encode("utf-8"))
