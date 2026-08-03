from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from hbcb_service.api import create_app
from hbcb_service.errors import StorageError
from hbcb_service.models import REQUIRED_PUBLISHED_ARTIFACTS, BuildStatus
from hbcb_service.state import InMemoryStateStore
from hbcb_service.storage import InMemoryArtifactStorage
from hbcb_service.structured_log import StructuredLogger

try:
    from .g6_support import facet_request_bytes, moss_request_bytes
    from .support import artifact_records, running_attempt, write_artifact_files
except ImportError:
    from g6_support import facet_request_bytes, moss_request_bytes
    from support import artifact_records, running_attempt, write_artifact_files


TOKEN = "a" * 64
AUTH = {"Authorization": "Bearer " + TOKEN}


class ApiFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.state = InMemoryStateStore(idempotency_secret=b"s" * 32)
        self.storage = InMemoryArtifactStorage(
            namespace="local",
            bucket="hbcb-artifacts",
            public_base_url="http://public-storage.local:9000",
        )
        self.log_stream = io.StringIO()
        app = create_app(
            repository=self.state,
            storage=self.storage,
            configured_token=TOKEN,
            signed_url_ttl_seconds=300,
            readiness=lambda: True,
            logger=StructuredLogger(self.log_stream),
        )
        self.client = TestClient(app, raise_server_exceptions=False)

    def post_build(
        self,
        payload: bytes | None = None,
        *,
        key: str | None = "facet-request-0001",
        headers: dict[str, str] | None = None,
    ):
        supplied = dict(AUTH)
        supplied["Content-Type"] = "application/json"
        if key is not None:
            supplied["Idempotency-Key"] = key
        if headers:
            supplied.update(headers)
        return self.client.post(
            "/v1/builds",
            content=facet_request_bytes() if payload is None else payload,
            headers=supplied,
        )

    def publish(self, build_id_text: str) -> None:
        from uuid import UUID

        build_id = UUID(build_id_text)
        queued = self.state.get_build(build_id)
        running = self.state.transition(
            build_id,
            queued.state_version,
            BuildStatus.RUNNING,
        )
        attempt = running_attempt(build_id=build_id)
        self.state.register_running_attempt(attempt)
        records = artifact_records(
            build_id=build_id,
            attempt_id=attempt.attempt_id,
            version_id=None,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_artifact_files(root, records)
            stored = tuple(
                self.storage.store_file(record, root / record.relative_path)
                for record in records
            )
        self.state.publish_success(build_id, running.state_version, stored)


class SubmissionApiTests(ApiFixture):
    def test_new_build_is_async_and_idempotent_replay_is_200(self) -> None:
        first = self.post_build()
        self.assertEqual(first.status_code, 202)
        document = first.json()
        self.assertEqual(document["status"], "queued")
        self.assertEqual(first.headers["location"], f"/v1/builds/{document['build_id']}")
        self.assertEqual(len(self.state.pending_outbox()), 1)

        replay = self.post_build()
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["build_id"], document["build_id"])
        self.assertEqual(len(self.state.pending_outbox()), 1)
        log = self.log_stream.getvalue()
        self.assertNotIn("facet-request-0001", log)
        self.assertNotIn(facet_request_bytes().decode("utf-8"), log)

    def test_idempotency_conflict_and_no_key_behavior(self) -> None:
        first = self.post_build()
        conflict = self.post_build(moss_request_bytes())
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "idempotency_conflict")
        self.assertEqual(len(self.state.pending_outbox()), 1)

        without_key_a = self.post_build(key=None)
        without_key_b = self.post_build(key=None)
        self.assertEqual(without_key_a.status_code, 202)
        self.assertEqual(without_key_b.status_code, 202)
        self.assertNotEqual(
            without_key_a.json()["build_id"], without_key_b.json()["build_id"]
        )

    def test_response_hides_internal_state_and_has_no_store_request_id(self) -> None:
        response = self.post_build()
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertRegex(
            response.headers["x-request-id"],
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        )
        forbidden = {
            "canonical_request",
            "manifest_object_key",
            "worker_id",
            "lease_token",
            "database_url",
        }
        self.assertFalse(forbidden & set(response.json()))


