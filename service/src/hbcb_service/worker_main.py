"""Production concurrency-one worker supervisor entrypoint."""

from __future__ import annotations

import os
import signal
import socket
import stat
import threading
from pathlib import Path
from typing import Mapping, Optional

from .config import WorkerConfig
from .errors import WorkerError
from .launcher import SubprocessBuilderLauncher
from .queue import RedisStreamsQueue
from .repository import PostgresRepository
from .runtime import minio_client, postgres_connection_factory, redis_client
from .storage import MinioArtifactStorage
from .structured_log import StructuredLogger
from .worker import WorkerSupervisor


SCRATCH_ROOT = Path("/work/service")
BUILDER_EXECUTABLE = Path("/usr/local/bin/builder")


def _scratch_root() -> Path:
    try:
        SCRATCH_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = SCRATCH_ROOT.lstat()
        SCRATCH_ROOT.chmod(0o700)
    except OSError as exc:
        raise WorkerError("scratch_root_invalid", "worker scratch root is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or SCRATCH_ROOT.is_symlink():
        raise WorkerError("scratch_root_invalid", "worker scratch root is unavailable")
    return SCRATCH_ROOT


def create_supervisor(
    environment: Optional[Mapping[str, str]] = None,
) -> WorkerSupervisor:
    supplied = os.environ if environment is None else environment
    config = WorkerConfig.from_environment(supplied)
    connect = postgres_connection_factory(config.database_url)
    repository = PostgresRepository(
        connect,
        deployment_namespace=config.deployment_namespace,
        idempotency_secret=None,
        storage_bucket=config.storage_bucket,
    )
    redis = redis_client(config.redis_url)
    queue = RedisStreamsQueue(redis, config.deployment_namespace)
    queue.initialize()
    internal = minio_client(
        config.storage_internal_endpoint,
        config.storage_access_key,
        config.storage_secret_key,
        secure=config.storage_internal_secure,
        region=config.storage_region,
    )
    storage = MinioArtifactStorage(
        internal,
        internal,
        namespace=config.deployment_namespace,
        bucket=config.storage_bucket,
    )
    storage.require_bucket()
    image_reference = supplied.get("HBCB_WORKER_IMAGE_REFERENCE", "")
    image_digest = supplied.get("HBCB_WORKER_IMAGE_DIGEST")
    image_id = supplied.get("HBCB_WORKER_IMAGE_ID")
    launcher = SubprocessBuilderLauncher(
        builder_executable=BUILDER_EXECUTABLE,
        scratch_root=_scratch_root(),
        image_reference=image_reference,
        image_digest=image_digest,
        image_id=image_id,
        timeout_seconds=900,
        poll_seconds=1,
    )
    return WorkerSupervisor(
        repository=repository,
        queue=queue,
        storage=storage,
        launcher=launcher,
        deployment_namespace=config.deployment_namespace,
        storage_bucket=config.storage_bucket,
        worker_id=socket.gethostname(),
        lease_seconds=30,
        retry_delay_seconds=5,
        logger=StructuredLogger(),
    )


def main() -> None:
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    create_supervisor().run_forever(stop, block_ms=1000)


if __name__ == "__main__":
    main()
