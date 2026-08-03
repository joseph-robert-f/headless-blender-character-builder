from __future__ import annotations

import concurrent.futures
import unittest
from dataclasses import replace
from uuid import uuid4

from hbcb_service.errors import IdempotencyConflict, ServiceError, StateConflict
from hbcb_service.models import (
    MAX_PUBLISHED_BYTES,
    AttemptRecord,
    AttemptStatus,
    BuildStatus,
)
from hbcb_service.state import InMemoryStateStore

try:
    from .support import (
        BUILD_ID,
        FIXED_NOW,
        artifact_records,
        facet_request_bytes,
        moss_request_bytes,
        running_attempt,
    )
except ImportError:  # Direct ``unittest -s tests/service_unit`` discovery.
    from support import (
        BUILD_ID,
        FIXED_NOW,
        artifact_records,
        facet_request_bytes,
        moss_request_bytes,
        running_attempt,
    )


def fixed_store(*, fixed_id: bool = True) -> InMemoryStateStore:
    arguments = {
        "idempotency_secret": b"s" * 32,
        "now": lambda: FIXED_NOW,
    }
    if fixed_id:
        arguments["build_id_factory"] = lambda: BUILD_ID
    return InMemoryStateStore(**arguments)


class SubmissionAndIdempotencyTests(unittest.TestCase):
    def test_submit_atomically_creates_queued_build_events_and_outbox(self) -> None:
        store = fixed_store()
        reservation = store.submit(facet_request_bytes(), "facet-request-0001")
        self.assertTrue(reservation.created)
        self.assertEqual(reservation.build.status, BuildStatus.QUEUED)
        self.assertEqual(reservation.build.state_version, 1)
        self.assertEqual(
            [event.to_status for event in store.events_for(BUILD_ID)],
            [BuildStatus.VALIDATING, BuildStatus.QUEUED],
        )
        outbox = store.pending_outbox()
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0].build_id, BUILD_ID)
        self.assertEqual(outbox[0].build_version, 1)

    def test_build_record_rejects_canonical_bytes_that_do_not_match_digest(self) -> None:
        store = fixed_store()
        build = store.submit(facet_request_bytes(), "facet-request-0001").build
        with self.assertRaises(ServiceError) as captured:
            replace(build, request_sha256="f" * 64)
        self.assertEqual(captured.exception.code, "invalid_request_hash")
        with self.assertRaises(ServiceError) as spec_captured:
            replace(build, spec_sha256="f" * 64)
        self.assertEqual(spec_captured.exception.code, "invalid_spec_hash")

    def test_same_key_and_request_returns_original_without_new_outbox(self) -> None:
        store = fixed_store()
        first = store.submit(facet_request_bytes(), "facet-request-0001")
        second = store.submit(facet_request_bytes(), "facet-request-0001")
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.build, second.build)
        self.assertEqual(len(store.pending_outbox()), 1)


class DomainModelInvariantTests(unittest.TestCase):
    def test_build_terminal_reason_matches_database_contract(self) -> None:
        build = fixed_store().submit(facet_request_bytes(), "facet-request-0001").build
        with self.assertRaises(ServiceError) as captured:
            replace(
                build,
                status=BuildStatus.FAILED,
                finished_at=FIXED_NOW,
                terminal_code=None,
            )
        self.assertEqual(captured.exception.code, "invalid_terminal_state")

    def test_attempt_terminal_timestamp_matches_database_contract(self) -> None:
        common = {
            "attempt_id": uuid4(),
            "build_id": BUILD_ID,
            "attempt_number": 1,
            "worker_id": "worker-1",
            "lease_token_sha256": "a" * 64,
            "lease_expires_at": FIXED_NOW,
            "heartbeat_at": FIXED_NOW,
            "started_at": FIXED_NOW,
            "exit_code": 0,
            "reason_code": None,
        }
        with self.assertRaises(ServiceError) as missing:
            AttemptRecord(status=AttemptStatus.SUCCEEDED, finished_at=None, **common)
        self.assertEqual(missing.exception.code, "invalid_attempt_state")
        with self.assertRaises(ServiceError) as unexpected:
            AttemptRecord(status=AttemptStatus.RUNNING, finished_at=FIXED_NOW, **common)
        self.assertEqual(unexpected.exception.code, "invalid_attempt_state")

    def test_success_manifest_size_obeys_aggregate_artifact_budget(self) -> None:
        store = fixed_store()
        queued = store.submit(facet_request_bytes(), "facet-request-0001").build
        running = store.transition(BUILD_ID, queued.state_version, BuildStatus.RUNNING)
        store.register_running_attempt(running_attempt())
        succeeded = store.publish_success(
            BUILD_ID, running.state_version, artifact_records()
        )
        with self.assertRaises(ServiceError) as captured:
            replace(succeeded, manifest_bytes=MAX_PUBLISHED_BYTES + 1)
        self.assertEqual(captured.exception.code, "invalid_success_state")


