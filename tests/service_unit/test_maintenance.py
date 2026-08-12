from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from hbcb_service.maintenance import (
    ArtifactVersionEvidence,
    BackupInventory,
    DeletionWorkItem,
    MaintenanceError,
    MaintenanceService,
    MinioVersionedObjectClient,
    PostgresMaintenanceStore,
    RetentionApplyResult,
    RetentionCandidate,
    RetentionPolicy,
    StoredObjectVersion,
    VersionRemap,
    validate_namespace,
)
from hbcb_service.maintenance_main import run
from hbcb_service.models import BuildStatus


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
BUILD_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BUILD_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
CLAIM = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


def evidence(
    *,
    build_id: UUID = BUILD_A,
    name: str = "model.stl",
    version_id: str = "version-1",
    payload: bytes = b"mesh-bytes",
) -> ArtifactVersionEvidence:
    return ArtifactVersionEvidence(
        namespace="local",
        build_id=build_id,
        bucket="hbcb-artifacts",
        object_key=f"local/v1/builds/{build_id}/attempts/11111111-1111-4111-8111-111111111111/complete-v1/{name}",
        version_id=version_id,
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
    )


def deletion_item(
    *,
    queue_id: int = 1,
    item_evidence: ArtifactVersionEvidence | None = None,
    status: str = "pending",
    claim_token: UUID | None = None,
) -> DeletionWorkItem:
    return DeletionWorkItem(
        queue_id=queue_id,
        evidence=item_evidence or evidence(),
        status=status,
        attempt_count=0,
        queued_at=NOW - timedelta(days=8),
        claim_token=claim_token,
    )


def stored_version(
    *,
    build_id: UUID = BUILD_A,
    name: str = "model.stl",
    version_id: str = "version-1",
    modified: datetime = NOW - timedelta(days=8),
    payload: bytes = b"mesh-bytes",
) -> StoredObjectVersion:
    attempt_id = UUID("11111111-1111-4111-8111-111111111111")
    return StoredObjectVersion(
        namespace="local",
        build_id=build_id,
        attempt_id=attempt_id,
        relative_path=name,
        bucket="hbcb-artifacts",
        object_key=(
            f"local/v1/builds/{build_id}/attempts/{attempt_id}/complete-v1/{name}"
        ),
        version_id=version_id,
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        last_modified=modified,
    )


class FakeStore:
    def __init__(self) -> None:
        self.candidates = (
            RetentionCandidate(
                BUILD_A,
                BuildStatus.SUCCEEDED,
                NOW - timedelta(days=31),
                1,
                10,
            ),
            RetentionCandidate(
                BUILD_B,
                BuildStatus.FAILED,
                NOW - timedelta(days=8),
                0,
                0,
            ),
        )
        self.preview: tuple[DeletionWorkItem, ...] = ()
        self.queued_ids: tuple[UUID, ...] = (BUILD_A, BUILD_B)
        self.inventory: tuple[ArtifactVersionEvidence, ...] = ()
        self.retention_selects: list[tuple[RetentionPolicy, datetime, int]] = []
        self.retention_applies: list[tuple[RetentionPolicy, datetime, tuple[UUID, ...]]] = []
        self.preview_calls: list[tuple[datetime, datetime, int]] = []
        self.claim_calls: list[tuple[datetime, datetime, int, UUID, datetime]] = []
        self.deletion_attempts: list[tuple[DeletionWorkItem, str, str, str | None, datetime]] = []
        self.remap_calls: list[tuple[VersionRemap, ...]] = []
        self.object_inventory: tuple[StoredObjectVersion, ...] = ()
        self.orphan_candidates: tuple[StoredObjectVersion, ...] = ()
        self.orphan_calls = []

    def select_retention_candidates(self, policy: RetentionPolicy, now: datetime, limit: int):
        self.retention_selects.append((policy, now, limit))
        return self.candidates[:limit]

    def queue_and_delete_builds(
        self, policy: RetentionPolicy, now: datetime, build_ids: tuple[UUID, ...]
    ) -> RetentionApplyResult:
        self.retention_applies.append((policy, now, build_ids))
        return RetentionApplyResult(build_ids, sum(item.artifact_count for item in self.candidates))

    def preview_deletions(self, eligible_before: datetime, now: datetime, limit: int):
        self.preview_calls.append((eligible_before, now, limit))
        return self.preview[:limit]

    def claim_deletions(
        self,
        eligible_before: datetime,
        now: datetime,
        limit: int,
        claim_token: UUID,
        lease_expires_at: datetime,
    ):
        self.claim_calls.append((eligible_before, now, limit, claim_token, lease_expires_at))
        return tuple(
            DeletionWorkItem(
                item.queue_id,
                item.evidence,
                "deleting",
                item.attempt_count,
                item.queued_at,
                claim_token,
            )
            for item in self.preview[:limit]
        )

    def record_deletion_attempt(
        self,
        item: DeletionWorkItem,
        worker_id: str,
        outcome: str,
        error_code: str | None,
        attempted_at: datetime,
    ) -> None:
        self.deletion_attempts.append((item, worker_id, outcome, error_code, attempted_at))

    def reconcile_orphan_versions(
        self,
        versions: tuple[StoredObjectVersion, ...],
        eligible_before: datetime,
        now: datetime,
        apply: bool,
        limit: int,
    ):
        self.orphan_calls.append((versions, eligible_before, now, apply, limit))
        return self.orphan_candidates[:limit]

    def iter_queued_build_ids(self, page_size: int):
        ordered = tuple(sorted(self.queued_ids, key=lambda value: value.int))
        for offset in range(0, len(ordered), page_size):
            yield ordered[offset : offset + page_size]

    def artifact_inventory(self):
        return self.inventory

    def apply_version_remaps(self, remaps: tuple[VersionRemap, ...]) -> int:
        self.remap_calls.append(remaps)
        return len(remaps)


