from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from uuid import UUID

from hbcb_service.errors import StateConflict
from hbcb_service.models import AttemptStatus, BuildStatus
from hbcb_service.repository import PostgresRepository
from hbcb_service.state import InMemoryStateStore

try:
    from .g6_support import facet_request_bytes
except ImportError:
    from g6_support import facet_request_bytes


BUILD_ID = UUID("11111111-1111-4111-8111-111111111111")
ATTEMPT_IDS = (
    UUID("22222222-2222-4222-8222-222222222222"),
    UUID("33333333-3333-4333-8333-333333333333"),
)
TOKEN_ONE = "a" * 43
TOKEN_TWO = "b" * 43


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def lifecycle_store(clock: MutableClock, *, max_attempts: int = 2) -> InMemoryStateStore:
    identifiers = iter(ATTEMPT_IDS)
    return InMemoryStateStore(
        idempotency_secret=b"s" * 32,
        now=clock,
        build_id_factory=lambda: BUILD_ID,
        attempt_id_factory=lambda: next(identifiers),
        max_attempts=max_attempts,
    )


class LeaseAndHeartbeatTests(unittest.TestCase):
    def test_lease_is_fenced_and_heartbeat_extends_it(self) -> None:
        clock = MutableClock()
        store = lifecycle_store(clock)
        store.submit(facet_request_bytes(), "facet-request-0001")
        lease = store.lease_build(
            BUILD_ID,
            "worker-1",
            TOKEN_ONE,
            lease_seconds=30,
        )
        self.assertIsNotNone(lease)
        assert lease is not None
        self.assertEqual(lease.build.status, BuildStatus.RUNNING)
        self.assertEqual(lease.attempt.status, AttemptStatus.RUNNING)
        self.assertNotEqual(lease.attempt.lease_token_sha256, TOKEN_ONE)

        clock.advance(10)
        heartbeat = store.heartbeat_attempt(
            lease.attempt.attempt_id,
            TOKEN_ONE,
            lease_seconds=30,
        )
        self.assertEqual(heartbeat.lease_expires_at, clock.value + timedelta(seconds=30))
        self.assertFalse(heartbeat.cancel_requested)
        with self.assertRaises(StateConflict) as wrong_fence:
            store.heartbeat_attempt(
                lease.attempt.attempt_id,
                TOKEN_TWO,
                lease_seconds=30,
            )
        self.assertEqual(wrong_fence.exception.code, "lease_fence_mismatch")

    def test_duplicate_delivery_cannot_create_a_second_active_attempt(self) -> None:
        clock = MutableClock()
        store = lifecycle_store(clock)
        store.submit(facet_request_bytes(), "facet-request-0001")
        first = store.lease_build(BUILD_ID, "worker-1", TOKEN_ONE, lease_seconds=30)
        duplicate = store.lease_build(BUILD_ID, "worker-2", TOKEN_TWO, lease_seconds=30)
        self.assertIsNotNone(first)
        self.assertIsNone(duplicate)
        self.assertEqual(len(store.attempts_for(BUILD_ID)), 1)


