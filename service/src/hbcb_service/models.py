"""Immutable service-domain records and state-transition policy."""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Optional
from uuid import UUID

from shared.build_manifest import MAX_PUBLISHED_ARTIFACT_BYTES
from shared.character_spec import validate_build_request
from shared.json_contract import ContractValidationError

from .errors import ServiceError, StateConflict


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SAFE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
WORKER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
OBJECT_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,1023}$")
MAX_PUBLISHED_BYTES = MAX_PUBLISHED_ARTIFACT_BYTES
MAX_DISPATCH_COUNT = (1 << 63) - 1

ARTIFACT_CONTENT_TYPES = MappingProxyType(
    {
        "model.blend": "application/x-blender",
        "model.glb": "model/gltf-binary",
        "model.stl": "model/stl",
        "preview.png": "image/png",
        "diagnostics/front.png": "image/png",
        "diagnostics/side.png": "image/png",
        "diagnostics/back.png": "image/png",
        "qa.json": "application/json",
        "manifest.json": "application/json",
    }
)
REQUIRED_PUBLISHED_ARTIFACTS = tuple(ARTIFACT_CONTENT_TYPES)


class BuildStatus(str, Enum):
    VALIDATING = "validating"
    QUEUED = "queued"
    RUNNING = "running"
    GEOMETRY_QA = "geometry_qa"
    RENDERING = "rendering"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    NEEDS_REVIEW = "needs_review"


class AttemptStatus(str, Enum):
    LEASED = "leased"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    CANCELED = "canceled"
    TIMED_OUT = "timed_out"
    LOST = "lost"


TERMINAL_BUILD_STATUSES = frozenset(
    {BuildStatus.SUCCEEDED, BuildStatus.FAILED, BuildStatus.CANCELED, BuildStatus.NEEDS_REVIEW}
)

