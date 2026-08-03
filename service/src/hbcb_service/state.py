"""Authoritative build-state interface and thread-safe reference adapter.

The in-memory adapter is deliberately feature-complete enough to define and
unit-test the Postgres contract.  Production durability comes from the schema
and repository added around this interface; Redis is never authoritative.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
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
    MAX_DISPATCH_COUNT,
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


LEASE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43,256}$")


def _next_dispatch_count(value: int) -> int:
    return min(value + 1, MAX_DISPATCH_COUNT)


def _lease_digest(lease_token: str) -> str:
    if not isinstance(lease_token, str) or LEASE_TOKEN_PATTERN.fullmatch(lease_token) is None:
        raise StateConflict("invalid_lease_token", "lease token is outside policy")
    return hashlib.sha256(lease_token.encode("ascii")).hexdigest()


def _lease_duration(lease_seconds: int) -> timedelta:
    if (
        isinstance(lease_seconds, bool)
        or not isinstance(lease_seconds, int)
        or not 5 <= lease_seconds <= 300
    ):
        raise StateConflict("invalid_lease_duration", "lease duration is outside policy")
    return timedelta(seconds=lease_seconds)


def _retry_delay(retry_delay_seconds: int) -> timedelta:
    if (
        isinstance(retry_delay_seconds, bool)
        or not isinstance(retry_delay_seconds, int)
        or not 0 <= retry_delay_seconds <= 300
    ):
        raise StateConflict("invalid_retry_delay", "retry delay is outside policy")
    return timedelta(seconds=retry_delay_seconds)


@dataclass(frozen=True)
class BuildReservation:
    build: BuildRecord
    created: bool


@dataclass(frozen=True)
class AttemptLease:
    """One active, fenced worker lease for a logical build."""

    build: BuildRecord
    attempt: AttemptRecord


@dataclass(frozen=True)
class AttemptHeartbeat:
    """Lease-renewal result returned to the worker supervisor."""

    build_id: UUID
    attempt_id: UUID
    lease_expires_at: datetime
    cancel_requested: bool


@dataclass(frozen=True)
class AttemptCompletion:
    """Atomic attempt/build completion result."""

    build: BuildRecord
    attempt: AttemptRecord
    requeued: bool
    exhausted: bool


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

    def lease_build(
        self,
        build_id: UUID,
        worker_id: str,
        lease_token: str,
        *,
        lease_seconds: int,
    ) -> Optional[AttemptLease]:
        ...

    def heartbeat_attempt(
        self,
        attempt_id: UUID,
        lease_token: str,
        *,
        lease_seconds: int,
    ) -> AttemptHeartbeat:
        ...

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
        ...

    def publish_attempt_success(
        self,
        attempt_id: UUID,
        lease_token: str,
        artifacts: Sequence[ArtifactRecord],
    ) -> BuildRecord:
        ...

    def recover_expired_attempts(
        self, *, retry_delay_seconds: int = 0, limit: int = 100
    ) -> Tuple[AttemptCompletion, ...]:
        ...


class InMemoryStateStore:
    """Transactional reference semantics for tests and local diagnostics."""

    def __init__(
        self,
        *,
        idempotency_secret: bytes,
        now: Callable[[], datetime] = utc_now,
        build_id_factory: Callable[[], UUID] = uuid4,
        attempt_id_factory: Callable[[], UUID] = uuid4,
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
        self._attempt_id_factory = attempt_id_factory
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

    def attempts_for(self, build_id: UUID) -> Tuple[AttemptRecord, ...]:
        with self._lock:
            if build_id not in self._builds:
                raise StateConflict("build_not_found", "build does not exist")
            return tuple(
                sorted(
                    (
                        attempt
                        for attempt in self._attempts.values()
                        if attempt.build_id == build_id
                    ),
                    key=lambda attempt: attempt.attempt_number,
                )
            )

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
        with self._lock:
            build = self.get_build(build_id)
            if build.status is not BuildStatus.QUEUED:
                return None
            existing = tuple(
                attempt
                for attempt in self._attempts.values()
                if attempt.build_id == build_id
            )
            if any(
                attempt.status in (AttemptStatus.LEASED, AttemptStatus.RUNNING)
                for attempt in existing
            ):
                raise StateConflict("active_attempt_conflict", "build already has an active attempt")
            attempt_number = max(
                (attempt.attempt_number for attempt in existing), default=0
            ) + 1
            if attempt_number > build.max_attempts:
                raise StateConflict("retry_policy_exhausted", "build has no attempts remaining")
            attempt_id = self._attempt_id_factory()
            if not isinstance(attempt_id, UUID) or attempt_id in self._attempts:
                raise StateConflict("attempt_id_collision", "attempt identifier could not be allocated")
            now = self._now()
            attempt = AttemptRecord(
                attempt_id=attempt_id,
                build_id=build_id,
                attempt_number=attempt_number,
                status=AttemptStatus.RUNNING,
                worker_id=worker_id,
                lease_token_sha256=token_sha256,
                lease_expires_at=now + duration,
                heartbeat_at=now,
                started_at=now,
                finished_at=None,
                exit_code=None,
                reason_code=None,
            )
            updated = replace(
                build,
                status=BuildStatus.RUNNING,
                state_version=build.state_version + 1,
                updated_at=now,
            )
            self._attempts[attempt_id] = attempt
            self._builds[build_id] = updated
            self._events[build_id].append(
                BuildEvent(
                    build_id=build_id,
                    sequence=len(self._events[build_id]) + 1,
                    event_type="attempt_started",
                    from_status=BuildStatus.QUEUED,
                    to_status=BuildStatus.RUNNING,
                    reason_code=None,
                    created_at=now,
                    attempt_id=attempt_id,
                )
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
        with self._lock:
            attempt = self.attempt_for(attempt_id)
            if attempt.status not in (AttemptStatus.LEASED, AttemptStatus.RUNNING):
                raise StateConflict("lease_not_active", "attempt lease is no longer active")
            if not hmac.compare_digest(attempt.lease_token_sha256, token_sha256):
                raise StateConflict("lease_fence_mismatch", "attempt lease fence does not match")
            now = self._now()
            if attempt.lease_expires_at <= now:
                raise StateConflict("lease_expired", "attempt lease has expired")
            updated = replace(
                attempt,
                heartbeat_at=now,
                lease_expires_at=now + duration,
            )
            self._attempts[attempt_id] = updated
            build = self.get_build(attempt.build_id)
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
        require_safe_code(reason_code, "reason_code", required=True)
        with self._lock:
            attempt = self.attempt_for(attempt_id)
            if attempt.status not in (AttemptStatus.LEASED, AttemptStatus.RUNNING):
                raise StateConflict("lease_not_active", "attempt lease is no longer active")
            if not hmac.compare_digest(attempt.lease_token_sha256, token_sha256):
                raise StateConflict("lease_fence_mismatch", "attempt lease fence does not match")
            now = self._now()
            if attempt.lease_expires_at <= now:
                raise StateConflict("lease_expired", "attempt lease has expired")
            build = self.get_build(attempt.build_id)
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
                and bool(retryable)
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
            updated_attempt = replace(
                attempt,
                status=final_attempt_status,
                finished_at=now,
                exit_code=exit_code,
                reason_code=final_reason,
            )
            updated_build = replace(
                build,
                status=target,
                state_version=build.state_version + 1,
                terminal_code=final_reason if terminal else None,
                updated_at=now,
                finished_at=now if terminal else None,
            )
            self._attempts[attempt_id] = updated_attempt
            self._builds[build.build_id] = updated_build
            self._events[build.build_id].append(
                BuildEvent(
                    build_id=build.build_id,
                    sequence=len(self._events[build.build_id]) + 1,
                    event_type="retry_queued" if can_retry else target.value,
                    from_status=BuildStatus.RUNNING,
                    to_status=target,
                    reason_code=final_reason,
                    created_at=now,
                    attempt_id=attempt_id,
                )
            )
            if can_retry:
                self._append_outbox(
                    build.build_id,
                    updated_build.state_version,
                    now + delay,
                )
            return AttemptCompletion(
                build=updated_build,
                attempt=updated_attempt,
                requeued=can_retry,
                exhausted=(
                    not can_retry
                    and bool(retryable)
                    and not cancel_wins
                    and status in (AttemptStatus.FAILED, AttemptStatus.TIMED_OUT)
                ),
            )

    def publish_attempt_success(
        self,
        attempt_id: UUID,
        lease_token: str,
        artifacts: Sequence[ArtifactRecord],
    ) -> BuildRecord:
        token_sha256 = _lease_digest(lease_token)
        with self._lock:
            attempt = self.attempt_for(attempt_id)
            if attempt.status is not AttemptStatus.RUNNING:
                raise StateConflict("lease_not_active", "attempt lease is no longer active")
            if not hmac.compare_digest(attempt.lease_token_sha256, token_sha256):
                raise StateConflict("lease_fence_mismatch", "attempt lease fence does not match")
            if attempt.lease_expires_at <= self._now():
                raise StateConflict("lease_expired", "attempt lease has expired")
            build = self.get_build(attempt.build_id)
            return self.publish_success(
                build.build_id,
                build.state_version,
                artifacts,
            )

    def recover_expired_attempts(
        self, *, retry_delay_seconds: int = 0, limit: int = 100
    ) -> Tuple[AttemptCompletion, ...]:
        delay = _retry_delay(retry_delay_seconds)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise StateConflict("invalid_recovery_limit", "recovery limit is outside policy")
        with self._lock:
            now = self._now()
            candidates = sorted(
                (
                    attempt
                    for attempt in self._attempts.values()
                    if attempt.status in (AttemptStatus.LEASED, AttemptStatus.RUNNING)
                    and attempt.lease_expires_at <= now
                ),
                key=lambda attempt: (attempt.lease_expires_at, attempt.attempt_number),
            )[:limit]
            results = []
            for attempt in candidates:
                build = self.get_build(attempt.build_id)
                cancel_wins = build.cancel_requested_at is not None
                can_retry = (
                    build.status is BuildStatus.RUNNING
                    and not cancel_wins
                    and attempt.attempt_number < build.max_attempts
                )
                if build.status is not BuildStatus.RUNNING:
                    target = build.status
                elif cancel_wins:
                    target = BuildStatus.CANCELED
                elif can_retry:
                    target = BuildStatus.QUEUED
                else:
                    target = BuildStatus.FAILED
                reason = "canceled_by_operator" if cancel_wins else "worker_lost"
                updated_attempt = replace(
                    attempt,
                    status=AttemptStatus.CANCELED if cancel_wins else AttemptStatus.LOST,
                    finished_at=now,
                    reason_code=reason,
                )
                if target is build.status:
                    updated_build = build
                else:
                    terminal = target in TERMINAL_BUILD_STATUSES
                    updated_build = replace(
                        build,
                        status=target,
                        state_version=build.state_version + 1,
                        terminal_code=reason if terminal else None,
                        updated_at=now,
                        finished_at=now if terminal else None,
                    )
                    self._builds[build.build_id] = updated_build
                    self._events[build.build_id].append(
                        BuildEvent(
                            build_id=build.build_id,
                            sequence=len(self._events[build.build_id]) + 1,
                            event_type="retry_queued" if can_retry else target.value,
                            from_status=BuildStatus.RUNNING,
                            to_status=target,
                            reason_code=reason,
                            created_at=now,
                            attempt_id=attempt.attempt_id,
                        )
                    )
                    if can_retry:
                        self._append_outbox(
                            build.build_id,
                            updated_build.state_version,
                            now + delay,
                        )
                self._attempts[attempt.attempt_id] = updated_attempt
                results.append(
                    AttemptCompletion(
                        build=updated_build,
                        attempt=updated_attempt,
                        requeued=can_retry,
                        exhausted=(
                            build.status is BuildStatus.RUNNING
                            and not can_retry
                            and not cancel_wins
                        ),
                    )
                )
            return tuple(results)

    def ping(self) -> bool:
        return True

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
                dispatch_count=_next_dispatch_count(current.dispatch_count),
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
                dispatch_count=_next_dispatch_count(current.dispatch_count),
                last_error_code=reason_code,
            )
            self._outbox[outbox_id] = updated
            return updated

    def dispatch_outbox(
        self,
        enqueue: Callable[[UUID], str],
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
        with self._lock:
            now = self._now()
            candidates = [
                item
                for _, item in sorted(self._outbox.items())
                if item.dispatched_at is None and item.available_at <= now
            ][:limit]
            for item in candidates:
                build = self.get_build(item.build_id)
                if build.status is not BuildStatus.QUEUED:
                    self._outbox[item.outbox_id] = replace(
                        item,
                        dispatched_at=now,
                        dispatch_count=_next_dispatch_count(item.dispatch_count),
                        last_error_code=None,
                    )
                    dispatched += 1
                    continue
                try:
                    enqueue(item.build_id)
                except Exception:
                    self._outbox[item.outbox_id] = replace(
                        item,
                        available_at=now + delay,
                        dispatch_count=_next_dispatch_count(item.dispatch_count),
                        last_error_code="redis_unavailable",
                    )
                    failed += 1
                    continue
                self._outbox[item.outbox_id] = replace(
                    item,
                    dispatched_at=now,
                    dispatch_count=_next_dispatch_count(item.dispatch_count),
                    last_error_code=None,
                )
                dispatched += 1
        return dispatched, failed

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
            if current.cancel_requested_at is not None:
                return current
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
