from __future__ import annotations

import unittest
from uuid import UUID, uuid4

from hbcb_service.errors import QueueError
from hbcb_service.queue import InMemoryBuildQueue, QueueMessage, RedisStreamsQueue


class ResponseError(Exception):
    pass


class FakePipeline:
    def __init__(self, client: "FakeRedis") -> None:
        self.client = client
        self.commands = []

    def xadd(self, stream: str, fields: dict[str, str]) -> "FakePipeline":
        self.commands.append(("xadd", stream, fields))
        return self

    def xack(self, stream: str, group: str, receipt: str) -> "FakePipeline":
        self.commands.append(("xack", stream, group, receipt))
        return self

    def execute(self) -> list[object]:
        self.client.pipeline_commands = list(self.commands)
        return [b"9-0", 1]


class FakeRedis:
    def __init__(self) -> None:
        self.group_calls = []
        self.xadd_calls = []
        self.read_response = []
        self.ack_result = 1
        self.pipeline_commands = []
        self.raise_group = None

    def xgroup_create(self, *args: object, **kwargs: object) -> None:
        self.group_calls.append((args, kwargs))
        if self.raise_group is not None:
            raise self.raise_group

    def xadd(self, stream: str, fields: dict[str, str]) -> bytes:
        self.xadd_calls.append((stream, fields))
        return b"1-0"

    def xreadgroup(self, *args: object, **kwargs: object) -> object:
        self.read_arguments = (args, kwargs)
        return self.read_response

    def xack(self, *args: object) -> int:
        self.ack_arguments = args
        return self.ack_result

    def pipeline(self, *, transaction: bool) -> FakePipeline:
        self.pipeline_transaction = transaction
        return FakePipeline(self)


class RedisQueueContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeRedis()
        self.queue = RedisStreamsQueue(self.client, "local")
        self.build_id = UUID("11111111-1111-4111-8111-111111111111")

    def test_namespace_and_group_are_fixed_and_initialization_is_idempotent(self) -> None:
        self.assertEqual(self.queue.stream, "hbcb:{local}:builds:v1")
        self.assertEqual(self.queue.dead_stream, "hbcb:{local}:dead:v1")
        self.queue.initialize()
        self.assertEqual(
            self.client.group_calls,
            [((self.queue.stream, "workers-v1"), {"id": "0", "mkstream": True})],
        )
        self.client.raise_group = ResponseError("BUSYGROUP Consumer Group name already exists")
        self.queue.initialize()
        self.client.raise_group = ResponseError("NOAUTH authentication required")
        with self.assertRaises(QueueError):
            self.queue.initialize()

    def test_enqueue_contains_exactly_build_id_and_no_request_or_secret(self) -> None:
        receipt = self.queue.enqueue(self.build_id)
        self.assertEqual(receipt, "1-0")
        self.assertEqual(
            self.client.xadd_calls,
            [(self.queue.stream, {"build_id": str(self.build_id)})],
        )
        rendered = repr(self.client.xadd_calls)
        for forbidden in ("request", "token", "secret", "spec", "idempotency"):
            self.assertNotIn(forbidden, rendered.lower())

    def test_claim_accepts_only_one_canonical_build_id_field(self) -> None:
        self.client.read_response = [
            (
                self.queue.stream.encode("ascii"),
                [(b"7-1", {b"build_id": str(self.build_id).encode("ascii")})],
            )
        ]
        message = self.queue.claim("worker-1", block_ms=500)
        self.assertEqual(message, QueueMessage(self.build_id, "7-1"))
        args, kwargs = self.client.read_arguments
        self.assertEqual(args[:2], ("workers-v1", "worker-1"))
        self.assertEqual(kwargs["count"], 1)
        self.assertEqual(kwargs["block"], 500)

    def test_malformed_extra_cross_namespace_and_noncanonical_messages_fail(self) -> None:
        cases = (
            [(self.queue.stream, [("1-0", {"build_id": str(self.build_id), "extra": "x"})])],
            [("hbcb:{other}:builds:v1", [("1-0", {"build_id": str(self.build_id)})])],
            [(self.queue.stream, [("1-0", {"build_id": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"})])],
            [(self.queue.stream, [("bad", {"build_id": str(self.build_id)})])],
        )
        for response in cases:
            with self.subTest(response=response[0][0]):
                self.client.read_response = response
                with self.assertRaises(QueueError):
                    self.queue.claim("worker-1")

    def test_acknowledge_requeue_and_dead_letter_use_fixed_transaction(self) -> None:
        message = QueueMessage(self.build_id, "7-1")
        self.queue.acknowledge(message)
        self.assertEqual(
            self.client.ack_arguments,
            (self.queue.stream, "workers-v1", "7-1"),
        )
        self.assertEqual(self.queue.requeue(message), "9-0")
        self.assertEqual(
            self.client.pipeline_commands,
            [
                ("xadd", self.queue.stream, {"build_id": str(self.build_id)}),
                ("xack", self.queue.stream, "workers-v1", "7-1"),
            ],
        )
        self.assertEqual(self.queue.dead_letter(message), "9-0")
        self.assertEqual(self.client.pipeline_commands[0][1], self.queue.dead_stream)
        self.assertTrue(self.client.pipeline_transaction)

    def test_timeout_consumer_and_namespace_limits_fail_before_redis(self) -> None:
        for consumer, timeout in (("bad consumer", 1), ("worker", -1), ("worker", 60_001)):
            with self.assertRaises(QueueError):
                self.queue.claim(consumer, block_ms=timeout)
        for namespace in ("", "UPPER", "../escape", "a" * 33):
            with self.assertRaises(QueueError):
                RedisStreamsQueue(self.client, namespace)


class InMemoryQueueTests(unittest.TestCase):
    def test_reference_queue_preserves_at_least_once_move_semantics(self) -> None:
        queue = InMemoryBuildQueue()
        build_id = uuid4()
        queue.enqueue(build_id)
        message = queue.claim("worker-1")
        self.assertIsNotNone(message)
        queue.requeue(message)
        replay = queue.claim("worker-1")
        self.assertEqual(replay.build_id, build_id)
        queue.dead_letter(replay)
        self.assertEqual(queue.dead_messages[0].build_id, build_id)
        self.assertIsNone(queue.claim("worker-1", block_ms=0))