# The G4 launcher is intentionally opaque and emits only a terminal result.
# G6 may report trusted optional stages when it has real evidence, but it may
# also publish a verified success directly from RUNNING without fabricating
# internal progress.
ALLOWED_BUILD_TRANSITIONS = MappingProxyType(
    {
        BuildStatus.VALIDATING: frozenset(
            {BuildStatus.QUEUED, BuildStatus.FAILED, BuildStatus.CANCELED}
        ),
        BuildStatus.QUEUED: frozenset({BuildStatus.RUNNING, BuildStatus.CANCELED}),
        BuildStatus.RUNNING: frozenset(
            {
                BuildStatus.QUEUED,
                BuildStatus.GEOMETRY_QA,
                BuildStatus.FAILED,
                BuildStatus.CANCELED,
                BuildStatus.NEEDS_REVIEW,
            }
        ),
        BuildStatus.GEOMETRY_QA: frozenset(
            {
                BuildStatus.RENDERING,
                BuildStatus.FAILED,
                BuildStatus.CANCELED,
                BuildStatus.NEEDS_REVIEW,
            }
        ),
        BuildStatus.RENDERING: frozenset(
            {BuildStatus.FAILED, BuildStatus.CANCELED, BuildStatus.NEEDS_REVIEW}
        ),
        BuildStatus.SUCCEEDED: frozenset(),
        BuildStatus.FAILED: frozenset(),
        BuildStatus.CANCELED: frozenset(),
        BuildStatus.NEEDS_REVIEW: frozenset(),
    }
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def require_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ServiceError("invalid_timestamp", f"{label} must be timezone-aware")
    return value


def require_sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ServiceError("invalid_sha256", f"{label} must be a lowercase SHA-256 digest")
    return value


def require_safe_code(value: Optional[str], label: str, *, required: bool = False) -> Optional[str]:
    if value is None and not required:
        return None
    if not isinstance(value, str) or SAFE_CODE_PATTERN.fullmatch(value) is None:
        raise ServiceError("invalid_reason_code", f"{label} is outside policy")
    return value


def require_transition(current: BuildStatus, target: BuildStatus) -> None:
    if not isinstance(current, BuildStatus) or not isinstance(target, BuildStatus):
        raise StateConflict("invalid_transition", "build transition is outside policy")
    if target not in ALLOWED_BUILD_TRANSITIONS[current]:
        raise StateConflict(
            "invalid_transition", f"build cannot transition from {current.value} to {target.value}"
        )


@dataclass(frozen=True)
class BuildRecord:
    build_id: UUID
    request_sha256: str
    spec_sha256: str
    canonical_request: bytes
    status: BuildStatus
    state_version: int
    max_attempts: int
    cancel_requested_at: Optional[datetime]
    terminal_code: Optional[str]
    manifest_object_key: Optional[str]
    manifest_sha256: Optional[str]
    manifest_bytes: Optional[int]
    created_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime]
    published_at: Optional[datetime]

    def __post_init__(self) -> None:
        if not isinstance(self.build_id, UUID):
            raise ServiceError("invalid_build_id", "build ID is invalid")
        require_sha256(self.request_sha256, "request_sha256")
        require_sha256(self.spec_sha256, "spec_sha256")
        if not isinstance(self.canonical_request, bytes) or not 1 <= len(self.canonical_request) <= 64 * 1024:
            raise ServiceError("invalid_request_bytes", "canonical request is outside policy")
        try:
            validated_request = validate_build_request(self.canonical_request)
        except ContractValidationError as exc:
            raise ServiceError(
                "invalid_request_bytes", "canonical request does not satisfy the build contract"
            ) from exc
        if validated_request.canonical_bytes != self.canonical_request:
            raise ServiceError(
                "invalid_request_bytes", "stored request bytes are not canonical"
            )
        if not hmac.compare_digest(validated_request.request_sha256, self.request_sha256):
            raise ServiceError(
                "invalid_request_hash", "canonical request does not match request_sha256"
            )
        if not hmac.compare_digest(validated_request.spec_sha256, self.spec_sha256):
            raise ServiceError(
                "invalid_spec_hash", "canonical request does not match spec_sha256"
            )
        if not isinstance(self.status, BuildStatus):
            raise ServiceError("invalid_build_status", "build status is invalid")
        if isinstance(self.state_version, bool) or not isinstance(self.state_version, int) or self.state_version < 0:
            raise ServiceError("invalid_state_version", "state version is invalid")
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or not 1 <= self.max_attempts <= 5:
            raise ServiceError("invalid_max_attempts", "maximum attempts is outside policy")
        require_safe_code(self.terminal_code, "terminal_code")
        require_utc(self.created_at, "created_at")
        require_utc(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ServiceError("invalid_timestamp", "updated_at precedes created_at")
        for value, label in (
            (self.cancel_requested_at, "cancel_requested_at"),
            (self.finished_at, "finished_at"),
            (self.published_at, "published_at"),
        ):
            if value is not None:
                require_utc(value, label)
        terminal = self.status in TERMINAL_BUILD_STATUSES
        if terminal != (self.finished_at is not None):
            raise ServiceError("invalid_terminal_state", "terminal timestamp does not match status")
        failure_terminal = self.status in (
            BuildStatus.FAILED,
            BuildStatus.CANCELED,
            BuildStatus.NEEDS_REVIEW,
        )
        if failure_terminal != (self.terminal_code is not None):
            raise ServiceError("invalid_terminal_state", "terminal reason does not match status")
        manifest_fields = (
            self.manifest_object_key,
            self.manifest_sha256,
            self.manifest_bytes,
            self.published_at,
        )
        if self.status is BuildStatus.SUCCEEDED:
            if any(value is None for value in manifest_fields):
                raise ServiceError("invalid_success_state", "successful build lacks manifest evidence")
            require_sha256(self.manifest_sha256 or "", "manifest_sha256")
            if (
                not isinstance(self.manifest_object_key, str)
                or OBJECT_KEY_PATTERN.fullmatch(self.manifest_object_key) is None
                or ".." in self.manifest_object_key.split("/")
            ):
                raise ServiceError("invalid_success_state", "manifest object key is outside policy")
            if (
                isinstance(self.manifest_bytes, bool)
                or not isinstance(self.manifest_bytes, int)
                or not 1 <= self.manifest_bytes <= MAX_PUBLISHED_BYTES
            ):
                raise ServiceError("invalid_success_state", "manifest byte count is outside policy")
        elif any(value is not None for value in manifest_fields):
            raise ServiceError("invalid_manifest_state", "non-success build retained manifest evidence")
        if self.status is BuildStatus.CANCELED and self.cancel_requested_at is None:
            raise ServiceError("invalid_canceled_state", "canceled build lacks cancellation request")


@dataclass(frozen=True)
class AttemptRecord:
    attempt_id: UUID
    build_id: UUID
    attempt_number: int
    status: AttemptStatus
    worker_id: str
    lease_token_sha256: str
    lease_expires_at: datetime
    heartbeat_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    exit_code: Optional[int]
    reason_code: Optional[str]

    def __post_init__(self) -> None:
        if not isinstance(self.attempt_id, UUID) or not isinstance(self.build_id, UUID):
            raise ServiceError("invalid_attempt_id", "attempt identifier is invalid")
        if isinstance(self.attempt_number, bool) or not isinstance(self.attempt_number, int) or not 1 <= self.attempt_number <= 5:
            raise ServiceError("invalid_attempt_number", "attempt number is outside policy")
        if not isinstance(self.status, AttemptStatus):
            raise ServiceError("invalid_attempt_status", "attempt status is invalid")
        if not isinstance(self.worker_id, str) or WORKER_ID_PATTERN.fullmatch(self.worker_id) is None:
            raise ServiceError("invalid_worker_id", "worker identifier is outside policy")
        require_sha256(self.lease_token_sha256, "lease_token_sha256")
        require_utc(self.lease_expires_at, "lease_expires_at")
        require_utc(self.heartbeat_at, "heartbeat_at")
        for value, label in ((self.started_at, "started_at"), (self.finished_at, "finished_at")):
            if value is not None:
                require_utc(value, label)
        terminal = self.status in (
            AttemptStatus.SUCCEEDED,
            AttemptStatus.FAILED,
            AttemptStatus.NEEDS_REVIEW,
            AttemptStatus.CANCELED,
            AttemptStatus.TIMED_OUT,
            AttemptStatus.LOST,
        )
        if terminal != (self.finished_at is not None):
            raise ServiceError(
                "invalid_attempt_state", "attempt terminal timestamp does not match status"
            )
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int) or not 0 <= self.exit_code <= 255
        ):
            raise ServiceError("invalid_exit_code", "attempt exit code is outside policy")
        require_safe_code(self.reason_code, "reason_code")


