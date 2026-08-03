from __future__ import annotations

import io
import unittest
from unittest import mock
from uuid import uuid4

from hbcb_service.api_main import create_application
from hbcb_service.config import SecretValue
from hbcb_service.errors import StateConflict
from hbcb_service.migrations import load_migrations
from hbcb_service.queue import RedisStreamsQueue
from hbcb_service.repository import PostgresRepository
from hbcb_service.runtime import ServiceReadiness, service_storage
from hbcb_service.structured_log import StructuredLogger

try:
    from .g6_support import facet_request_bytes
    from .support import valid_environment
except ImportError:
    from g6_support import facet_request_bytes
    from support import valid_environment


class FakeCursor:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self.rows = rows

    def execute(self, _sql: str, _parameters: object = None) -> None:
        return None

    def fetchall(self):
        return list(self.rows)

    def close(self) -> None:
        return None


class FakeConnection:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self.rows = rows
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.rows)

    def close(self) -> None:
        self.closed = True


class FakeRepository:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready

    def ping(self) -> bool:
        return self.ready


class FakeRedis:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready
        self.created = False

    def ping(self) -> bool:
        return self.ready

    def xgroup_create(self, *_args: object, **_kwargs: object) -> None:
        self.created = True

    def xinfo_groups(self, _stream: str):
        return [{b"name": b"workers-v1"}] if self.created else []


class FakeStorage:
    def __init__(self) -> None:
        self.checked = False

    def require_bucket(self) -> None:
        self.checked = True


class RuntimeWiringTests(unittest.TestCase):
    def test_api_factory_constructs_without_contacting_dependencies(self) -> None:
        app = create_application(valid_environment())
        self.assertIsNotNone(app)
        self.assertIsNone(app.docs_url)
        self.assertIsNone(app.openapi_url)

    def test_readiness_requires_current_migrations_redis_group_and_storage(self) -> None:
        rows = [(item.version, item.sha256) for item in load_migrations()]
        redis = FakeRedis()
        storage = FakeStorage()
        readiness = ServiceReadiness(
            repository=FakeRepository(),  # type: ignore[arg-type]
            connect=lambda: FakeConnection(rows),
            redis=redis,
            queue=RedisStreamsQueue(redis, "local"),
            storage=storage,  # type: ignore[arg-type]
        )
        self.assertTrue(readiness())
        self.assertTrue(storage.checked)

        stale = ServiceReadiness(
            repository=FakeRepository(),  # type: ignore[arg-type]
            connect=lambda: FakeConnection([]),
            redis=FakeRedis(),
            queue=RedisStreamsQueue(FakeRedis(), "local"),
            storage=FakeStorage(),  # type: ignore[arg-type]
        )
        self.assertFalse(stale())

    def test_worker_repository_role_cannot_submit(self) -> None:
        repository = PostgresRepository(
            lambda: (_ for _ in ()).throw(AssertionError("must not connect")),
            deployment_namespace="local",
            idempotency_secret=None,
            storage_bucket="hbcb-artifacts",
        )
        with self.assertRaises(StateConflict) as captured:
            repository.submit(facet_request_bytes(), "facet-request-0001")
        self.assertEqual(captured.exception.code, "operation_not_permitted")

    def test_storage_clients_use_explicit_transport_security_and_region(self) -> None:
        clients = [mock.Mock(), mock.Mock()]
        with mock.patch("minio.Minio", side_effect=clients) as constructor:
            storage = service_storage(
                internal_endpoint="minio:9000",
                public_endpoint="localhost:9000",
                access_key=SecretValue("hbcb_api_key", minimum=3),
                secret_key=SecretValue("c" * 64),
                internal_secure=False,
                public_secure=True,
                region="us-west-2",
                namespace="local",
                bucket="hbcb-artifacts",
            )
        self.assertIsNotNone(storage)
        self.assertEqual(constructor.call_count, 2)
        self.assertFalse(constructor.call_args_list[0].kwargs["secure"])
        self.assertTrue(constructor.call_args_list[1].kwargs["secure"])
        for call in constructor.call_args_list:
            self.assertEqual(call.kwargs["region"], "us-west-2")


class StructuredLoggingTests(unittest.TestCase):
    def test_only_bounded_metadata_is_emitted(self) -> None:
        stream = io.StringIO()
        logger = StructuredLogger(stream)
        build_id = uuid4()
        logger.emit(
            "attempt_started",
            build_id=build_id,
            worker_id="worker-1",
            details={"attempt_number": 1, "requeued": False},
        )
        value = stream.getvalue()
        self.assertIn(str(build_id), value)
        self.assertNotIn("Bearer", value)
        with self.assertRaises(ValueError):
            logger.emit(
                "unsafe_event",
                details={"download_url": "https://signed.example/secret"},
            )


if __name__ == "__main__":
    unittest.main()