class StrictInputAndAuthorizationTests(ApiFixture):
    def test_authentication_precedes_body_processing_and_is_uniform(self) -> None:
        huge = b"{" + (b"x" * (64 * 1024 + 1))
        response = self.client.post(
            "/v1/builds",
            content=huge,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")
        self.assertEqual(response.json()["error"]["code"], "unauthorized")

        wrong = self.client.get(
            "/v1/builds/11111111-1111-4111-8111-111111111111",
            headers={"Authorization": "Bearer " + ("b" * 64)},
        )
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json()["error"]["code"], "unauthorized")

    def test_duplicate_auth_and_idempotency_headers_are_rejected(self) -> None:
        duplicate_auth = self.client.get(
            "/readyz",
            headers=[
                ("Authorization", "Bearer " + TOKEN),
                ("Authorization", "Bearer " + TOKEN),
            ],
        )
        self.assertEqual(duplicate_auth.status_code, 401)
        duplicate_key = self.client.post(
            "/v1/builds",
            content=facet_request_bytes(),
            headers=[
                ("Authorization", "Bearer " + TOKEN),
                ("Content-Type", "application/json"),
                ("Idempotency-Key", "facet-request-0001"),
                ("Idempotency-Key", "facet-request-0001"),
            ],
        )
        self.assertEqual(duplicate_key.status_code, 400)

    def test_size_media_encoding_and_contract_errors_are_distinct(self) -> None:
        oversized = self.post_build(b" " * (64 * 1024 + 1))
        self.assertEqual(oversized.status_code, 413)
        duplicate_json = self.post_build(b'{"a":1,"a":2}')
        self.assertEqual(duplicate_json.status_code, 400)
        self.assertEqual(duplicate_json.json()["error"]["code"], "duplicate_key")
        invalid_utf8 = self.post_build(b'{"name":"\xff"}')
        self.assertEqual(invalid_utf8.status_code, 400)
        self.assertEqual(invalid_utf8.json()["error"]["code"], "invalid_utf8")

        parsed = json.loads(facet_request_bytes())
        parsed["unexpected"] = True
        extra = self.post_build(json.dumps(parsed).encode("utf-8"))
        self.assertEqual(extra.status_code, 422)
        self.assertIsNotNone(extra.json()["error"]["path"])

        wrong_media = self.client.post(
            "/v1/builds",
            content=facet_request_bytes(),
            headers={**AUTH, "Content-Type": "text/plain"},
        )
        self.assertEqual(wrong_media.status_code, 415)
        compressed = self.post_build(
            headers={"Content-Encoding": "gzip"},
        )
        self.assertEqual(compressed.status_code, 415)

    def test_invalid_uuid_route_and_method_use_error_envelope(self) -> None:
        unauthenticated = self.client.get("/v1/builds/not-a-uuid")
        self.assertEqual(unauthenticated.status_code, 401)
        invalid = self.client.get("/v1/builds/not-a-uuid", headers=AUTH)
        self.assertEqual(invalid.status_code, 422)
        self.assertIn("request_id", invalid.json()["error"])
        missing = self.client.get("/no-such-route")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "route_not_found")
        wrong_method = self.client.put("/healthz")
        self.assertEqual(wrong_method.status_code, 405)


