"""Concurrency-one queue consumer and fresh-builder lifecycle supervisor."""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence, Tuple
from uuid import UUID

from .artifact_io import records_from_output
from .errors import ServiceError, StateConflict, WorkerError
from .launcher import LaunchResult, LaunchTermination
from .models import AttemptStatus, ArtifactRecord, BuildRecord, BuildStatus
from .queue import BuildQueue, QueueMessage
from .state import AttemptCompletion, AttemptHeartbeat, AttemptLease
from .storage import ArtifactStorage, publication_order
from .structured_log import StructuredLogger


class WorkerRepository(Protocol):
    def recover_expired_attempts(
        self, *, retry_delay_seconds: int = 0, limit: int = 100
    ) -> Tuple[AttemptCompletion, ...]:
        ...

    def dispatch_outbox(
        self, enqueue: object, *, limit: int = 100, retry_delay_seconds: int = 1
    ) -> Tuple[int, int]:
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


class BuilderLauncher(Protocol):
    def execute(
        self,
        request_canonical: bytes,
        attempt_id: UUID,
        heartbeat: object,
    ) -> LaunchResult:
        ...

    def cleanup(self, scratch: object) -> None:
        ...


class _LeaseMonitor:
    def __init__(
        self,
        repository: WorkerRepository,
        attempt_id: UUID,
        lease_token: str,
        lease_seconds: int,
    ) -> None:
        self._repository = repository
        self._attempt_id = attempt_id
        self._lease_token = lease_token
        self._lease_seconds = lease_seconds
        self._interval = max(1.0, min(10.0, lease_seconds / 3.0))
        self._stop = threading.Event()
        self._cancel = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"lease-heartbeat-{attempt_id}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                heartbeat = self._repository.heartbeat_attempt(
                    self._attempt_id,
                    self._lease_token,
                    lease_seconds=self._lease_seconds,
                )
            except Exception:
                self._lost.set()
                return
            if heartbeat.cancel_requested:
                self._cancel.set()

    def probe(self) -> bool:
        if self._lost.is_set():
            raise WorkerError("lease_lost", "worker lease could not be renewed")
        return self._cancel.is_set()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(2.0, self._interval + 1.0))


@dataclass(frozen=True)
class ExitPolicy:
    status: AttemptStatus
    reason_code: str
    retryable: bool


def exit_policy(exit_code: int) -> ExitPolicy:
    if exit_code == 11:
        return ExitPolicy(AttemptStatus.NEEDS_REVIEW, "builder_needs_review", False)
    if exit_code == 124:
        return ExitPolicy(AttemptStatus.TIMED_OUT, "builder_timeout", True)
    if exit_code == 2:
        return ExitPolicy(AttemptStatus.FAILED, "builder_cli_contract", False)
    if exit_code == 3:
        return ExitPolicy(AttemptStatus.FAILED, "builder_invalid_request", False)
    if exit_code == 4:
        return ExitPolicy(AttemptStatus.FAILED, "builder_filesystem", True)
    if exit_code == 10:
        return ExitPolicy(AttemptStatus.FAILED, "blender_failed", True)
    if exit_code == 12:
        return ExitPolicy(AttemptStatus.FAILED, "builder_internal", True)
    if 128 <= exit_code <= 255:
        return ExitPolicy(AttemptStatus.FAILED, "builder_signaled", True)
    return ExitPolicy(AttemptStatus.FAILED, "builder_failed", True)