class RetryCancelTimeoutAndRecoveryTests(unittest.TestCase):
    def test_invalid_retry_flags_are_rejected_without_mutation_by_both_adapters(self) -> None:
        clock = MutableClock()
        store = lifecycle_store(clock)
        store.submit(facet_request_bytes(), "facet-request-0001")
        lease = store.lease_build(BUILD_ID, "worker-1", TOKEN_ONE, lease_seconds=30)
        self.assertIsNotNone(lease)
        connect = mock.Mock(side_effect=AssertionError("invalid input reached PostgreSQL"))
        postgres = PostgresRepository(
            connect,
            deployment_namespace="local",
            idempotency_secret=b"s" * 32,
            storage_bucket="hbcb-artifacts",
        )
        before = (
            store.get_build(BUILD_ID), store.attempts_for(BUILD_ID),
            store.events_for(BUILD_ID), store.pending_outbox(),
        )
        for adapter in (store, postgres):
            for retryable in (1, 0, None, "false", "true", [], {}):
                with self.subTest(adapter=type(adapter).__name__, retryable=retryable):
                    with self.assertRaises(StateConflict) as captured:
                        adapter.complete_attempt(
                            lease.attempt.attempt_id,
                            TOKEN_ONE,
                            status=AttemptStatus.FAILED,
                            exit_code=10,
                            reason_code="blender_failed",
                            retryable=retryable,
                        )
                    self.assertEqual(captured.exception.code, "invalid_retry_policy")
        connect.assert_not_called()
        self.assertEqual(before, (
            store.get_build(BUILD_ID), store.attempts_for(BUILD_ID),
            store.events_for(BUILD_ID), store.pending_outbox(),
        ))

    def test_boolean_retry_flags_select_retry_or_terminal_failure(self) -> None:
        for retryable in (True, False):
            with self.subTest(retryable=retryable):
                store = lifecycle_store(MutableClock())
                store.submit(facet_request_bytes(), "facet-request-0001")
                lease = store.lease_build(BUILD_ID, "worker-1", TOKEN_ONE, lease_seconds=30)
                completion = store.complete_attempt(
                    lease.attempt.attempt_id, TOKEN_ONE,
                    status=AttemptStatus.FAILED, exit_code=10,
                    reason_code="blender_failed", retryable=retryable,
                )
                self.assertEqual(completion.requeued, retryable)
                self.assertEqual(
                    completion.build.status,
                    BuildStatus.QUEUED if retryable else BuildStatus.FAILED,
                )

    def test_retry_then_exhaustion_is_durable_and_dead_letter_eligible(self) -> None:
        clock = MutableClock()
        store = lifecycle_store(clock, max_attempts=2)
        store.submit(facet_request_bytes(), "facet-request-0001")
        first = store.lease_build(BUILD_ID, "worker-1", TOKEN_ONE, lease_seconds=30)
        assert first is not None
        retried = store.complete_attempt(
            first.attempt.attempt_id,
            TOKEN_ONE,
            status=AttemptStatus.FAILED,
            exit_code=10,
            reason_code="blender_failed",
            retryable=True,
            retry_delay_seconds=0,
        )
        self.assertTrue(retried.requeued)
        self.assertFalse(retried.exhausted)
        self.assertEqual(retried.build.status, BuildStatus.QUEUED)
        self.assertEqual([item.build_version for item in store.pending_outbox()], [1, 3])

        second = store.lease_build(BUILD_ID, "worker-1", TOKEN_TWO, lease_seconds=30)
        assert second is not None
        exhausted = store.complete_attempt(
            second.attempt.attempt_id,
            TOKEN_TWO,
            status=AttemptStatus.FAILED,
            exit_code=10,
            reason_code="blender_failed",
            retryable=True,
        )
        self.assertFalse(exhausted.requeued)
        self.assertTrue(exhausted.exhausted)
        self.assertEqual(exhausted.build.status, BuildStatus.FAILED)

    def test_accepted_cancellation_wins_over_retryable_failure(self) -> None:
        clock = MutableClock()
        store = lifecycle_store(clock)
        queued = store.submit(facet_request_bytes(), "facet-request-0001").build
        lease = store.lease_build(BUILD_ID, "worker-1", TOKEN_ONE, lease_seconds=30)
        assert lease is not None
        requested = store.request_cancel(BUILD_ID, lease.build.state_version)
        self.assertEqual(requested.status, BuildStatus.RUNNING)
        heartbeat = store.heartbeat_attempt(
            lease.attempt.attempt_id,
            TOKEN_ONE,
            lease_seconds=30,
        )
        self.assertTrue(heartbeat.cancel_requested)
        completion = store.complete_attempt(
            lease.attempt.attempt_id,
            TOKEN_ONE,
            status=AttemptStatus.FAILED,
            exit_code=10,
            reason_code="blender_failed",
            retryable=True,
        )
        self.assertEqual(completion.attempt.status, AttemptStatus.CANCELED)
        self.assertEqual(completion.build.status, BuildStatus.CANCELED)
        self.assertFalse(completion.requeued)

    def test_timeout_retries_once_then_fails(self) -> None:
        clock = MutableClock()
        store = lifecycle_store(clock, max_attempts=1)
        store.submit(facet_request_bytes(), "facet-request-0001")
        lease = store.lease_build(BUILD_ID, "worker-1", TOKEN_ONE, lease_seconds=30)
        assert lease is not None
        completion = store.complete_attempt(
            lease.attempt.attempt_id,
            TOKEN_ONE,
            status=AttemptStatus.TIMED_OUT,
            exit_code=124,
            reason_code="builder_timeout",
            retryable=True,
        )
        self.assertTrue(completion.exhausted)
        self.assertEqual(completion.attempt.status, AttemptStatus.TIMED_OUT)
        self.assertEqual(completion.build.status, BuildStatus.FAILED)

    def test_expired_lease_is_marked_lost_and_requeued(self) -> None:
        clock = MutableClock()
        store = lifecycle_store(clock, max_attempts=2)
        store.submit(facet_request_bytes(), "facet-request-0001")
        lease = store.lease_build(BUILD_ID, "worker-1", TOKEN_ONE, lease_seconds=5)
        assert lease is not None
        clock.advance(6)
        recovered = store.recover_expired_attempts(retry_delay_seconds=0)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].attempt.status, AttemptStatus.LOST)
        self.assertEqual(recovered[0].build.status, BuildStatus.QUEUED)
        self.assertTrue(recovered[0].requeued)
        with self.assertRaises(StateConflict):
            store.heartbeat_attempt(
                lease.attempt.attempt_id,
                TOKEN_ONE,
                lease_seconds=5,
            )


if __name__ == "__main__":
    unittest.main()
