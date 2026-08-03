"""Production API process entrypoint."""

from __future__ import annotations

import os
from typing import Mapping, Optional

from .api import create_app
from .config import ServiceConfig
from .queue import RedisStreamsQueue
from .repository import PostgresRepository
from .runtime import (
    ServiceReadiness,
    postgres_connection_factory,
    redis_client,
    service_storage,
)


def create_application(environment: Optional[Mapping[str, str]] = None):
    supplied = os.environ if environment is None else environment
    config = ServiceConfig.from_environment(supplied)
    connect = postgres_connection_factory(config.database_url)
    repository = PostgresRepository(
        connect,
        deployment_namespace=config.deployment_namespace,
        idempotency_secret=config.idempotency_secret,
        storage_bucket=config.storage_bucket,
    )
    redis = redis_client(config.redis_url)
    queue = RedisStreamsQueue(redis, config.deployment_namespace)
    storage = service_storage(
        internal_endpoint=config.storage_internal_endpoint,
        public_endpoint=config.storage_public_endpoint,
        access_key=config.storage_access_key,
        secret_key=config.storage_secret_key,
        secure=config.storage_secure,
        namespace=config.deployment_namespace,
        bucket=config.storage_bucket,
    )
    readiness = ServiceReadiness(
        repository=repository,
        connect=connect,
        redis=redis,
        queue=queue,
        storage=storage,
    )
    return create_app(
        repository=repository,
        storage=storage,
        configured_token=config.api_token.reveal(),
        signed_url_ttl_seconds=config.signed_url_ttl_seconds,
        readiness=readiness,
    )


def main() -> None:
    import uvicorn

    uvicorn.run(
        create_application(),
        host="0.0.0.0",
        port=8080,
        access_log=False,
        server_header=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
