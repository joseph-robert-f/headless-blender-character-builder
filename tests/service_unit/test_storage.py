from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from hbcb_service.auth import authorize_bearer
from hbcb_service.errors import AuthorizationError, StorageError
from hbcb_service.models import REQUIRED_PUBLISHED_ARTIFACTS, BuildStatus
from hbcb_service.state import InMemoryStateStore
from hbcb_service.storage import (
    InMemoryArtifactStorage,
    MinioArtifactStorage,
    artifact_object_key,
    publication_order,
)

try:
    from .support import (
        BUILD_ID,
        FIXED_NOW,
        artifact_records,
        facet_request_bytes,
        running_attempt,
        write_artifact_files,
    )
except ImportError:  # Direct ``unittest -s tests/service_unit`` discovery.
    from support import (
        BUILD_ID,
        FIXED_NOW,
        artifact_records,
        facet_request_bytes,
        running_attempt,
        write_artifact_files,
    )


class NotFound(Exception):
    code = "NoSuchKey"


class FakeMinio:
    def __init__(self, *, public: bool = False) -> None:
        self.objects = {}
        self.public = public
        self.put_calls = []
        self.bucket_present = True
        self.versioning_enabled = True

    def bucket_exists(self, bucket: str) -> bool:
        self.bucket_checked = bucket
        return self.bucket_present

    def get_bucket_versioning(self, bucket: str) -> object:
        return SimpleNamespace(status="Enabled" if self.versioning_enabled else "Suspended")

    def stat_object(self, bucket: str, key: str, *, version_id: str | None = None) -> object:
        try:
            observed = self.objects[(bucket, key)]
        except KeyError as exc:
            raise NotFound() from exc
        if version_id is not None and observed.version_id != version_id:
            raise NotFound()
        return observed

    def put_object(
        self,
        bucket: str,
        key: str,
        stream: object,
        length: int,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> object:
        payload = stream.read()
        self.put_calls.append((bucket, key, length, content_type, dict(metadata), payload))
        self.objects[(bucket, key)] = SimpleNamespace(
            size=len(payload),
            metadata={"x-amz-meta-sha256": metadata["sha256"]},
            etag="not-a-sha256-etag",
            version_id="v1",
            payload=payload,
        )
        return SimpleNamespace(etag="ignored", version_id="v1")

    def remove_object(self, bucket: str, key: str, *, version_id: str | None = None) -> None:
        observed = self.objects.get((bucket, key))
        if observed is not None and (version_id is None or observed.version_id == version_id):
            self.objects.pop((bucket, key), None)

    def get_object(self, bucket: str, key: str, *, version_id: str) -> object:
        observed = self.stat_object(bucket, key, version_id=version_id)
        response = io.BytesIO(observed.payload)
        response.release_conn = lambda: None
        return response

    def presigned_get_object(
        self, bucket: str, key: str, *, expires: object, version_id: str
    ) -> str:
        self.presign_arguments = (bucket, key, expires, version_id)
        return f"http://localhost:9000/{bucket}/{key}?signed=yes"


class MutatingFakeMinio(FakeMinio):
    def __init__(self, source: Path) -> None:
        super().__init__()
        self.source = source

    def put_object(self, *args: object, **kwargs: object) -> object:
        payload = self.source.read_bytes()
        self.source.write_bytes(bytes([payload[0] ^ 1]) + payload[1:])
        return super().put_object(*args, **kwargs)



class StorageKeyAndOrderTests(unittest.TestCase):
    def test_keys_are_generated_only_from_bounded_identifiers_and_allowlist(self) -> None:
        build_id = uuid4()
        attempt_id = uuid4()
        key = artifact_object_key("local", build_id, attempt_id, "diagnostics/front.png")
        self.assertEqual(
            key,
            f"local/v1/builds/{build_id}/attempts/{attempt_id}/complete-v1/diagnostics/front.png",
        )
        for namespace in ("", "UPPER", "../escape", "a" * 33):
            with self.assertRaises(StorageError):
                artifact_object_key(namespace, build_id, attempt_id, "model.stl")
        for path in ("../model.stl", "/tmp/model.stl", "unknown.bin", "model.stl/extra"):
            with self.assertRaises(StorageError):
                artifact_object_key("local", build_id, attempt_id, path)

    def test_exact_publication_order_always_places_manifest_last(self) -> None:
        records = artifact_records(version_id=None)
        ordered = publication_order(tuple(reversed(records)))
        self.assertEqual(ordered[-1].relative_path, "manifest.json")
        self.assertEqual(
            {record.relative_path for record in ordered}, set(REQUIRED_PUBLISHED_ARTIFACTS)
        )
        with self.assertRaises(StorageError):
            publication_order(records[:-1])
        with self.assertRaises(StorageError):
            publication_order(records + (records[0],))
        foreign = replace(records[0], attempt_id=uuid4())
        with self.assertRaises(StorageError):
            publication_order((foreign,) + records[1:])


class InMemoryStorageTests(unittest.TestCase):
    def test_store_is_hash_verified_immutable_and_idempotent(self) -> None:
        records = artifact_records(version_id=None)
        record = records[0]
        storage = InMemoryArtifactStorage(
            namespace="local", bucket="hbcb-artifacts", public_base_url="http://localhost:9000"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_artifact_files(root, (record,))
            stored = storage.store_file(record, root / record.relative_path)
            replay = storage.store_file(record, root / record.relative_path)
            self.assertEqual(stored, replay)
            self.assertEqual(stored.version_id, "sha256-" + record.sha256)
            self.assertEqual(storage.payload(record.object_key), (record.relative_path + "\n").encode())
            changed_payload = b"changed payload\n"
            changed_path = root / "changed"
            changed_path.write_bytes(changed_payload)
            changed = replace(
                record,
                sha256=hashlib.sha256(changed_payload).hexdigest(),
                bytes=len(changed_payload),
            )
            with self.assertRaises(StorageError) as conflict:
                storage.store_file(changed, changed_path)
            self.assertEqual(conflict.exception.code, "immutable_object_conflict")

    def test_symlink_directory_size_and_hash_changes_fail_closed(self) -> None:
        record = artifact_records(version_id=None)[0]
        storage = InMemoryArtifactStorage(
            namespace="local", bucket="hbcb-artifacts", public_base_url="http://localhost:9000"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.write_bytes((record.relative_path + "\n").encode())
            link = root / "link"
            link.symlink_to(source)
            with self.assertRaises(StorageError):
                storage.store_file(record, link)
            with self.assertRaises(StorageError):
                storage.store_file(record, root)
            wrong_size = replace(record, bytes=record.bytes + 1)
            with self.assertRaises(StorageError):
                storage.store_file(wrong_size, source)
            wrong_hash = replace(record, sha256="f" * 64)
            with self.assertRaises(StorageError):
                storage.store_file(wrong_hash, source)

    def test_signed_url_is_short_lived_and_caller_authorizes_first(self) -> None:
        token = "a" * 64
        record = artifact_records(version_id=None)[0]
        storage = InMemoryArtifactStorage(
            namespace="local", bucket="hbcb-artifacts", public_base_url="http://localhost:9000"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_artifact_files(root, (record,))
            stored = storage.store_file(record, root / record.relative_path)
        with self.assertRaises(AuthorizationError):
            authorize_bearer("Bearer " + ("b" * 64), token)
        authorize_bearer("Bearer " + token, token)
        url = storage.presign_get(stored, expires_seconds=300)
        self.assertIn("expires=300", url)
        self.assertIn("versionId=sha256-", url)
        for ttl in (29, 901):
            with self.assertRaises(StorageError):
                storage.presign_get(stored, expires_seconds=ttl)

    def test_stored_versions_are_accepted_by_atomic_success_publication(self) -> None:
        state = InMemoryStateStore(
            idempotency_secret=b"s" * 32,
            now=lambda: FIXED_NOW,
            build_id_factory=lambda: BUILD_ID,
        )
        queued = state.submit(facet_request_bytes(), "facet-request-0001").build
        running = state.transition(BUILD_ID, queued.state_version, BuildStatus.RUNNING)
        state.register_running_attempt(running_attempt())
        storage = InMemoryArtifactStorage(
            namespace="local",
            bucket="hbcb-artifacts",
            public_base_url="http://localhost:9000",
        )
        records = artifact_records(version_id=None)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_artifact_files(root, records)
            stored = tuple(
                storage.store_file(record, root / record.relative_path)
                for record in records
            )
        succeeded = state.publish_success(BUILD_ID, running.state_version, stored)
        self.assertEqual(succeeded.status, BuildStatus.SUCCEEDED)
        self.assertTrue(all(record.version_id for record in stored))
        self.assertIn(
            "versionId=sha256-",
            storage.presign_get(stored[-1], expires_seconds=300),
        )


class MinioAdapterTests(unittest.TestCase):
    def test_bucket_must_exist_and_upload_is_verified_by_size_and_sha_metadata(self) -> None:
        internal = FakeMinio()
        signer = FakeMinio(public=True)
        adapter = MinioArtifactStorage(
            internal,
            signer,
            namespace="local",
            bucket="hbcb-artifacts",
        )
        adapter.require_bucket()
        internal.bucket_present = False
        with self.assertRaises(StorageError):
            adapter.require_bucket()
        internal.bucket_present = True
        internal.versioning_enabled = False
        with self.assertRaises(StorageError) as versioning:
            adapter.require_bucket()
        self.assertEqual(versioning.exception.code, "bucket_versioning_required")
        internal.versioning_enabled = True
        record = artifact_records(version_id=None)[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_artifact_files(root, (record,))
            stored = adapter.store_file(record, root / record.relative_path)
            replay = adapter.store_file(record, root / record.relative_path)
        self.assertEqual(stored, replay)
        self.assertEqual(stored.sha256, record.sha256)
        self.assertEqual(stored.etag, "not-a-sha256-etag")
        self.assertNotEqual(stored.etag, stored.sha256)
        self.assertEqual(len(internal.put_calls), 1)
        self.assertEqual(internal.put_calls[0][4], {"sha256": record.sha256})

    def test_existing_different_object_and_noncanonical_record_fail(self) -> None:
        internal = FakeMinio()
        adapter = MinioArtifactStorage(
            internal,
            FakeMinio(public=True),
            namespace="local",
            bucket="hbcb-artifacts",
        )
        record = artifact_records(version_id=None)[0]
        internal.objects[(record.bucket, record.object_key)] = SimpleNamespace(
            size=record.bytes,
            metadata={"x-amz-meta-sha256": "f" * 64},
            etag="etag",
            version_id=None,
            payload=(record.relative_path + "\n").encode(),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_artifact_files(root, (record,))
            with self.assertRaises(StorageError) as conflict:
                adapter.store_file(record, root / record.relative_path)
        self.assertEqual(conflict.exception.code, "immutable_object_conflict")
        with self.assertRaises(StorageError):
            adapter.presign_get(replace(record, object_key="local/wrong"), expires_seconds=300)

    def test_exact_streamed_bytes_are_hashed_and_invalid_upload_is_never_published(self) -> None:
        record = artifact_records(version_id=None)[0]
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / record.relative_path
            source.write_bytes((record.relative_path + "\n").encode())
            internal = MutatingFakeMinio(source)
            adapter = MinioArtifactStorage(
                internal,
                FakeMinio(public=True),
                namespace="local",
                bucket="hbcb-artifacts",
            )
            with self.assertRaises(StorageError) as captured:
                adapter.store_file(record, source)
        self.assertEqual(captured.exception.code, "artifact_hash_mismatch")
        # The low-privilege worker deliberately has no DeleteObjectVersion
        # permission. A bad upload remains an unreferenced version for the
        # separate retention janitor; it is never returned as published.
        self.assertIn((record.bucket, record.object_key), internal.objects)

    def test_forged_sha_metadata_cannot_hide_a_different_object_body(self) -> None:
        record = artifact_records(version_id=None)[0]
        internal = FakeMinio()
        forged_payload = bytes([ord("x")]) * record.bytes
        internal.objects[(record.bucket, record.object_key)] = SimpleNamespace(
            size=record.bytes,
            metadata={"x-amz-meta-sha256": record.sha256},
            etag="etag",
            version_id="forged-version",
            payload=forged_payload,
        )
        adapter = MinioArtifactStorage(
            internal,
            FakeMinio(public=True),
            namespace="local",
            bucket="hbcb-artifacts",
        )
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / record.relative_path
            source.write_bytes((record.relative_path + "\n").encode())
            with self.assertRaises(StorageError) as captured:
                adapter.store_file(record, source)
        self.assertEqual(captured.exception.code, "immutable_object_conflict")

    def test_public_signing_client_controls_returned_endpoint(self) -> None:
        signer = FakeMinio(public=True)
        adapter = MinioArtifactStorage(
            FakeMinio(), signer, namespace="local", bucket="hbcb-artifacts"
        )
        record = artifact_records(version_id=None)[0]
        versioned = replace(record, version_id="v1")
        value = adapter.presign_get(versioned, expires_seconds=300)
        self.assertTrue(value.startswith("http://localhost:9000/"))
        self.assertEqual(signer.presign_arguments[2].total_seconds(), 300)
        self.assertEqual(signer.presign_arguments[3], "v1")
        with self.assertRaises(StorageError):
            adapter.presign_get(record, expires_seconds=300)