@dataclass(frozen=True)
class ArtifactRecord:
    build_id: UUID
    attempt_id: UUID
    relative_path: str
    bucket: str
    object_key: str
    sha256: str
    bytes: int
    content_type: str
    created_at: datetime
    etag: Optional[str] = None
    version_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.build_id, UUID) or not isinstance(self.attempt_id, UUID):
            raise ServiceError("invalid_artifact_owner", "artifact owner is invalid")
        expected_type = ARTIFACT_CONTENT_TYPES.get(self.relative_path)
        if expected_type is None or self.content_type != expected_type:
            raise ServiceError("invalid_artifact", "artifact path or content type is outside policy")
        if not isinstance(self.bucket, str) or not 3 <= len(self.bucket) <= 63:
            raise ServiceError("invalid_artifact", "artifact bucket is outside policy")
        if (
            not isinstance(self.object_key, str)
            or OBJECT_KEY_PATTERN.fullmatch(self.object_key) is None
            or any(part in ("", ".", "..") for part in self.object_key.split("/"))
        ):
            raise ServiceError("invalid_artifact", "artifact object key is outside policy")
        require_sha256(self.sha256, "artifact sha256")
        if isinstance(self.bytes, bool) or not isinstance(self.bytes, int) or not 1 <= self.bytes <= MAX_PUBLISHED_BYTES:
            raise ServiceError("invalid_artifact", "artifact byte count is outside policy")
        require_utc(self.created_at, "created_at")
        for candidate in (self.etag, self.version_id):
            if candidate is not None and (
                not isinstance(candidate, str)
                or not 1 <= len(candidate) <= 256
                or any(ord(character) < 33 or ord(character) > 126 for character in candidate)
            ):
                raise ServiceError("invalid_artifact", "artifact storage identifier is outside policy")


@dataclass(frozen=True)
class BuildEvent:
    build_id: UUID
    sequence: int
    event_type: str
    from_status: Optional[BuildStatus]
    to_status: BuildStatus
    reason_code: Optional[str]
    created_at: datetime
    attempt_id: Optional[UUID] = None

    def __post_init__(self) -> None:
        if not isinstance(self.build_id, UUID) or (
            self.attempt_id is not None and not isinstance(self.attempt_id, UUID)
        ):
            raise ServiceError("invalid_event", "event owner is invalid")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ServiceError("invalid_event", "event sequence is invalid")
        require_safe_code(self.event_type, "event_type", required=True)
        if self.from_status is not None and not isinstance(self.from_status, BuildStatus):
            raise ServiceError("invalid_event", "event source state is invalid")
        if not isinstance(self.to_status, BuildStatus):
            raise ServiceError("invalid_event", "event target state is invalid")
        require_safe_code(self.reason_code, "reason_code")
        require_utc(self.created_at, "created_at")


@dataclass(frozen=True)
class OutboxRecord:
    outbox_id: int
    build_id: UUID
    build_version: int
    available_at: datetime
    dispatched_at: Optional[datetime]
    dispatch_count: int
    last_error_code: Optional[str]

    def __post_init__(self) -> None:
        if isinstance(self.outbox_id, bool) or not isinstance(self.outbox_id, int) or self.outbox_id < 1:
            raise ServiceError("invalid_outbox", "outbox identifier is invalid")
        if not isinstance(self.build_id, UUID):
            raise ServiceError("invalid_outbox", "outbox build identifier is invalid")
        if isinstance(self.build_version, bool) or not isinstance(self.build_version, int) or self.build_version < 0:
            raise ServiceError("invalid_outbox", "outbox build version is invalid")
        require_utc(self.available_at, "available_at")
        if self.dispatched_at is not None:
            require_utc(self.dispatched_at, "dispatched_at")
        if (
            isinstance(self.dispatch_count, bool)
            or not isinstance(self.dispatch_count, int)
            or not 0 <= self.dispatch_count <= MAX_DISPATCH_COUNT
        ):
            raise ServiceError("invalid_outbox", "outbox dispatch count is outside policy")
        require_safe_code(self.last_error_code, "last_error_code")
