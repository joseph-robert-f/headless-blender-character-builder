"""Lazy production dependency wiring shared by API, worker, and migrator."""

from __future__ import annotations

from typing import Any, Callable, Optional

from .config import SecretValue
from .migrations import load_migrations
from .queue import RedisStreamsQueue
from .repository import PostgresRepository
from .storage import MinioArtifactStorage


MINIO_DEFAULT_REGION = "us-east-1"


def postgres_connection_factory(database_url: SecretValue) -> Callable[[], Any]:
    dsn = database_url.reveal()

    def connect() -> Any:
        import psycopg

        return psycopg.connect(
            dsn,
            connect_timeout=5,
            options="-c statement_timeout=5000 -c lock_timeout=5000",
        )

    return connect


def redis_client(redis_url: SecretValue) -> Any:
    import redis

    return redis.Redis.from_url(
        redis_url.reveal(),
        socket_connect_timeout=3,
        socket_timeout=3,
        health_check_interval=15,
        decode_responses=False,
    )


def minio_client(
    endpoint: str,
    access_key: SecretValue,
    secret_key: SecretValue,
    *,
    secure: bool,
) -> Any:
    from minio import Minio
    import urllib3

    http_client = urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=3.0, read=3.0),
        retries=False,
    )

    return Minio(
        endpoint,
        access_key=access_key.reveal(),
        secret_key=secret_key.reveal(),
        secure=secure,
        # Pin the local MinIO default so presigning is pure computation.  If
        # omitted, minio-py first queries GetBucketLocation through the public
        # URL (localhost from a host-facing signed URL), which is unreachable
        # from the API container.
        region=MINIO_DEFAULT_REGION,
        http_client=http_client,
    )


def service_storage(
    *,
    internal_endpoint: str,
    public_endpoint: str,
    access_key: SecretValue,
    secret_key: SecretValue,
    secure: bool,
    namespace: str,
    bucket: str,
) -> MinioArtifactStorage:
    internal = minio_client(
        internal_endpoint,
        access_key,
        secret_key,
        secure=secure,
    )
    signer = minio_client(
        public_endpoint,
        access_key,
        secret_key,
        secure=secure,
    )
    return MinioArtifactStorage(
        internal,
        signer,
        namespace=namespace,
        bucket=bucket,
    )


class ServiceReadiness:
    """Bounded full-pipeline readiness without returning dependency details."""

    def __init__(
        self,
        *,
        repository: PostgresRepository,
        connect: Callable[[], Any],
        redis: Any,
        queue: RedisStreamsQueue,
        storage: MinioArtifactStorage,
    ) -> None:
        self._repository = repository
        self._connect = connect
        self._redis = redis
        self._queue = queue
        self._storage = storage

    def _migrations_current(self) -> bool:
        expected = {
            migration.version: migration.sha256 for migration in load_migrations()
        }
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT version, sha256 FROM hbcb.schema_migrations ORDER BY version"
            )
            actual = {str(row[0]): str(row[1]) for row in cursor.fetchall()}
            return actual == expected
        finally:
            try:
                cursor.close()
            except (AttributeError, UnboundLocalError):
                pass
            try:
                connection.close()
            except Exception:
                pass

    def __call__(self) -> bool:
        if not self._repository.ping() or not self._migrations_current():
            return False
        if self._redis.ping() is not True:
            return False
        self._queue.initialize()
        groups = self._redis.xinfo_groups(self._queue.stream)
        names = set()
        for group in groups:
            if not isinstance(group, dict):
                continue
            value = group.get(b"name", group.get("name"))
            if isinstance(value, bytes):
                value = value.decode("ascii", "ignore")
            if isinstance(value, str):
                names.add(value)
        if self._queue.group not in names:
            return False
        self._storage.require_bucket()
        return True


__all__ = [
    "ServiceReadiness",
    "MINIO_DEFAULT_REGION",
    "minio_client",
    "postgres_connection_factory",
    "redis_client",
    "service_storage",
]
