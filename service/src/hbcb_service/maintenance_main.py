"""Command-line entrypoint for bounded G8 maintenance operations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Callable, Mapping, Optional, Sequence, TextIO

from .config import WorkerConfig
from .errors import ServiceError
from .maintenance import (
    MAX_MAINTENANCE_BATCH,
    MAX_ORPHAN_SCAN_VERSIONS,
    MAX_RETENTION_DAYS,
    MaintenanceError,
    MaintenanceService,
    MinioVersionedObjectClient,
    PostgresMaintenanceStore,
    RetentionPolicy,
)
from .queue import RedisStreamsQueue
from .runtime import minio_client, postgres_connection_factory, redis_client


ServiceFactory = Callable[[Mapping[str, str]], MaintenanceService]


def _bounded_cli_integer(label: str, minimum: int, maximum: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        if not isinstance(value, str) or not value.isascii() or not value.isdigit():
            raise argparse.ArgumentTypeError(f"{label} is outside policy")
        parsed = int(value)
        if not minimum <= parsed <= maximum:
            raise argparse.ArgumentTypeError(f"{label} is outside policy")
        return parsed

    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hbcb-maintenance")
    commands = parser.add_subparsers(dest="command", required=True)

    retention = commands.add_parser(
        "retain",
        aliases=["retention"],
        help="preview or apply terminal-build retention",
    )
    retention.add_argument("--apply", action="store_true", help="perform the deletion transaction")
    retention.add_argument(
        "--limit",
        type=_bounded_cli_integer("retention limit", 1, MAX_MAINTENANCE_BATCH),
        default=100,
    )
    for option, default in (
        ("succeeded-days", 30),
        ("failed-days", 7),
        ("canceled-days", 7),
        ("needs-review-days", 7),
        ("orphan-grace-days", 7),
    ):
        retention.add_argument(
            "--" + option,
            type=_bounded_cli_integer(option, 1, MAX_RETENTION_DAYS),
            default=None,
        )

    deletion = commands.add_parser(
        "delete-artifacts", help="preview or delete exact queued object versions"
    )
    deletion.add_argument("--apply", action="store_true", help="delete exact recorded versions")
    deletion.add_argument(
        "--limit",
        type=_bounded_cli_integer("deletion limit", 1, MAX_MAINTENANCE_BATCH),
        default=100,
    )
    deletion.add_argument(
        "--orphan-grace-days",
        type=_bounded_cli_integer("orphan grace days", 1, MAX_RETENTION_DAYS),
        default=None,
    )
    deletion.add_argument("--worker-id", default="maintenance-v1")

    orphan = commands.add_parser(
        "discover-orphans",
        help="preview or durably queue old unreferenced immutable object versions",
    )
    orphan.add_argument(
        "--apply",
        action="store_true",
        help="queue exact orphan evidence for later delete-artifacts processing",
    )
    orphan.add_argument(
        "--limit",
        type=_bounded_cli_integer("orphan limit", 1, MAX_MAINTENANCE_BATCH),
        default=100,
    )
    orphan.add_argument(
        "--scan-limit",
        type=_bounded_cli_integer("orphan scan limit", 1, MAX_ORPHAN_SCAN_VERSIONS),
        default=MAX_ORPHAN_SCAN_VERSIONS,
    )
    orphan.add_argument(
        "--orphan-grace-days",
        type=_bounded_cli_integer("orphan grace days", 1, MAX_RETENTION_DAYS),
        default=None,
    )

    reconstruct = commands.add_parser(
        "reconstruct-redis",
        help="derive Redis wakeups from current PostgreSQL queued builds",
    )
    reconstruct.add_argument("--apply", action="store_true", help="enqueue the derived UUIDs")
    reconstruct.add_argument(
        "--limit",
        type=_bounded_cli_integer("Redis reconstruction limit", 1, MAX_MAINTENANCE_BATCH),
        default=MAX_MAINTENANCE_BATCH,
    )

    commands.add_parser(
        "backup-inventory",
        help="emit exact PostgreSQL artifact version/hash inventory JSON",
    )
    backup_export = commands.add_parser(
        "backup-export",
        help="download exact referenced object versions into a new private directory",
    )
    backup_export.add_argument("--output", required=True)

    restore = commands.add_parser(
        "restore-objects",
        help="validate an object backup and restore exact canonical keys",
    )
    restore.add_argument("--input", required=True)
    restore.add_argument(
        "--apply",
        action="store_true",
        help="upload verified objects and atomically remap PostgreSQL version IDs",
    )
    return parser


class _InitializingQueue:
    """Create the Redis group lazily, only when an apply operation enqueues."""

    def __init__(self, queue: RedisStreamsQueue) -> None:
        self._queue = queue
        self._initialized = False

    def enqueue(self, build_id: Any) -> str:
        if not self._initialized:
            self._queue.initialize()
            self._initialized = True
        return self._queue.enqueue(build_id)


def service_from_environment(environment: Mapping[str, str]) -> MaintenanceService:
    """Wire clients from a maintenance-process environment.

    ``HBCB_DATABASE_URL`` must identify a separately scoped maintenance role in
    production.  This module does not reuse or broaden the API/worker grants.
    """

    config = WorkerConfig.from_environment(environment)
    store = PostgresMaintenanceStore(
        postgres_connection_factory(config.database_url),
        namespace=config.deployment_namespace,
    )
    redis_queue = RedisStreamsQueue(
        redis_client(config.redis_url),
        config.deployment_namespace,
    )
    storage = MinioVersionedObjectClient(
        minio_client(
            config.storage_internal_endpoint,
            config.storage_access_key,
            config.storage_secret_key,
            secure=config.storage_internal_secure,
            region=config.storage_region,
        )
    )
    return MaintenanceService(
        store,
        namespace=config.deployment_namespace,
        bucket=config.storage_bucket,
        objects=storage,
        queue=_InitializingQueue(redis_queue),
    )


def _environment_integer(
    environment: Mapping[str, str], name: str, default: int
) -> int:
    value = environment.get(name)
    if value is None:
        return default
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise MaintenanceError("invalid_integer", f"{name} is outside policy")
    parsed = int(value)
    if not 1 <= parsed <= MAX_RETENTION_DAYS:
        raise MaintenanceError("invalid_integer", f"{name} is outside policy")
    return parsed


def _policy(
    arguments: argparse.Namespace,
    environment: Mapping[str, str],
    *,
    deletion_only: bool = False,
) -> RetentionPolicy:
    orphan_default = _environment_integer(
        environment, "HBCB_ORPHAN_GRACE_DAYS", 7
    )
    orphan_days = (
        orphan_default
        if arguments.orphan_grace_days is None
        else arguments.orphan_grace_days
    )
    if deletion_only:
        return RetentionPolicy(orphan_grace_days=orphan_days)
    succeeded_default = _environment_integer(
        environment, "HBCB_RETENTION_SUCCEEDED_DAYS", 30
    )
    other_default = _environment_integer(
        environment, "HBCB_RETENTION_OTHER_DAYS", 7
    )
    return RetentionPolicy(
        succeeded_days=(
            succeeded_default
            if arguments.succeeded_days is None
            else arguments.succeeded_days
        ),
        failed_days=(
            other_default if arguments.failed_days is None else arguments.failed_days
        ),
        canceled_days=(
            other_default
            if arguments.canceled_days is None
            else arguments.canceled_days
        ),
        needs_review_days=(
            other_default
            if arguments.needs_review_days is None
            else arguments.needs_review_days
        ),
        orphan_grace_days=orphan_days,
    )


def _write_json(stream: TextIO, payload: Mapping[str, Any]) -> None:
    stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def run(
    argv: Optional[Sequence[str]] = None,
    *,
    environment: Optional[Mapping[str, str]] = None,
    service_factory: ServiceFactory = service_from_environment,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    now: Optional[datetime] = None,
) -> int:
    """Run one maintenance command.

    ``now`` is a Python-only dependency-injection seam for deterministic tests.
    It is intentionally absent from the command-line parser, so operators
    cannot move destructive grace-period decisions forward from the CLI.
    """

    parser = build_parser()
    arguments = parser.parse_args(argv)
    selected_environment = os.environ if environment is None else environment
    try:
        service = service_factory(selected_environment)
        if arguments.command in ("retain", "retention"):
            result = service.run_retention(
                policy=_policy(arguments, selected_environment),
                apply=arguments.apply,
                limit=arguments.limit,
                now=now,
            )
            _write_json(
                stdout,
                {
                    "candidates": len(result.candidates),
                    "deleted_builds": len(result.deleted_build_ids),
                    "dry_run": result.dry_run,
                    "queued_artifact_versions": result.queued_artifact_versions,
                },
            )
        elif arguments.command == "delete-artifacts":
            result = service.run_artifact_deletion(
                policy=_policy(
                    arguments,
                    selected_environment,
                    deletion_only=True,
                ),
                worker_id=arguments.worker_id,
                apply=arguments.apply,
                limit=arguments.limit,
                now=now,
            )
            _write_json(
                stdout,
                {
                    "considered": result.considered,
                    "deleted": result.deleted,
                    "dry_run": result.dry_run,
                    "failed": result.failed,
                },
            )
        elif arguments.command == "discover-orphans":
            result = service.discover_orphan_versions(
                policy=_policy(
                    arguments,
                    selected_environment,
                    deletion_only=True,
                ),
                apply=arguments.apply,
                limit=arguments.limit,
                scan_limit=arguments.scan_limit,
                now=now,
            )
            _write_json(
                stdout,
                {
                    "candidates": result.candidates,
                    "dry_run": result.dry_run,
                    "queued": result.queued,
                    "scanned": result.scanned,
                },
            )
        elif arguments.command == "reconstruct-redis":
            result = service.reconstruct_redis(
                apply=arguments.apply,
                limit=arguments.limit,
            )
            _write_json(
                stdout,
                {
                    "derived_queued_builds": result.derived_queued_builds,
                    "dry_run": result.dry_run,
                    "enqueued": result.enqueued,
                },
            )
        elif arguments.command == "backup-inventory":
            stdout.write(service.backup_inventory().to_json_bytes().decode("ascii") + "\n")
        elif arguments.command == "backup-export":
            result = service.export_object_backup(arguments.output)
            _write_json(
                stdout,
                {
                    "artifact_bytes": result.artifact_bytes,
                    "artifacts": result.artifact_count,
                    "inventory_sha256": result.inventory_sha256,
                },
            )
        elif arguments.command == "restore-objects":
            result = service.restore_object_backup(
                arguments.input,
                apply=arguments.apply,
            )
            _write_json(
                stdout,
                {
                    "artifact_bytes": result.artifact_bytes,
                    "artifacts": result.artifact_count,
                    "dry_run": result.dry_run,
                    "remapped": result.remapped,
                    "uploaded": result.uploaded,
                },
            )
        else:  # pragma: no cover - argparse makes this unreachable.
            raise MaintenanceError("invalid_command", "maintenance command is invalid")
        return 0
    except ServiceError as exc:
        _write_json(stderr, {"error": {"code": exc.code}, "ok": False})
        return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