class SubmissionAndIdempotencyContinuationTests(unittest.TestCase):
    def test_same_key_different_request_conflicts_without_orphan(self) -> None:
        store = fixed_store()
        store.submit(facet_request_bytes(), "facet-request-0001")
        with self.assertRaises(IdempotencyConflict):
            store.submit(moss_request_bytes(), "facet-request-0001")
        self.assertEqual(len(store.pending_outbox()), 1)
        self.assertEqual(len(store.events_for(BUILD_ID)), 2)

    def test_no_key_always_creates_a_distinct_build(self) -> None:
        store = fixed_store(fixed_id=False)
        first = store.submit(facet_request_bytes(), None)
        second = store.submit(facet_request_bytes(), None)
        self.assertNotEqual(first.build.build_id, second.build.build_id)
        self.assertEqual(len(store.pending_outbox()), 2)

    def test_concurrent_replay_creates_exactly_one_build_and_outbox(self) -> None:
        store = fixed_store(fixed_id=False)

        def submit() -> object:
            return store.submit(facet_request_bytes(), "concurrent-request-1")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _index: submit(), range(32)))
        self.assertEqual(sum(result.created for result in results), 1)
        self.assertEqual(len({result.build.build_id for result in results}), 1)
        self.assertEqual(len(store.pending_outbox()), 1)


class StateTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = fixed_store()
        self.build = self.store.submit(facet_request_bytes(), "facet-request-0001").build

    def test_optimistic_version_and_transition_allowlist(self) -> None:
        running = self.store.transition(
            BUILD_ID, self.build.state_version, BuildStatus.RUNNING
        )
        self.assertEqual(running.state_version, 2)
        with self.assertRaises(StateConflict) as stale:
            self.store.transition(BUILD_ID, 1, BuildStatus.GEOMETRY_QA)
        self.assertEqual(stale.exception.code, "stale_state_version")
        with self.assertRaises(StateConflict):
            self.store.transition(BUILD_ID, 2, BuildStatus.RENDERING)
        qa = self.store.transition(BUILD_ID, 2, BuildStatus.GEOMETRY_QA)
        rendering = self.store.transition(BUILD_ID, qa.state_version, BuildStatus.RENDERING)
        self.assertEqual(rendering.status, BuildStatus.RENDERING)

    def test_retry_returns_to_queue_with_one_new_outbox(self) -> None:
        running = self.store.transition(BUILD_ID, 1, BuildStatus.RUNNING)
        queued = self.store.transition(BUILD_ID, running.state_version, BuildStatus.QUEUED)
        self.assertEqual(queued.status, BuildStatus.QUEUED)
        self.assertEqual([item.build_version for item in self.store.pending_outbox()], [1, 3])

    def test_failure_and_needs_review_require_safe_reason_and_are_terminal(self) -> None:
        running = self.store.transition(BUILD_ID, 1, BuildStatus.RUNNING)
        with self.assertRaises(ServiceError):
            self.store.transition(BUILD_ID, running.state_version, BuildStatus.FAILED)
        reviewed = self.store.transition(
            BUILD_ID,
            running.state_version,
            BuildStatus.NEEDS_REVIEW,
            reason_code="mandatory_qa_unknown",
        )
        self.assertIsNotNone(reviewed.finished_at)
        with self.assertRaises(StateConflict):
            self.store.transition(BUILD_ID, reviewed.state_version, BuildStatus.QUEUED)

    def test_queued_cancellation_is_immediate_and_terminal(self) -> None:
        canceled = self.store.request_cancel(BUILD_ID, self.build.state_version)
        self.assertEqual(canceled.status, BuildStatus.CANCELED)
        self.assertEqual(canceled.terminal_code, "canceled_by_operator")
        with self.assertRaises(StateConflict):
            self.store.request_cancel(BUILD_ID, canceled.state_version)

    def test_running_cancellation_blocks_success_then_completes(self) -> None:
        running = self.store.transition(BUILD_ID, 1, BuildStatus.RUNNING)
        requested = self.store.request_cancel(BUILD_ID, running.state_version)
        self.assertEqual(requested.status, BuildStatus.RUNNING)
        with self.assertRaises(StateConflict) as conflict:
            self.store.publish_success(
                BUILD_ID, requested.state_version, artifact_records()
            )
        self.assertEqual(conflict.exception.code, "cancel_requested")
        canceled = self.store.transition(
            BUILD_ID, requested.state_version, BuildStatus.CANCELED
        )
        self.assertEqual(canceled.status, BuildStatus.CANCELED)

    def test_success_requires_exact_immutable_artifacts_and_allows_opaque_runner(self) -> None:
        running = self.store.transition(BUILD_ID, 1, BuildStatus.RUNNING)
        with self.assertRaises(StateConflict):
            self.store.transition(BUILD_ID, running.state_version, BuildStatus.SUCCEEDED)
        with self.assertRaises(StateConflict):
            self.store.publish_success(
                BUILD_ID, running.state_version, artifact_records()[:-1]
            )
        with self.assertRaises(StateConflict) as missing_attempt:
            self.store.publish_success(
                BUILD_ID, running.state_version, artifact_records()
            )
        self.assertEqual(missing_attempt.exception.code, "attempt_not_found")
        self.store.register_running_attempt(running_attempt())
        forged = tuple(
            replace(record, object_key="evil/" + record.relative_path)
            for record in artifact_records()
        )
        with self.assertRaises(StateConflict) as forged_key:
            self.store.publish_success(BUILD_ID, running.state_version, forged)
        self.assertEqual(forged_key.exception.code, "artifact_key_mismatch")
        versionless = tuple(
            replace(record, version_id=None) for record in artifact_records()
        )
        with self.assertRaises(StateConflict) as missing_version:
            self.store.publish_success(BUILD_ID, running.state_version, versionless)
        self.assertEqual(missing_version.exception.code, "artifact_version_missing")
        succeeded = self.store.publish_success(
            BUILD_ID, running.state_version, artifact_records()
        )
        self.assertEqual(succeeded.status, BuildStatus.SUCCEEDED)
        self.assertEqual(len(self.store.artifacts_for(BUILD_ID)), 9)
        self.assertIsNotNone(succeeded.manifest_sha256)
        self.assertEqual(
            self.store.attempt_for(running_attempt().attempt_id).status,
            AttemptStatus.SUCCEEDED,
        )
        with self.assertRaises(StateConflict):
            self.store.publish_success(
                BUILD_ID, succeeded.state_version, artifact_records()
            )


class OutboxTests(unittest.TestCase):
    def test_dispatch_success_is_idempotent_and_error_is_bounded(self) -> None:
        store = fixed_store()
        store.submit(facet_request_bytes(), "facet-request-0001")
        outbox = store.pending_outbox()[0]
        failed = store.mark_outbox_error(outbox.outbox_id, "redis_unavailable")
        self.assertEqual(failed.dispatch_count, 1)
        dispatched = store.mark_outbox_dispatched(outbox.outbox_id)
        self.assertEqual(dispatched.dispatch_count, 2)
        self.assertEqual(store.pending_outbox(), ())
        self.assertEqual(store.mark_outbox_dispatched(outbox.outbox_id), dispatched)
        with self.assertRaises(StateConflict):
            store.mark_outbox_error(outbox.outbox_id, "another_error")

    def test_dispatch_recovers_after_more_than_one_hundred_queue_failures(self) -> None:
        store = fixed_store()
        build_id = store.submit(
            facet_request_bytes(), "facet-request-0001"
        ).build.build_id

        def unavailable(_build_id: UUID) -> str:
            raise RuntimeError("synthetic Redis outage")

        for _attempt in range(101):
            self.assertEqual(
                store.dispatch_outbox(unavailable, retry_delay_seconds=0),
                (0, 1),
            )
        pending = store.pending_outbox()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].dispatch_count, 101)
        self.assertEqual(
            store.dispatch_outbox(lambda _build_id: "1-0", retry_delay_seconds=0),
            (1, 0),
        )
        self.assertEqual(store.pending_outbox(), ())
        self.assertEqual(store.get_build(build_id).status, BuildStatus.QUEUED)
