"""Authoritative build-state interface and thread-safe reference adapter.

The in-memory adapter is deliberately feature-complete enough to define and
unit-test the Postgres contract.  Production durability comes from the schema
and repository added around this interface; Redis is never authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from threading import RLock
from typing import Callable, Dict, Mapping, Optional, Protocol, Sequence, Tuple, Union
from uuid import UUID, uuid4

from shared.character_spec import BuildRequest

from .config import BUCKET_PATTERN, NAMESPACE_PATTERN
from .errors import IdempotencyConflict, StateConflict
from .idempotency import (
    RequestFingerprint,
    digest_idempotency_key,
    require_same_request,
)
from .models import (
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
    utc_now,
)
from .storage import artifact_object_key


@dataclass(frozen=True)
class BuildReservation:
    build: BuildRecord
    created: bool


class BuildStateStore(Protocol):
    def submit(
        self, request: Union[BuildRequest, bytes, str], idempotency_key: Optional[str]
    ) -> BuildReservation:
        ...

    def get_build(self, build_id: UUID) -> BuildRecord:
        ...

    def transition(
        self,
        build_id: UUID,
        expected_version: int,
        target: BuildStatus,
        *,
        reason_code: Optional[str] = None,
    ) -> BuildRecord:
        ...

    def request_cancel(self, build_id: UUID, expected_version: int) -> BuildRecord:
        ...

    def publish_success(
        self,
        build_id: UUID,
        expected_version: int,
        artifacts: Sequence[ArtifactRecord],
    ) -> BuildRecord:
        ...

    def register_running_attempt(self, attempt: AttemptRecord) -> AttemptRecord:
        ...


class InMemoryStateStore:
    """Transactional reference semantics for tests and local diagnostics."""

    def __init__(
        self,
        *,
        idempotency_secret: bytes,
        now: Callable[[], datetime] = utc_now,
        build_id_factory: Callable[[], UUID] = uuid4,
        max_attempts: int = 2,
        deployment_namespace: str = "local",
        storage_bucket: str = "hbcb-artifacts",
    ) -> None:
        if not isinstance(idempotency_secret, bytes) or not 32 <= len(idempotency_secret) <= 128:
            raise StateConflict("invalid_idempotency_secret", "idempotency secret is outside policy")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 5:
            raise StateConflict("invalid_max_attempts", "maximum attempts is outside policy")
        if NAMESPACE_PATTERN.fullmatch(deployment_namespace) is None:
            raise StateConflict("invalid_namespace", "deployment namespace is outside policy")
        if BUCKET_PATTERN.fullmatch(storage_bucket) is None or ".." in storage_bucket:
            raise StateConflict("invalid_bucket", "storage bucket is outside policy")
        self._secret = idempotency_secret
        self._now = now
        self._build_id_factory = build_id_factory
        self._max_attempts = max_attempts
        self._deployment_namespace = deployment_namespace
        self._storage_bucket = storage_bucket
        self._lock = RLock()
        self._builds: Dict[UUID, BuildRecord] = {}
        self._idempotency: Dict[str, Tuple[str, bytes, UUID]] = {}
        self._events: Dict[UUID, list[BuildEvent]] = {}
        self._artifacts: Dict[UUID, Dict[str, ArtifactRecord]] = {}
        self._attempts: Dict[UUID, AttemptRecord] = {}
        self._outbox: Dict[int, OutboxRecord] = {}
        self._next_outbox_id = 1

    def submit(
        self, request: Union[BuildRequest, bytes, str], idempotency_key: Optional[str]
    ) -> BuildReservation:
        fingerprint = RequestFingerprint.from_request(request)
        key_digest = (
            digest_idempotency_key(idempotency_key, self._secret)
            if idempotency_key is not None
            else None
        )
        with self._lock:
            if key_digest is not None and key_digest in self._idempotency:
                request_sha256, canonical_request, build_id = self._idempotency[key_digest]
                require_same_request(request_sha256, fingerprint.request_sha256)
                if canonical_request != fingerprint.canonical_request:
                    raise IdempotencyConflict(
                        "idempotency_conflict",
                        "Idempotency-Key was already used for a different request",
                    )
                return BuildReservation(self._builds[build_id], False)

            build_id = self._build_id_factory()
            if not isinstance(build_id, UUID) or build_id in self._builds:
                raise StateConflict("build_id_collision", "build identifier could not be allocated")
            now = self._now()
            build = BuildRecord(
                build_id=build_id,
                request_sha256=fingerprint.request_sha256,
                spec_sha256=fingerprint.spec_sha256,
                canonical_request=fingerprint.canonical_request,
                status=BuildStatus.QUEUED,
                state_version=1,
                max_attempts=self._max_attempts,
                cancel_requested_at=None,
                terminal_code=None,
                manifest_object_key=None,
                manifest_sha256=None,
                manifest_bytes=None,
                created_at=now,
                updated_at=now,
                finished_at=None,
                published_at=None,
            )
            events = [
                BuildEvent(
                    build_id=build_id,
                    sequence=1,
                    event_type="validated",
                    from_status=None,
                    to_status=BuildStatus.VALIDATING,
                    reason_code=None,
                    created_at=now,
                ),
                BuildEvent(
                    build_id=build_id,
                    sequence=2,
                    event_type="queued",
                    from_status=BuildStatus.VALIDATING,
                    to_status=BuildStatus.QUEUED,
                    reason_code=None,
                    created_at=now,
                ),
            ]
            self._builds[build_id] = build
            self._events[build_id] = events
            if key_digest is not None:
                self._idempotency[key_digest] = (
                    fingerprint.request_sha256,
                    fingerprint.canonical_request,
                    build_id,
                )
            self._append_outbox(build_id, build.state_version, now)
            return BuildReservation(build, True)

    def get_build(self, build_id: UUID) -> BuildRecord:
        with self._lock:
            try:
                return self._builds[build_id]
            except (KeyError, TypeError) as exc:
                raise StateConflict("build_not_found", "build does not exist") from exc

    def events_for(self, build_id: UUID) -> Tuple[BuildEvent, ...]:
        with self._lock:
            if build_id not in self._events:
                raise StateConflict("build_not_found", "build does not exist")
            return tuple(self._events[build_id])

    def artifacts_for(self, build_id: UUID) -> Mapping[str, ArtifactRecord]:
        with self._lock:
            if build_id not in self._builds:
                raise StateConflict("build_not_found", "build does not exist")
            return dict(self._artifacts.get(build_id, {}))

    def register_running_attempt(self, attempt: AttemptRecord) -> AttemptRecord:
        """Record G5 publication evidence; G6 owns lease creation and renewal."""

        if not isinstance(attempt, AttemptRecord) or attempt.status is not AttemptStatus.RUNNING:
            raise StateConflict("invalid_attempt", "publication attempt must be running")
        with self._lock:
            build = self.get_build(attempt.build_id)
            if build.status is not BuildStatus.RUNNING:
                raise StateConflict("invalid_attempt", "build is not running")
            if attempt.attempt_number > build.max_attempts:
                raise StateConflict("invalid_attempt", "attempt exceeds build retry policy")
            if attempt.attempt_id in self._attempts or any(
                existing.build_id == attempt.build_id
                and existing.attempt_number == attempt.attempt_number
                for existing in self._attempts.values()
            ):
                raise StateConflict("attempt_conflict", "attempt already exists")
            if any(
                existing.build_id == attempt.build_id
                and existing.status in (AttemptStatus.LEASED, AttemptStatus.RUNNING)
                for existing in self._attempts.values()
            ):
                raise StateConflict("active_attempt_conflict", "build already has an active attempt")
            self._attempts[attempt.attempt_id] = attempt
            return attempt

    def attempt_for(self, attempt_id: UUID) -> AttemptRecord:
        with self._lock:
            try:
                return self._attempts[attempt_id]
            except (KeyError, TypeError) as exc:
                raise StateConflict("attempt_not_found", "attempt does not exist") from exc

    def pending_outbox(self) -> Tuple[OutboxRecord, ...]:
        with self._lock:
            return tuple(
                item
                for _, item in sorted(self._outbox.items())
                if item.dispatched_at is None
            )

    def mark_outbox_dispatched(self, outbox_id: int) -> OutboxRecord:
        with self._lock:
            try:
                current = self._outbox[outbox_id]
            except (KeyError, TypeError) as exc:
                raise StateConflict("outbox_not_found", "outbox record does not exist") from exc
            if current.dispatched_at is not None:
                return current
            updated = replace(
                current,
                dispatched_at=self._now(),
                dispatch_count=current.dispatch_count + 1,
                last_error_code=None,
            )
            self._outbox[outbox_id] = updated
            return updated

    def mark_outbox_error(self, outbox_id: int, reason_code: str) -> OutboxRecord:
        require_safe_code(reason_code, "reason_code", required=True)
        with self._lock:
            try:
                current = self._outbox[outbox_id]
            except (KeyError, TypeError) as exc:
                raise StateConflict("outbox_not_found", "outbox record does not exist") from exc
            if current.dispatched_at is not None:
                raise StateConflict("outbox_already_dispatched", "outbox record is already dispatched")
            updated = replace(
                current,
                dispatch_count=current.dispatch_count + 1,
                last_error_code=reason_code,
            )
            self._outbox[outbox_id] = updated
            return updated

    def transition(
        self,
        build_id: UUID,
        expected_version: int,
        target: BuildStatus,
        *,
        reason_code: Optional[str] = None,
    ) -> BuildRecord:
        with self._lock:
            current = self.get_build(build_id)
            self._require_version(current, expected_version)
            if target is BuildStatus.SUCCEEDED:
                raise StateConflict("success_requires_artifacts", "success requires immutable artifact evidence")
            require_transition(current.status, target)
            if target in (BuildStatus.FAILED, BuildStatus.NEEDS_REVIEW):
                require_safe_code(reason_code, "reason_code", required=True)
            elif target is BuildStatus.CANCELED:
                if current.cancel_requested_at is None:
                    raise StateConflict("cancel_requires_request", "cancellation was not requested")
                if reason_code not in (None, "canceled_by_operator"):
                    raise StateConflict("invalid_reason_code", "cancellation reason is outside policy")
                reason_code = "canceled_by_operator"
            elif reason_code is not None:
                raise StateConflict("unexpected_reason", "nonterminal transition cannot include a reason")
            now = self._now()
            terminal = target in TERMINAL_BUILD_STATUSES
            updated = replace(
                current,
                status=target,
                state_version=current.state_version + 1,
                terminal_code=reason_code if terminal else None,
                updated_at=now,
                finished_at=now if terminal else None,
            )
            self._builds[build_id] = updated
            self._append_event(current, updated, reason_code)
            if target is BuildStatus.QUEUED:
                self._append_outbox(build_id, updated.state_version, now)
            return updated

    def request_cancel(self, build_id: UUID, expected_version: int) -> BuildRecord:
        with self._lock:
            current = self.get_build(build_id)
            self._require_version(current, expected_version)
            if current.status in TERMINAL_BUILD_STATUSES:
                raise StateConflict("terminal_build", "terminal build cannot be canceled")
            now = self._now()
            immediate = current.status in (BuildStatus.VALIDATING, BuildStatus.QUEUED)
            target = BuildStatus.CANCELED if immediate else current.status
            updated = replace(
                current,
                status=target,
                state_version=current.state_version + 1,
                cancel_requested_at=now,
                terminal_code="canceled_by_operator" if immediate else None,
                updated_at=now,
                finished_at=now if immediate else None,
            )
            self._builds[build_id] = updated
            self._events[build_id].append(
                BuildEvent(
                    build_id=build_id,
                    sequence=len(self._events[build_id]) + 1,
                    event_type="canceled" if immediate else "cancel_requested",
                    from_status=current.status,
                    to_status=target,
                    reason_code="canceled_by_operator",
                    created_at=now,
                )
            )
            return updated

    def publish_success(
        self,
        build_id: UUID,
        expected_version: int,
        artifacts: Sequence[ArtifactRecord],
    ) -> BuildRecord:
        with self._lock:
            current = self.get_build(build_id)
            self._require_version(current, expected_version)
            if current.status not in (BuildStatus.RUNNING, BuildStatus.RENDERING):
                raise StateConflict("invalid_transition", "success cannot be published from current state")
            if current.cancel_requested_at is not None:
                raise StateConflict("cancel_requested", "success cannot race an accepted cancellation")
            records = tuple(artifacts)
            by_name = {record.relative_path: record for record in records}
            if len(records) != len(by_name) or set(by_name) != set(REQUIRED_PUBLISHED_ARTIFACTS):
                raise StateConflict("artifact_set_mismatch", "success requires the exact nine artifacts")
            if any(record.build_id != build_id for record in records):
                raise StateConflict("artifact_owner_mismatch", "artifact owner does not match build")
            attempt_ids = {record.attempt_id for record in records}
            if len(attempt_ids) != 1:
                raise StateConflict("artifact_attempt_mismatch", "artifacts span multiple attempts")
            attempt_id = next(iter(attempt_ids))
            try:
                attempt = self._attempts[attempt_id]
            except KeyError as exc:
                raise StateConflict(
                    "attempt_not_found", "artifact attempt is not recorded"
                ) from exc
            if attempt.build_id != build_id or attempt.status is not AttemptStatus.RUNNING:
                raise StateConflict(
                    "invalid_attempt", "artifact attempt is not eligible for publication"
                )
            if any(record.bucket != self._storage_bucket for record in records):
                raise StateConflict("artifact_bucket_mismatch", "artifact bucket is not canonical")
            if any(not record.version_id for record in records):
                raise StateConflict(
                    "artifact_version_missing", "durable artifact version evidence is required"
                )
            for record in records:
                expected_key = artifact_object_key(
                    self._deployment_namespace,
                    build_id,
                    attempt_id,
                    record.relative_path,
                )
                if record.object_key != expected_key:
                    raise StateConflict(
                        "artifact_key_mismatch", "artifact object key is not canonical"
                    )
            if sum(record.bytes for record in records) > 2 * 1024 * 1024 * 1024:
                raise StateConflict("artifact_budget", "published artifacts exceed the aggregate budget")
            if build_id in self._artifacts:
                raise StateConflict("artifacts_already_published", "build artifacts are immutable")
            manifest = by_name["manifest.json"]
            now = self._now()
            updated = replace(
                current,
                status=BuildStatus.SUCCEEDED,
                state_version=current.state_version + 1,
                terminal_code=None,
                manifest_object_key=manifest.object_key,
                manifest_sha256=manifest.sha256,
                manifest_bytes=manifest.bytes,
                updated_at=now,
                finished_at=now,
                published_at=now,
            )
            self._artifacts[build_id] = by_name
            self._attempts[attempt_id] = replace(
                attempt,
                status=AttemptStatus.SUCCEEDED,
                finished_at=now,
                exit_code=0,
                reason_code=None,
            )
            self._builds[build_id] = updated
            self._events[build_id].append(
                BuildEvent(
                    build_id=build_id,
                    sequence=len(self._events[build_id]) + 1,
                    event_type="succeeded",
                    from_status=current.status,
                    to_status=BuildStatus.SUCCEEDED,
                    reason_code=None,
                    created_at=now,
                    attempt_id=attempt_id,
                )
            )
            return updated

    def _append_event(
        self, current: BuildRecord, updated: BuildRecord, reason_code: Optional[str]
    ) -> None:
        self._events[current.build_id].append(
            BuildEvent(
                build_id=current.build_id,
                sequence=len(self._events[current.build_id]) + 1,
                event_type=updated.status.value,
                from_status=current.status,
                to_status=updated.status,
                reason_code=reason_code,
                created_at=updated.updated_at,
            )
        )

    def _append_outbox(self, build_id: UUID, build_version: int, now: datetime) -> None:
        if any(
            record.build_id == build_id and record.build_version == build_version
            for record in self._outbox.values()
        ):
            raise StateConflict("duplicate_outbox", "queue outbox record already exists")
        outbox_id = self._next_outbox_id
        self._next_outbox_id += 1
        self._outbox[outbox_id] = OutboxRecord(
            outbox_id=outbox_id,
            build_id=build_id,
            build_version=build_version,
            available_at=now,
            dispatched_at=None,
            dispatch_count=0,
            last_error_code=None,
        )

    @staticmethod
    def _require_version(build: BuildRecord, expected_version: int) -> None:
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version != build.state_version
        ):
            raise StateConflict("stale_state_version", "build state was updated concurrently")