class WorkerSupervisor:
    """Process at most one queue message and one Blender child at a time."""

    def __init__(
        self,
        *,
        repository: WorkerRepository,
        queue: BuildQueue,
        storage: ArtifactStorage,
        launcher: BuilderLauncher,
        deployment_namespace: str,
        storage_bucket: str,
        worker_id: str,
        lease_seconds: int = 30,
        retry_delay_seconds: int = 1,
        logger: Optional[StructuredLogger] = None,
    ) -> None:
        if not 5 <= lease_seconds <= 300:
            raise WorkerError("lease_duration_invalid", "worker lease duration is outside policy")
        if not 0 <= retry_delay_seconds <= 300:
            raise WorkerError("retry_delay_invalid", "worker retry delay is outside policy")
        self._repository = repository
        self._queue = queue
        self._storage = storage
        self._launcher = launcher
        self._namespace = deployment_namespace
        self._bucket = storage_bucket
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._logger = logger or StructuredLogger()

    def _complete(
        self,
        lease: AttemptLease,
        lease_token: str,
        *,
        status: AttemptStatus,
        exit_code: Optional[int],
        reason_code: str,
        retryable: bool,
    ) -> AttemptCompletion:
        return self._repository.complete_attempt(
            lease.attempt.attempt_id,
            lease_token,
            status=status,
            exit_code=exit_code,
            reason_code=reason_code,
            retryable=retryable,
            retry_delay_seconds=self._retry_delay_seconds,
        )

    def _settle_message(
        self, message: QueueMessage, completion: AttemptCompletion
    ) -> None:
        if completion.requeued or completion.build.status is BuildStatus.CANCELED:
            self._queue.acknowledge(message)
        elif completion.build.status in (
            BuildStatus.FAILED,
            BuildStatus.NEEDS_REVIEW,
        ):
            self._queue.dead_letter(message)
        else:
            self._queue.acknowledge(message)

    def _handle_result(
        self,
        message: QueueMessage,
        lease: AttemptLease,
        lease_token: str,
        monitor: _LeaseMonitor,
        result: LaunchResult,
    ) -> None:
        if result.termination is LaunchTermination.LEASE_LOST:
            self._logger.emit(
                "attempt_lease_lost",
                level="warning",
                build_id=lease.build.build_id,
                attempt_id=lease.attempt.attempt_id,
                worker_id=self._worker_id,
            )
            return
        if result.termination is LaunchTermination.CANCELED:
            completion = self._complete(
                lease,
                lease_token,
                status=AttemptStatus.CANCELED,
                exit_code=result.exit_code,
                reason_code="canceled_by_operator",
                retryable=False,
            )
            self._settle_message(message, completion)
            return
        if result.termination is LaunchTermination.TIMED_OUT:
            completion = self._complete(
                lease,
                lease_token,
                status=AttemptStatus.TIMED_OUT,
                exit_code=124,
                reason_code="builder_timeout",
                retryable=True,
            )
            self._settle_message(message, completion)
            return
        if result.exit_code != 0:
            policy = exit_policy(result.exit_code)
            completion = self._complete(
                lease,
                lease_token,
                status=policy.status,
                exit_code=result.exit_code,
                reason_code=policy.reason_code,
                retryable=policy.retryable,
            )
            self._settle_message(message, completion)
            return

        try:
            records = records_from_output(
                result.output_dir,
                build_id=lease.build.build_id,
                attempt_id=lease.attempt.attempt_id,
                request_sha256=lease.build.request_sha256,
                spec_sha256=lease.build.spec_sha256,
                namespace=self._namespace,
                bucket=self._bucket,
            )
            stored = []
            for record in publication_order(records):
                if monitor.probe():
                    completion = self._complete(
                        lease,
                        lease_token,
                        status=AttemptStatus.CANCELED,
                        exit_code=result.exit_code,
                        reason_code="canceled_by_operator",
                        retryable=False,
                    )
                    self._settle_message(message, completion)
                    return
                stored.append(
                    self._storage.store_file(
                        record,
                        result.output_dir / record.relative_path,
                    )
                )
            if monitor.probe():
                completion = self._complete(
                    lease,
                    lease_token,
                    status=AttemptStatus.CANCELED,
                    exit_code=result.exit_code,
                    reason_code="canceled_by_operator",
                    retryable=False,
                )
                self._settle_message(message, completion)
                return
            succeeded = self._repository.publish_attempt_success(
                lease.attempt.attempt_id,
                lease_token,
                tuple(stored),
            )
        except StateConflict as exc:
            if exc.code in ("lease_expired", "lease_fence_mismatch", "lease_not_active"):
                return
            if exc.code == "cancel_requested":
                completion = self._complete(
                    lease,
                    lease_token,
                    status=AttemptStatus.CANCELED,
                    exit_code=result.exit_code,
                    reason_code="canceled_by_operator",
                    retryable=False,
                )
            else:
                completion = self._complete(
                    lease,
                    lease_token,
                    status=AttemptStatus.FAILED,
                    exit_code=result.exit_code,
                    reason_code="publication_failed",
                    retryable=True,
                )
            self._settle_message(message, completion)
            return
        except ServiceError:
            completion = self._complete(
                lease,
                lease_token,
                status=AttemptStatus.FAILED,
                exit_code=result.exit_code,
                reason_code="artifact_verification_failed",
                retryable=True,
            )
            self._settle_message(message, completion)
            return
        self._queue.acknowledge(message)
        self._logger.emit(
            "build_succeeded",
            build_id=succeeded.build_id,
            attempt_id=lease.attempt.attempt_id,
            worker_id=self._worker_id,
        )

    def process_once(self, *, block_ms: int = 1000) -> bool:
        recovered = self._repository.recover_expired_attempts(
            retry_delay_seconds=self._retry_delay_seconds,
            limit=100,
        )
        for completion in recovered:
            self._logger.emit(
                "attempt_recovered",
                level="warning",
                build_id=completion.build.build_id,
                attempt_id=completion.attempt.attempt_id,
                worker_id=self._worker_id,
                details={"requeued": completion.requeued, "exhausted": completion.exhausted},
            )
        self._repository.dispatch_outbox(
            self._queue.enqueue,
            limit=100,
            retry_delay_seconds=self._retry_delay_seconds,
        )
        message = self._queue.claim(self._worker_id, block_ms=block_ms)
        if message is None:
            return False
        lease_token = secrets.token_urlsafe(32)
        try:
            lease = self._repository.lease_build(
                message.build_id,
                self._worker_id,
                lease_token,
                lease_seconds=self._lease_seconds,
            )
        except StateConflict as exc:
            if exc.code == "build_not_found":
                self._queue.dead_letter(message)
                return True
            raise
        if lease is None:
            self._queue.acknowledge(message)
            return True
        self._logger.emit(
            "attempt_started",
            build_id=lease.build.build_id,
            attempt_id=lease.attempt.attempt_id,
            worker_id=self._worker_id,
            details={"attempt_number": lease.attempt.attempt_number},
        )
        monitor = _LeaseMonitor(
            self._repository,
            lease.attempt.attempt_id,
            lease_token,
            self._lease_seconds,
        )
        monitor.start()
        result: Optional[LaunchResult] = None
        try:
            result = self._launcher.execute(
                lease.build.canonical_request,
                lease.attempt.attempt_id,
                monitor.probe,
            )
            self._handle_result(message, lease, lease_token, monitor, result)
        except Exception:
            self._logger.emit(
                "worker_internal_error",
                level="error",
                build_id=lease.build.build_id,
                attempt_id=lease.attempt.attempt_id,
                worker_id=self._worker_id,
            )
            try:
                completion = self._complete(
                    lease,
                    lease_token,
                    status=AttemptStatus.FAILED,
                    exit_code=None,
                    reason_code="worker_internal",
                    retryable=True,
                )
                self._settle_message(message, completion)
            except ServiceError:
                pass
        finally:
            monitor.stop()
            if result is not None:
                try:
                    self._launcher.cleanup(result.scratch_dir)
                except ServiceError:
                    self._logger.emit(
                        "scratch_cleanup_failed",
                        level="warning",
                        build_id=lease.build.build_id,
                        attempt_id=lease.attempt.attempt_id,
                        worker_id=self._worker_id,
                    )
        return True

    def run_forever(self, stop: threading.Event, *, block_ms: int = 1000) -> None:
        if not isinstance(stop, threading.Event):
            raise WorkerError("stop_signal_invalid", "worker stop signal is invalid")
        while not stop.is_set():
            try:
                self.process_once(block_ms=block_ms)
            except ServiceError as exc:
                self._logger.emit(
                    "worker_dependency_error",
                    level="warning",
                    worker_id=self._worker_id,
                    code=exc.code,
                )
                stop.wait(1)


__all__ = ["ExitPolicy", "WorkerSupervisor", "exit_policy"]
