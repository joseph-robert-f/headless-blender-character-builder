"""Replaceable queue contract and Redis Streams adapter.

Postgres plus its transactional outbox is authoritative.  Redis contains only
opaque build UUIDs and provides at-least-once wake-up/coordination semantics.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from threading import RLock
from typing import Any, Deque, Mapping, Optional, Protocol, Sequence, Tuple
from uuid import UUID

from .config import NAMESPACE_PATTERN
from .errors import QueueError


CONSUMER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
RECEIPT_PATTERN = re.compile(r"^[0-9]+-[0-9]+$")
GROUP_NAME = "workers-v1"
STALE_CLAIM_IDLE_MS = 60_000


@dataclass(frozen=True)
class QueueMessage:
    build_id: UUID
    receipt: str

    def __post_init__(self) -> None:
        if not isinstance(self.build_id, UUID):
            raise QueueError("invalid_queue_message", "queue build ID is invalid")
        if not isinstance(self.receipt, str) or RECEIPT_PATTERN.fullmatch(self.receipt) is None:
            raise QueueError("invalid_queue_message", "queue receipt is invalid")


class BuildQueue(Protocol):
    def enqueue(self, build_id: UUID) -> str:
        ...

    def claim(self, consumer: str, *, block_ms: int = 1000) -> Optional[QueueMessage]:
        ...

    def acknowledge(self, message: QueueMessage) -> None:
        ...

    def requeue(self, message: QueueMessage) -> str:
        ...

    def dead_letter(self, message: QueueMessage) -> str:
        ...


def _text(value: Any, label: str) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("ascii", "strict")
        except UnicodeDecodeError as exc:
            raise QueueError("invalid_queue_message", f"{label} is malformed") from exc
    if isinstance(value, str):
        return value
    raise QueueError("invalid_queue_message", f"{label} is malformed")


def _canonical_uuid(value: Any) -> UUID:
    text = _text(value, "build ID")
    try:
        parsed = UUID(text)
    except (ValueError, AttributeError) as exc:
        raise QueueError("invalid_queue_message", "queue build ID is malformed") from exc
    if str(parsed) != text:
        raise QueueError("invalid_queue_message", "queue build ID is not canonical")
    return parsed


class RedisStreamsQueue:
    """Small redis-py-compatible adapter with a fixed one-field payload."""

    def __init__(self, client: Any, namespace: str) -> None:
        if NAMESPACE_PATTERN.fullmatch(namespace) is None:
            raise QueueError("invalid_namespace", "queue namespace is outside policy")
        self._client = client
        self.stream = f"hbcb:{{{namespace}}}:builds:v1"
        self.dead_stream = f"hbcb:{{{namespace}}}:dead:v1"
        self.group = GROUP_NAME

    def initialize(self) -> None:
        try:
            self._client.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except Exception as exc:
            # redis-py exposes BUSYGROUP as ResponseError.  Avoid importing the
            # optional dependency in the contract package, but ignore only the
            # exact already-created condition.
            if exc.__class__.__name__ != "ResponseError" or "BUSYGROUP" not in str(exc):
                raise QueueError("queue_initialization_failed", "queue group could not be initialized") from exc

    def enqueue(self, build_id: UUID) -> str:
        if not isinstance(build_id, UUID):
            raise QueueError("invalid_build_id", "queue build ID is invalid")
        try:
            receipt = self._client.xadd(self.stream, {"build_id": str(build_id)})
        except Exception as exc:
            raise QueueError("queue_unavailable", "build could not be enqueued") from exc
        return self._receipt(receipt)

    def claim(self, consumer: str, *, block_ms: int = 1000) -> Optional[QueueMessage]:
        if not isinstance(consumer, str) or CONSUMER_PATTERN.fullmatch(consumer) is None:
            raise QueueError("invalid_consumer", "queue consumer is outside policy")
        if isinstance(block_ms, bool) or not isinstance(block_ms, int) or not 0 <= block_ms <= 60_000:
            raise QueueError("invalid_block_timeout", "queue block timeout is outside policy")
        reclaimed = self._reclaim_stale(consumer)
        if reclaimed is not None:
            return reclaimed
        try:
            response = self._client.xreadgroup(
                self.group,
                consumer,
                {self.stream: ">"},
                count=1,
                block=block_ms,
            )
        except Exception as exc:
            raise QueueError("queue_unavailable", "queue claim failed") from exc
        if not response:
            return None
        if not self._sequence(response) or len(response) != 1:
            raise QueueError("invalid_queue_message", "queue response shape is invalid")
        stream_name, entries = response[0]
        if _text(stream_name, "stream") != self.stream or not self._sequence(entries) or len(entries) != 1:
            raise QueueError("invalid_queue_message", "queue response shape is invalid")
        return self._message(entries[0])

    def _reclaim_stale(self, consumer: str) -> Optional[QueueMessage]:
        """Recover a claim lost before PostgreSQL leasing became authoritative."""

        try:
            response = self._client.xautoclaim(
                self.stream,
                self.group,
                consumer,
                STALE_CLAIM_IDLE_MS,
                start_id="0-0",
                count=1,
            )
        except Exception as exc:
            raise QueueError("queue_unavailable", "queue stale-claim recovery failed") from exc
        if not self._sequence(response) or len(response) not in (2, 3):
            raise QueueError("invalid_queue_message", "queue reclaim response shape is invalid")
        self._receipt(response[0])
        entries = response[1]
        if not self._sequence(entries) or len(entries) > 1:
            raise QueueError("invalid_queue_message", "queue reclaim response shape is invalid")
        if len(response) == 3:
            deleted = response[2]
            if not self._sequence(deleted):
                raise QueueError("invalid_queue_message", "queue reclaim response shape is invalid")
            for receipt in deleted:
                self._receipt(receipt)
        if not entries:
            return None
        return self._message(entries[0])

    @staticmethod
    def _sequence(value: Any) -> bool:
        return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))

    @classmethod
    def _message(cls, entry: Any) -> QueueMessage:
        if not cls._sequence(entry) or len(entry) != 2:
            raise QueueError("invalid_queue_message", "queue entry shape is invalid")
        receipt_raw, fields = entry
        if not isinstance(fields, Mapping) or len(fields) != 1:
            raise QueueError("invalid_queue_message", "queue payload must contain only build_id")
        key, value = next(iter(fields.items()))
        if _text(key, "field") != "build_id":
            raise QueueError("invalid_queue_message", "queue payload must contain only build_id")
        return QueueMessage(_canonical_uuid(value), cls._receipt(receipt_raw))

    def acknowledge(self, message: QueueMessage) -> None:
        self._require_message(message)
        try:
            acknowledged = self._client.xack(self.stream, self.group, message.receipt)
        except Exception as exc:
            raise QueueError("queue_unavailable", "queue acknowledgement failed") from exc
        if acknowledged not in (0, 1):
            raise QueueError("invalid_queue_response", "queue acknowledgement was invalid")

    def requeue(self, message: QueueMessage) -> str:
        return self._move(message, self.stream, "queue requeue failed")

    def dead_letter(self, message: QueueMessage) -> str:
        return self._move(message, self.dead_stream, "queue dead-letter failed")

    def _move(self, message: QueueMessage, target_stream: str, failure: str) -> str:
        self._require_message(message)
        try:
            pipeline = self._client.pipeline(transaction=True)
            pipeline.xadd(target_stream, {"build_id": str(message.build_id)})
            pipeline.xack(self.stream, self.group, message.receipt)
            results = pipeline.execute()
        except Exception as exc:
            raise QueueError("queue_unavailable", failure) from exc
        if not isinstance(results, Sequence) or len(results) != 2 or results[1] not in (0, 1):
            raise QueueError("invalid_queue_response", "queue move response was invalid")
        return self._receipt(results[0])

    @staticmethod
    def _receipt(value: Any) -> str:
        receipt = _text(value, "receipt")
        if RECEIPT_PATTERN.fullmatch(receipt) is None:
            raise QueueError("invalid_queue_response", "queue receipt is invalid")
        return receipt

    @staticmethod
    def _require_message(message: QueueMessage) -> None:
        if not isinstance(message, QueueMessage):
            raise QueueError("invalid_queue_message", "queue message is invalid")


class InMemoryBuildQueue:
    """Deterministic reference queue; duplicate delivery remains permitted."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._ready: Deque[QueueMessage] = deque()
        self._claimed: dict[str, QueueMessage] = {}
        self._dead: list[QueueMessage] = []
        self._next = 1

    def enqueue(self, build_id: UUID) -> str:
        if not isinstance(build_id, UUID):
            raise QueueError("invalid_build_id", "queue build ID is invalid")
        with self._lock:
            receipt = f"{self._next}-0"
            self._next += 1
            self._ready.append(QueueMessage(build_id, receipt))
            return receipt

    def claim(self, consumer: str, *, block_ms: int = 1000) -> Optional[QueueMessage]:
        if not isinstance(consumer, str) or CONSUMER_PATTERN.fullmatch(consumer) is None:
            raise QueueError("invalid_consumer", "queue consumer is outside policy")
        if isinstance(block_ms, bool) or not isinstance(block_ms, int) or not 0 <= block_ms <= 60_000:
            raise QueueError("invalid_block_timeout", "queue block timeout is outside policy")
        with self._lock:
            if not self._ready:
                return None
            message = self._ready.popleft()
            self._claimed[message.receipt] = message
            return message

    def acknowledge(self, message: QueueMessage) -> None:
        with self._lock:
            self._claimed.pop(message.receipt, None)

    def requeue(self, message: QueueMessage) -> str:
        with self._lock:
            self._claimed.pop(message.receipt, None)
            return self.enqueue(message.build_id)

    def dead_letter(self, message: QueueMessage) -> str:
        with self._lock:
            self._claimed.pop(message.receipt, None)
            receipt = f"{self._next}-0"
            self._next += 1
            self._dead.append(QueueMessage(message.build_id, receipt))
            return receipt

    @property
    def dead_messages(self) -> Tuple[QueueMessage, ...]:
        with self._lock:
            return tuple(self._dead)