class FakeObjects:
    def __init__(self, versions: dict[tuple[str, str, str], bytes]) -> None:
        self.versions = versions
        self.deleted: list[tuple[str, str, str]] = []
        self.fail_delete: set[str] = set()
        self.uploaded: list[tuple[str, str, bytes, int, str, str]] = []
        self.inspected: list[tuple[str, str]] = []
        self.namespace_is_empty = True
        self.inventory: tuple[StoredObjectVersion, ...] = ()
        self.inventory_calls = []

    def iter_version(self, bucket: str, object_key: str, version_id: str):
        payload = self.versions[(bucket, object_key, version_id)]
        midpoint = max(1, len(payload) // 2)
        yield payload[:midpoint]
        if payload[midpoint:]:
            yield payload[midpoint:]

    def delete_version(self, bucket: str, object_key: str, version_id: str) -> None:
        self.deleted.append((bucket, object_key, version_id))
        if version_id in self.fail_delete:
            raise RuntimeError("secret storage failure details")

    def inventory_namespace_versions(self, bucket: str, namespace: str, *, limit: int):
        self.inventory_calls.append((bucket, namespace, limit))
        return self.inventory

    def assert_namespace_empty(self, bucket: str, namespace: str) -> None:
        self.inspected.append((bucket, namespace))
        if not self.namespace_is_empty:
            raise MaintenanceError("restore_target_not_empty", "fixed safe message")

    def upload_version(
        self,
        bucket: str,
        object_key: str,
        source: io.BufferedReader,
        bytes: int,
        sha256: str,
        content_type: str,
    ) -> str:
        payload = source.read()
        version_id = f"restored-{len(self.uploaded) + 1}"
        self.uploaded.append((bucket, object_key, payload, bytes, sha256, content_type))
        self.versions[(bucket, object_key, version_id)] = payload
        return version_id


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[UUID] = []

    def enqueue(self, build_id: UUID) -> str:
        self.enqueued.append(build_id)
        return f"{len(self.enqueued)}-0"


class FakeExporter:
    def __init__(self, payload: bytes, *, fail: bool = False) -> None:
        self.payload = payload
        self.fail = fail
        self.namespaces: list[str] = []

    def export_namespace(self, namespace: str, destination: io.BytesIO) -> None:
        self.namespaces.append(namespace)
        if self.fail:
            raise RuntimeError("postgresql://user:password@database/hbcb")
        destination.write(self.payload[:3])
        destination.write(self.payload[3:])


class ListedVersionsClient:
    def __init__(self, entries: tuple[object, ...], stats: dict[tuple[str, str], object]) -> None:
        self.entries = entries
        self.stats = stats
        self.list_calls = []

    def list_objects(self, bucket: str, **kwargs: object):
        self.list_calls.append((bucket, kwargs))
        return iter(self.entries)

    def stat_object(self, bucket: str, key: str, *, version_id: str):
        return self.stats[(key, version_id)]


class PolicyAndRetentionTests(unittest.TestCase):
    def test_defaults_integer_bounds_and_namespace(self) -> None:
        policy = RetentionPolicy()
        self.assertEqual(policy.succeeded_days, 30)
        self.assertEqual(policy.failed_days, 7)
        self.assertEqual(policy.canceled_days, 7)
        self.assertEqual(policy.needs_review_days, 7)
        self.assertEqual(policy.orphan_grace_days, 7)
        for invalid in (True, 0, 3651, 1.0, "7"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(MaintenanceError):
                    RetentionPolicy(succeeded_days=invalid)  # type: ignore[arg-type]
        self.assertEqual(validate_namespace("prod-east"), "prod-east")
        for invalid in ("../prod", "UPPER", "a" * 33, 7):
            with self.assertRaises(MaintenanceError):
                validate_namespace(invalid)

    def test_retention_is_dry_run_by_default_and_apply_is_explicit(self) -> None:
        store = FakeStore()
        service = MaintenanceService(store, namespace="local")
        preview = service.run_retention(now=NOW)
        self.assertTrue(preview.dry_run)
        self.assertEqual(len(preview.candidates), 2)
        self.assertEqual(store.retention_applies, [])

        applied = service.run_retention(now=NOW, apply=True)
        self.assertFalse(applied.dry_run)
        self.assertEqual(applied.deleted_build_ids, (BUILD_A, BUILD_B))
        self.assertEqual(applied.queued_artifact_versions, 1)
        self.assertEqual(store.retention_applies[0][2], (BUILD_A, BUILD_B))

    def test_store_output_cannot_smuggle_an_active_build(self) -> None:
        store = FakeStore()
        store.candidates = (
            SimpleNamespace(
                build_id=BUILD_A,
                status=BuildStatus.RUNNING,
                finished_at=NOW - timedelta(days=100),
            ),
        )
        with self.assertRaises(MaintenanceError):
            MaintenanceService(store, namespace="local").run_retention(now=NOW)


class DeletionAndRedisTests(unittest.TestCase):
    def test_deletion_dry_run_observes_seven_day_grace_without_claim_or_delete(self) -> None:
        store = FakeStore()
        store.preview = (deletion_item(),)
        objects = FakeObjects({})
        service = MaintenanceService(store, namespace="local", objects=objects)
        result = service.run_artifact_deletion(now=NOW)
        self.assertTrue(result.dry_run)
        self.assertEqual(result.considered, 1)
        self.assertEqual(store.claim_calls, [])
        self.assertEqual(objects.deleted, [])
        self.assertEqual(store.preview_calls[0][0], NOW - timedelta(days=7))

    def test_apply_deletes_only_exact_recorded_versions_and_records_both_outcomes(self) -> None:
        first = evidence(version_id="version-ok", payload=b"first")
        second = evidence(
            build_id=BUILD_B,
            name="model.glb",
            version_id="version-fail",
            payload=b"second",
        )
        store = FakeStore()
        store.preview = (
            deletion_item(queue_id=1, item_evidence=first),
            deletion_item(queue_id=2, item_evidence=second),
        )
        objects = FakeObjects({})
        objects.fail_delete.add("version-fail")
        service = MaintenanceService(
            store,
            namespace="local",
            objects=objects,
            uuid_factory=lambda: CLAIM,
        )
        result = service.run_artifact_deletion(now=NOW, apply=True)
        self.assertEqual((result.deleted, result.failed), (1, 1))
        self.assertEqual(
            objects.deleted,
            [
                (first.bucket, first.object_key, first.version_id),
                (second.bucket, second.object_key, second.version_id),
            ],
        )
        self.assertEqual(
            [(entry[2], entry[3]) for entry in store.deletion_attempts],
            [("deleted", None), ("failed", "storage_delete_failed")],
        )
        rendered = repr(store.deletion_attempts)
        self.assertNotIn("secret storage failure details", rendered)

    def test_redis_reconstruction_is_postgres_derived_and_dry_run_by_default(self) -> None:
        store = FakeStore()
        queue = FakeQueue()
        service = MaintenanceService(store, namespace="local", queue=queue)
        preview = service.reconstruct_redis()
        self.assertTrue(preview.dry_run)
        self.assertEqual(preview.derived_queued_builds, 2)
        self.assertEqual(queue.enqueued, [])
        applied = service.reconstruct_redis(apply=True)
        self.assertEqual(applied.enqueued, 2)
        self.assertEqual(queue.enqueued, [BUILD_A, BUILD_B])

    def test_redis_reconstruction_pages_past_one_thousand_without_truncation(self) -> None:
        store = FakeStore()
        store.queued_ids = tuple(UUID(int=index) for index in range(1, 1002))
        queue = FakeQueue()
        service = MaintenanceService(store, namespace="local", queue=queue)
        result = service.reconstruct_redis(apply=True, limit=1000)
        self.assertEqual(result.derived_queued_builds, 1001)
        self.assertEqual(result.enqueued, 1001)
        self.assertEqual(tuple(queue.enqueued), store.queued_ids)

    def test_orphan_discovery_is_bounded_dry_by_default_and_uses_object_age(self) -> None:
        item = stored_version()
        store = FakeStore()
        store.orphan_candidates = (item,)
        objects = FakeObjects({})
        objects.inventory = (item,)
        service = MaintenanceService(
            store,
            namespace="local",
            bucket="hbcb-artifacts",
            objects=objects,
        )
        result = service.discover_orphan_versions(now=NOW, limit=1, scan_limit=5)
        self.assertEqual((result.dry_run, result.scanned, result.candidates, result.queued), (True, 1, 1, 0))
        self.assertEqual(objects.inventory_calls, [("hbcb-artifacts", "local", 5)])
        self.assertEqual(store.orphan_calls[0][1], NOW - timedelta(days=7))
        self.assertFalse(store.orphan_calls[0][3])

        applied = service.discover_orphan_versions(now=NOW, apply=True, limit=1, scan_limit=5)
        self.assertEqual((applied.dry_run, applied.queued), (False, 1))
        self.assertTrue(store.orphan_calls[1][3])

    def test_orphan_discovery_rejects_fresh_or_uninventoried_store_candidates(self) -> None:
        old = stored_version()
        fresh = stored_version(version_id="fresh", modified=NOW - timedelta(hours=1))
        store = FakeStore()
        objects = FakeObjects({})
        objects.inventory = (old, fresh)
        service = MaintenanceService(
            store, namespace="local", bucket="hbcb-artifacts", objects=objects
        )
        store.orphan_candidates = (fresh,)
        with self.assertRaises(MaintenanceError) as captured:
            service.discover_orphan_versions(now=NOW)
        self.assertEqual(captured.exception.code, "invalid_orphan_result")

        store.orphan_candidates = (stored_version(version_id="not-listed"),)
        with self.assertRaises(MaintenanceError):
            service.discover_orphan_versions(now=NOW)

    def test_minio_inventory_consumes_all_versions_and_verifies_exact_evidence(self) -> None:
        first = stored_version(version_id="version-1", payload=b"one")
        second = stored_version(
            build_id=BUILD_B,
            name="model.glb",
            version_id="version-2",
            payload=b"two",
        )
        entries = tuple(
            SimpleNamespace(
                object_name=item.object_key,
                version_id=item.version_id,
                last_modified=item.last_modified,
                size=item.bytes,
                is_delete_marker=False,
            )
            for item in (first, second)
        )
        stats = {
            (item.object_key, item.version_id): SimpleNamespace(
                version_id=item.version_id,
                size=item.bytes,
                last_modified=item.last_modified,
                metadata={"x-amz-meta-sha256": item.sha256},
            )
            for item in (first, second)
        }
        client = ListedVersionsClient(entries, stats)
        inventoried = MinioVersionedObjectClient(client).inventory_namespace_versions(
            "hbcb-artifacts", "local", limit=2
        )
        self.assertEqual({item.identity for item in inventoried}, {first.identity, second.identity})
        self.assertEqual(
            client.list_calls[0][1],
            {
                "prefix": "local/v1/builds/",
                "recursive": True,
                "include_version": True,
            },
        )

    def test_minio_inventory_fails_closed_on_delete_marker_ambiguity_and_limit(self) -> None:
        item = stored_version()
        marker = SimpleNamespace(
            object_name=item.object_key,
            version_id="marker-version",
            last_modified=item.last_modified,
            size=0,
            is_delete_marker=True,
        )
        with self.assertRaises(MaintenanceError) as captured:
            MinioVersionedObjectClient(ListedVersionsClient((marker,), {})).inventory_namespace_versions(
                "hbcb-artifacts", "local", limit=1
            )
        self.assertEqual(captured.exception.code, "ambiguous_object_inventory")

        entry = SimpleNamespace(
            object_name=item.object_key,
            version_id=item.version_id,
            last_modified=item.last_modified,
            size=item.bytes,
            is_delete_marker=False,
        )
        stat_item = SimpleNamespace(
            version_id=item.version_id,
            size=item.bytes,
            last_modified=item.last_modified,
            metadata={"sha256": item.sha256},
        )
        client = ListedVersionsClient((entry, entry), {(item.object_key, item.version_id): stat_item})
        with self.assertRaises(MaintenanceError) as bounded:
            MinioVersionedObjectClient(client).inventory_namespace_versions(
                "hbcb-artifacts", "local", limit=1
            )
        self.assertEqual(bounded.exception.code, "object_inventory_too_large")

        ambiguous = SimpleNamespace(
            object_name=item.object_key,
            version_id="null",
            last_modified=item.last_modified,
            size=item.bytes,
            is_delete_marker=False,
        )
        with self.assertRaises(MaintenanceError) as unversioned:
            MinioVersionedObjectClient(
                ListedVersionsClient((ambiguous,), {})
            ).inventory_namespace_versions("hbcb-artifacts", "local", limit=1)
        self.assertEqual(unversioned.exception.code, "ambiguous_object_inventory")

    def test_minio_inventory_rejects_missing_or_changed_listing_evidence(self) -> None:
        item = stored_version()
        base = {
            "object_name": item.object_key,
            "version_id": item.version_id,
            "last_modified": item.last_modified,
            "size": item.bytes,
        }
        stat_item = SimpleNamespace(
            version_id=item.version_id,
            size=item.bytes,
            last_modified=item.last_modified,
            metadata={"sha256": item.sha256},
        )
        identity = (item.object_key, item.version_id)
        for entry in (
            SimpleNamespace(**base),
            SimpleNamespace(**base, is_delete_marker=None),
        ):
            with self.subTest(marker=getattr(entry, "is_delete_marker", "missing")):
                with self.assertRaises(MaintenanceError) as marker:
                    MinioVersionedObjectClient(
                        ListedVersionsClient((entry,), {identity: stat_item})
                    ).inventory_namespace_versions("hbcb-artifacts", "local", limit=1)
                self.assertEqual(marker.exception.code, "ambiguous_object_inventory")

        changed_stat = SimpleNamespace(
            version_id=item.version_id,
            size=item.bytes,
            last_modified=item.last_modified + timedelta(seconds=1),
            metadata={"sha256": item.sha256},
        )
        entry = SimpleNamespace(**base, is_delete_marker=False)
        with self.assertRaises(MaintenanceError) as changed:
            MinioVersionedObjectClient(
                ListedVersionsClient((entry,), {identity: changed_stat})
            ).inventory_namespace_versions("hbcb-artifacts", "local", limit=1)
        self.assertEqual(changed.exception.code, "object_inventory_changed")

        subsecond_stat = SimpleNamespace(
            version_id=item.version_id,
            size=item.bytes,
            last_modified=item.last_modified + timedelta(microseconds=500000),
            metadata={"sha256": item.sha256},
        )
        self.assertEqual(
            MinioVersionedObjectClient(
                ListedVersionsClient((entry,), {identity: subsecond_stat})
            ).inventory_namespace_versions("hbcb-artifacts", "local", limit=1)[0].identity,
            item.identity,
        )


class BackupRestoreTests(unittest.TestCase):
    def test_inventory_round_trip_and_exact_version_hash_validation(self) -> None:
        payload = b"exact model bytes"
        item = evidence(payload=payload)
        store = FakeStore()
        store.inventory = (item,)
        objects = FakeObjects({(item.bucket, item.object_key, item.version_id): payload})
        service = MaintenanceService(store, namespace="local", objects=objects)
        inventory = service.backup_inventory(now=NOW)
        restored = BackupInventory.from_json_bytes(inventory.to_json_bytes())
        self.assertEqual(restored, inventory)
        self.assertEqual(service.validate_backup(restored), 1)

        objects.versions[(item.bucket, item.object_key, item.version_id)] = b"wrong bytes"
        with self.assertRaises(MaintenanceError) as captured:
            service.validate_backup(restored)
        self.assertEqual(captured.exception.code, "artifact_evidence_mismatch")

    def test_inventory_parser_rejects_duplicates_extra_fields_and_unbounded_numbers(self) -> None:
        item = evidence()
        inventory = BackupInventory("local", NOW, (item,))
        payload = inventory.to_json_bytes().decode("ascii")
        duplicate = payload.replace('"namespace":"local"', '"namespace":"local","namespace":"local"', 1)
        with self.assertRaises(MaintenanceError):
            BackupInventory.from_json_bytes(duplicate.encode("ascii"))
        raw = json.loads(payload)
        raw["secret"] = "must-not-be-accepted"
        with self.assertRaises(MaintenanceError):
            BackupInventory.from_json_bytes(json.dumps(raw).encode("utf-8"))
        raw.pop("secret")
        raw["artifacts"][0]["bytes"] = 10**100
        with self.assertRaises(MaintenanceError):
            BackupInventory.from_json_bytes(json.dumps(raw).encode("utf-8"))

    def test_database_export_is_streamed_and_returns_only_hash_size_evidence(self) -> None:
        item = evidence()
        store = FakeStore()
        store.inventory = (item,)
        service = MaintenanceService(store, namespace="local")
        destination = io.BytesIO()
        exporter = FakeExporter(b"database-export")
        result = service.export_backup(exporter, destination, now=NOW)
        self.assertEqual(destination.getvalue(), b"database-export")
        self.assertEqual(result.database.sha256, hashlib.sha256(b"database-export").hexdigest())
        self.assertEqual(result.database.bytes, len(b"database-export"))
        self.assertEqual(exporter.namespaces, ["local"])
        self.assertNotIn("database-export", repr(result))

        with self.assertRaises(MaintenanceError) as captured:
            service.export_backup(FakeExporter(b"", fail=True), io.BytesIO(), now=NOW)
        self.assertEqual(captured.exception.code, "database_export_failed")
        self.assertNotIn("password", str(captured.exception))

    def test_restore_validates_new_exact_versions_then_remaps_postgres_only_on_apply(self) -> None:
        payload = b"restored bytes"
        original = evidence(version_id="old-version", payload=payload)
        inventory = BackupInventory("local", NOW, (original,))
        remap = VersionRemap(
            namespace="local",
            build_id=original.build_id,
            bucket=original.bucket,
            object_key=original.object_key,
            source_version_id=original.version_id,
            restored_version_id="new-version",
            sha256=original.sha256,
            bytes=original.bytes,
        )
        objects = FakeObjects({(original.bucket, original.object_key, "new-version"): payload})
        store = FakeStore()
        service = MaintenanceService(store, namespace="local", objects=objects)
        self.assertEqual(service.restore_version_ids(inventory, [remap]), (remap,))
        self.assertEqual(store.remap_calls, [])
        self.assertEqual(
            service.restore_version_ids(inventory, [remap], apply=True),
            (remap,),
        )
        self.assertEqual(store.remap_calls, [(remap,)])

        changed = VersionRemap(
            namespace="local",
            build_id=original.build_id,
            bucket=original.bucket,
            object_key=original.object_key,
            source_version_id=original.version_id,
            restored_version_id="other-version",
            sha256="f" * 64,
            bytes=original.bytes,
        )
        with self.assertRaises(MaintenanceError):
            service.restore_version_ids(inventory, [changed])

    def test_object_backup_exports_exact_versions_to_a_new_private_directory(self) -> None:
        payload = b"portable exact model bytes"
        item = evidence(payload=payload)
        store = FakeStore()
        store.inventory = (item,)
        objects = FakeObjects({(item.bucket, item.object_key, item.version_id): payload})
        service = MaintenanceService(
            store,
            namespace="local",
            bucket="hbcb-artifacts",
            objects=objects,
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "object-backup"
            result = service.export_object_backup(output, now=NOW)
            self.assertEqual((result.artifact_count, result.artifact_bytes), (1, len(payload)))
            self.assertEqual(
                result.inventory_sha256,
                hashlib.sha256((output / "inventory.json").read_bytes()).hexdigest(),
            )
            self.assertEqual((output / "objects" / "00000000.bin").read_bytes(), payload)
            self.assertEqual(stat.S_IMODE(output.lstat().st_mode), 0o700)
            self.assertEqual(
                stat.S_IMODE((output / "objects" / "00000000.bin").lstat().st_mode),
                0o600,
            )
            with self.assertRaises(MaintenanceError) as captured:
                service.export_object_backup(output, now=NOW)
            self.assertEqual(captured.exception.code, "backup_target_exists")

    def test_object_restore_is_dry_then_uploads_canonical_keys_and_remaps_once(self) -> None:
        payload = b"restorable exact bytes"
        item = evidence(version_id="source-version", payload=payload)
        source_store = FakeStore()
        source_store.inventory = (item,)
        source_objects = FakeObjects(
            {(item.bucket, item.object_key, item.version_id): payload}
        )
        with tempfile.TemporaryDirectory() as temporary:
            backup_path = Path(temporary) / "object-backup"
            MaintenanceService(
                source_store,
                namespace="local",
                bucket="hbcb-artifacts",
                objects=source_objects,
            ).export_object_backup(backup_path, now=NOW)

            restore_store = FakeStore()
            restore_objects = FakeObjects({})
            restore = MaintenanceService(
                restore_store,
                namespace="local",
                bucket="hbcb-artifacts",
                objects=restore_objects,
            )
            preview = restore.restore_object_backup(backup_path)
            self.assertTrue(preview.dry_run)
            self.assertEqual(preview.artifact_count, 1)
            self.assertEqual(restore_objects.uploaded, [])
            self.assertEqual(restore_store.remap_calls, [])

            applied = restore.restore_object_backup(backup_path, apply=True)
            self.assertFalse(applied.dry_run)
            self.assertEqual((applied.uploaded, applied.remapped), (1, 1))
            upload = restore_objects.uploaded[0]
            self.assertEqual(upload[:3], (item.bucket, item.object_key, payload))
            self.assertEqual(upload[3:], (item.bytes, item.sha256, "model/stl"))
            self.assertEqual(applied.remaps[0].source_version_id, "source-version")
            self.assertEqual(applied.remaps[0].restored_version_id, "restored-1")
            self.assertEqual(restore_store.remap_calls, [applied.remaps])
            self.assertEqual(
                restore_objects.inspected,
                [("hbcb-artifacts", "local"), ("hbcb-artifacts", "local")],
            )

    def test_object_restore_rejects_ambiguous_symlinked_or_writable_input(self) -> None:
        payload = b"safe bytes"
        item = evidence(payload=payload)
        store = FakeStore()
        store.inventory = (item,)
        objects = FakeObjects({(item.bucket, item.object_key, item.version_id): payload})
        with tempfile.TemporaryDirectory() as temporary:
            backup_path = Path(temporary) / "object-backup"
            service = MaintenanceService(store, namespace="local", objects=objects)
            service.export_object_backup(backup_path, now=NOW)

            link = Path(temporary) / "backup-link"
            link.symlink_to(backup_path, target_is_directory=True)
            with self.assertRaises(MaintenanceError) as linked:
                service.restore_object_backup(link)
            self.assertEqual(linked.exception.code, "unsafe_backup_path")

            extra = backup_path / "unexpected"
            extra.write_bytes(b"x")
            os.chmod(extra, 0o600)
            with self.assertRaises(MaintenanceError) as ambiguous:
                service.restore_object_backup(backup_path)
            self.assertEqual(ambiguous.exception.code, "ambiguous_backup")
            extra.unlink()

            object_path = backup_path / "objects" / "00000000.bin"
            os.chmod(object_path, 0o666)
            with self.assertRaises(MaintenanceError) as writable:
                service.restore_object_backup(backup_path)
            self.assertEqual(writable.exception.code, "unsafe_backup_mode")


class ScriptedCursor:
    def __init__(self, connection: "ScriptedConnection") -> None:
        self.connection = connection
        self.rows: list[tuple[object, ...]] = []
        self.rowcount = 0

    def execute(self, sql: str, parameters: object = None) -> None:
        normalized = " ".join(sql.split())
        self.connection.executions.append((normalized, parameters))
        self.rowcount = 0
        if normalized.startswith("SELECT b.id, b.status, b.finished_at FROM hbcb.builds"):
            self.rows = [(BUILD_A, "succeeded", NOW - timedelta(days=31))]
        elif normalized.startswith("SELECT COUNT(*) FROM hbcb.artifacts"):
            self.rows = [(1,)]
        elif normalized.startswith("SELECT COUNT(*) FROM hbcb.artifact_deletion_queue"):
            self.rows = [(1,)]
        elif normalized.startswith("DELETE FROM hbcb.builds"):
            self.rows = [(BUILD_A,)]
        elif normalized.startswith("SELECT id FROM hbcb.builds"):
            self.rows = [(BUILD_A,), (BUILD_B,)]
        else:
            self.rows = []

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def close(self) -> None:
        pass


class ScriptedConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def cursor(self) -> ScriptedCursor:
        return ScriptedCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed += 1


class PostgresOrderingTests(unittest.TestCase):
    def test_exact_versions_are_inserted_before_build_delete_in_one_transaction(self) -> None:
        connection = ScriptedConnection()
        store = PostgresMaintenanceStore(lambda: connection, namespace="local")
        result = store.queue_and_delete_builds(RetentionPolicy(), NOW, (BUILD_A,))
        self.assertEqual(result.deleted_build_ids, (BUILD_A,))
        statements = [sql for sql, _parameters in connection.executions]
        insert_index = next(
            index
            for index, sql in enumerate(statements)
            if sql.startswith("INSERT INTO hbcb.artifact_deletion_queue")
        )
        delete_index = next(
            index
            for index, sql in enumerate(statements)
            if sql.startswith("DELETE FROM hbcb.builds")
        )
        self.assertLess(insert_index, delete_index)
        insertion = statements[insert_index]
        for field in ("bucket", "object_key", "version_id", "sha256", "bytes"):
            self.assertIn(field, insertion)
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)

    def test_redis_reconstruction_query_uses_current_build_status_not_outbox(self) -> None:
        connection = ScriptedConnection()
        store = PostgresMaintenanceStore(lambda: connection, namespace="local")
        self.assertEqual(tuple(store.iter_queued_build_ids(100)), ((BUILD_A, BUILD_B),))
        self.assertEqual(
            connection.executions[0][0],
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        )
        sql = connection.executions[1][0]
        self.assertIn("FROM hbcb.builds", sql)
        self.assertIn("status = 'queued'", sql)
        self.assertIn("ORDER BY id", sql)
        self.assertNotIn("queue_outbox", sql)

    def test_orphan_claim_query_rechecks_active_builds_and_exact_references(self) -> None:
        connection = ScriptedConnection()
        store = PostgresMaintenanceStore(lambda: connection, namespace="local")
        store.claim_deletions(
            NOW - timedelta(days=7),
            NOW,
            100,
            CLAIM,
            NOW + timedelta(minutes=15),
        )
        sql = connection.executions[0][0]
        self.assertIn("LEFT JOIN hbcb.builds", sql)
        self.assertIn("NOT EXISTS", sql)
        self.assertIn("FROM hbcb.artifacts", sql)
        self.assertIn("build.id IS NULL OR build.status NOT IN", sql)
        self.assertIn("FOR UPDATE OF queue SKIP LOCKED", sql)


class CommandTests(unittest.TestCase):
    def test_retain_alias_uses_bounded_environment_defaults_and_stays_dry(self) -> None:
        store = FakeStore()
        store.candidates = (
            RetentionCandidate(
                BUILD_A,
                BuildStatus.SUCCEEDED,
                NOW - timedelta(days=41),
                1,
                10,
            ),
            RetentionCandidate(
                BUILD_B,
                BuildStatus.FAILED,
                NOW - timedelta(days=10),
                0,
                0,
            ),
        )
        service = MaintenanceService(store, namespace="local")
        output = io.StringIO()
        code = run(
            ["retain"],
            environment={
                "HBCB_RETENTION_SUCCEEDED_DAYS": "40",
                "HBCB_RETENTION_OTHER_DAYS": "9",
                "HBCB_ORPHAN_GRACE_DAYS": "8",
            },
            service_factory=lambda _environment: service,
            stdout=output,
        )
        self.assertEqual(code, 0)
        rendered = json.loads(output.getvalue())
        self.assertTrue(rendered["dry_run"])
        self.assertEqual(store.retention_applies, [])
        policy = store.retention_selects[0][0]
        self.assertEqual(
            (
                policy.succeeded_days,
                policy.failed_days,
                policy.canceled_days,
                policy.needs_review_days,
                policy.orphan_grace_days,
            ),
            (40, 9, 9, 9, 8),
        )

    def test_retention_alias_apply_and_redis_command_are_explicit(self) -> None:
        store = FakeStore()
        queue = FakeQueue()
        service = MaintenanceService(store, namespace="local", queue=queue)
        self.assertEqual(
            run(
                ["retention", "--apply"],
                environment={},
                service_factory=lambda _environment: service,
                stdout=io.StringIO(),
            ),
            0,
        )
        self.assertEqual(len(store.retention_applies), 1)
        self.assertEqual(
            run(
                ["reconstruct-redis"],
                environment={},
                service_factory=lambda _environment: service,
                stdout=io.StringIO(),
            ),
            0,
        )
        self.assertEqual(queue.enqueued, [])
        self.assertEqual(
            run(
                ["reconstruct-redis", "--apply"],
                environment={},
                service_factory=lambda _environment: service,
                stdout=io.StringIO(),
            ),
            0,
        )
        self.assertEqual(queue.enqueued, [BUILD_A, BUILD_B])

    def test_command_errors_emit_only_stable_codes(self) -> None:
        error = io.StringIO()
        code = run(
            ["retain"],
            environment={},
            service_factory=lambda _environment: (_ for _ in ()).throw(
                MaintenanceError("database_unavailable", "fixed safe message")
            ),
            stdout=io.StringIO(),
            stderr=error,
        )
        self.assertEqual(code, 1)
        self.assertEqual(
            json.loads(error.getvalue()),
            {"error": {"code": "database_unavailable"}, "ok": False},
        )

    def test_orphan_command_is_dry_by_default_and_apply_is_explicit(self) -> None:
        item = stored_version()
        store = FakeStore()
        store.orphan_candidates = (item,)
        objects = FakeObjects({})
        objects.inventory = (item,)
        service = MaintenanceService(
            store,
            namespace="local",
            bucket="hbcb-artifacts",
            objects=objects,
        )
        preview_output = io.StringIO()
        self.assertEqual(
            run(
                ["discover-orphans", "--limit", "1", "--scan-limit", "5"],
                environment={"HBCB_ORPHAN_GRACE_DAYS": "7"},
                service_factory=lambda _environment: service,
                stdout=preview_output,
            ),
            0,
        )
        self.assertEqual(
            json.loads(preview_output.getvalue()),
            {"candidates": 1, "dry_run": True, "queued": 0, "scanned": 1},
        )
        apply_output = io.StringIO()
        self.assertEqual(
            run(
                ["discover-orphans", "--apply", "--limit", "1", "--scan-limit", "5"],
                environment={},
                service_factory=lambda _environment: service,
                stdout=apply_output,
            ),
            0,
        )
        self.assertEqual(json.loads(apply_output.getvalue())["queued"], 1)

    def test_command_clock_injection_reaches_grace_period_decisions(self) -> None:
        item = stored_version()
        store = FakeStore()
        store.orphan_candidates = (item,)
        objects = FakeObjects({})
        objects.inventory = (item,)
        service = MaintenanceService(
            store,
            namespace="local",
            bucket="hbcb-artifacts",
            objects=objects,
        )
        self.assertEqual(
            run(
                ["discover-orphans", "--orphan-grace-days", "3"],
                environment={},
                service_factory=lambda _environment: service,
                stdout=io.StringIO(),
                now=NOW,
            ),
            0,
        )
        self.assertEqual(store.orphan_calls[0][1:3], (NOW - timedelta(days=3), NOW))

        self.assertEqual(
            run(
                ["delete-artifacts", "--orphan-grace-days", "2"],
                environment={},
                service_factory=lambda _environment: service,
                stdout=io.StringIO(),
                now=NOW,
            ),
            0,
        )
        self.assertEqual(store.preview_calls[0][:2], (NOW - timedelta(days=2), NOW))

    def test_object_backup_and_restore_commands_require_explicit_paths_and_apply(self) -> None:
        payload = b"command backup bytes"
        item = evidence(payload=payload)
        store = FakeStore()
        store.inventory = (item,)
        objects = FakeObjects({(item.bucket, item.object_key, item.version_id): payload})
        service = MaintenanceService(
            store,
            namespace="local",
            bucket="hbcb-artifacts",
            objects=objects,
        )
        with tempfile.TemporaryDirectory() as temporary:
            backup_path = Path(temporary) / "backup"
            backup_output = io.StringIO()
            self.assertEqual(
                run(
                    ["backup-export", "--output", str(backup_path)],
                    environment={},
                    service_factory=lambda _environment: service,
                    stdout=backup_output,
                ),
                0,
            )
            self.assertEqual(json.loads(backup_output.getvalue())["artifacts"], 1)

            restore_output = io.StringIO()
            self.assertEqual(
                run(
                    ["restore-objects", "--input", str(backup_path)],
                    environment={},
                    service_factory=lambda _environment: service,
                    stdout=restore_output,
                ),
                0,
            )
            self.assertTrue(json.loads(restore_output.getvalue())["dry_run"])
            self.assertEqual(objects.uploaded, [])

            apply_output = io.StringIO()
            self.assertEqual(
                run(
                    ["restore-objects", "--input", str(backup_path), "--apply"],
                    environment={},
                    service_factory=lambda _environment: service,
                    stdout=apply_output,
                ),
                0,
            )
            self.assertEqual(json.loads(apply_output.getvalue())["remapped"], 1)


if __name__ == "__main__":
    unittest.main()