class HealthArtifactAndCancellationTests(ApiFixture):
    def test_health_is_public_and_readiness_is_private(self) -> None:
        health = self.client.get("/healthz")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ok"})
        self.assertEqual(self.client.get("/readyz").status_code, 401)
        self.assertEqual(self.client.get("/readyz", headers=AUTH).status_code, 200)

        app = create_app(
            repository=self.state,
            storage=self.storage,
            configured_token=TOKEN,
            signed_url_ttl_seconds=300,
            readiness=lambda: False,
        )
        unavailable = TestClient(app, raise_server_exceptions=False).get(
            "/readyz", headers=AUTH
        )
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable.json()["error"]["code"], "service_not_ready")

    def test_artifacts_are_hidden_until_exact_immutable_success(self) -> None:
        created = self.post_build()
        build_id = created.json()["build_id"]
        pending = self.client.get(
            f"/v1/builds/{build_id}/artifacts",
            headers=AUTH,
        )
        self.assertEqual(pending.status_code, 409)
        self.assertEqual(pending.json()["error"]["code"], "artifacts_not_ready")

        self.publish(build_id)
        published = self.client.get(
            f"/v1/builds/{build_id}/artifacts",
            headers=AUTH,
        )
        self.assertEqual(published.status_code, 200)
        artifacts = published.json()["artifacts"]
        self.assertEqual(
            [artifact["path"] for artifact in artifacts],
            list(REQUIRED_PUBLISHED_ARTIFACTS),
        )
        self.assertTrue(all("versionId=sha256-" in item["download_url"] for item in artifacts))
        self.assertTrue(
            all(item["download_url"].startswith("http://public-storage.local:9000/") for item in artifacts)
        )

    def test_queued_and_running_cancellation_semantics(self) -> None:
        queued = self.post_build(key="queued-cancel-0001")
        queued_id = queued.json()["build_id"]
        canceled = self.client.post(f"/v1/builds/{queued_id}/cancel", headers=AUTH)
        self.assertEqual(canceled.status_code, 200)
        self.assertEqual(canceled.json()["status"], "canceled")
        replay = self.client.post(f"/v1/builds/{queued_id}/cancel", headers=AUTH)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["state_version"], canceled.json()["state_version"])

        running_response = self.post_build(key="running-cancel-0001")
        from uuid import UUID

        running_id = UUID(running_response.json()["build_id"])
        queued_build = self.state.get_build(running_id)
        self.state.transition(running_id, queued_build.state_version, BuildStatus.RUNNING)
        requested = self.client.post(f"/v1/builds/{running_id}/cancel", headers=AUTH)
        self.assertEqual(requested.status_code, 202)
        self.assertIsNotNone(requested.json()["cancel_requested_at"])
        repeated = self.client.post(f"/v1/builds/{running_id}/cancel", headers=AUTH)
        self.assertEqual(repeated.status_code, 202)
        self.assertEqual(repeated.json()["state_version"], requested.json()["state_version"])

    def test_successful_build_cannot_be_canceled(self) -> None:
        created = self.post_build(key="successful-cancel-0001")
        build_id = created.json()["build_id"]
        self.publish(build_id)
        response = self.client.post(f"/v1/builds/{build_id}/cancel", headers=AUTH)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "terminal_build")

    def test_cancel_rejects_any_body(self) -> None:
        created = self.post_build(key="cancel-body-0001")
        build_id = created.json()["build_id"]
        response = self.client.post(
            f"/v1/builds/{build_id}/cancel",
            content=b"{}",
            headers=AUTH,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "unexpected_body")

    def test_signing_failure_returns_no_partial_artifact_document(self) -> None:
        created = self.post_build(key="signing-failure-0001")
        build_id = created.json()["build_id"]
        self.publish(build_id)

        class FailingSigner:
            def __init__(self, delegate: object) -> None:
                self.delegate = delegate
                self.calls = 0

            def presign_get(self, record: object, *, expires_seconds: int) -> str:
                self.calls += 1
                if self.calls == 5:
                    raise StorageError("signing_failed", "signed URL could not be generated")
                return self.delegate.presign_get(  # type: ignore[attr-defined]
                    record,
                    expires_seconds=expires_seconds,
                )

        app = create_app(
            repository=self.state,
            storage=FailingSigner(self.storage),  # type: ignore[arg-type]
            configured_token=TOKEN,
            signed_url_ttl_seconds=300,
            readiness=lambda: True,
        )
        response = TestClient(app, raise_server_exceptions=False).get(
            f"/v1/builds/{build_id}/artifacts",
            headers=AUTH,
        )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("download_url", response.text)


class UnexpectedFailureTests(unittest.TestCase):
    def test_unexpected_error_is_generic_and_secret_free(self) -> None:
        class FailingRepository:
            def submit(self, _payload: bytes, _key: str | None):
                raise RuntimeError("canary-secret-database-detail")

        stream = io.StringIO()
        app = create_app(
            repository=FailingRepository(),  # type: ignore[arg-type]
            storage=object(),  # type: ignore[arg-type]
            configured_token=TOKEN,
            signed_url_ttl_seconds=300,
            readiness=lambda: True,
            logger=StructuredLogger(stream),
        )
        response = TestClient(app, raise_server_exceptions=False).post(
            "/v1/builds",
            content=facet_request_bytes(),
            headers={
                **AUTH,
                "Content-Type": "application/json",
                "Idempotency-Key": "failing-request-0001",
            },
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "internal_error")
        self.assertNotIn("canary-secret", response.text)
        self.assertNotIn("canary-secret", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
