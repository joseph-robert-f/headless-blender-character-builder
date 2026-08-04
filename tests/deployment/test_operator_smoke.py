from __future__ import annotations

import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "operator-smoke"
LOADER = importlib.machinery.SourceFileLoader("operator_smoke_under_test", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
operator_smoke = importlib.util.module_from_spec(SPEC)
sys.modules[LOADER.name] = operator_smoke
LOADER.exec_module(operator_smoke)


TOKEN = "t" * 64
SIGNATURE_CANARY = "c" * 64
BUILD_ID = "11111111-1111-4111-8111-111111111111"
TIMESTAMP = "2026-08-03T12:00:00.000Z"


def sigv4_query(*, expires: int = 300, signature: str = SIGNATURE_CANARY) -> str:
    return urllib.parse.urlencode(
        {
            "versionId": "opaque-v1",
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": "operator/20260803/us-east-1/s3/aws4_request",
            "X-Amz-Date": "20260803T120000Z",
            "X-Amz-Expires": str(expires),
            "X-Amz-SignedHeaders": "host",
            "X-Amz-Signature": signature,
        }
    )


def passed_quality() -> Mapping[str, Any]:
    return {
        "qa_version": "qa/v1",
        "status": "passed",
        "measurements": {
            "requested_height_mm": 95,
            "dimensions_mm": [64, 51, 95],
            "glb_dimensions_mm": [64.1, 51, 95.1],
            "stl_dimensions_mm": [64, 50.9, 95],
            "triangle_count": 24000,
            "object_count": 18,
            "material_count": 3,
            "non_manifold_edges": 0,
            "zero_area_faces": 0,
            "minimum_wall_mm": 1.34,
            "minimum_feature_mm": 2.15,
            "connected_shells": 1,
        },
        "checks": {
            "manifold": True,
            "finite_geometry": True,
            "outward_normals": True,
            "positive_volume": True,
            "height_within_tolerance": True,
            "fresh_reload": True,
            "glb_reimport": True,
            "stl_reimport": True,
        },
        "notes": [],
    }


class MockState:
    def __init__(self) -> None:
        self.token = TOKEN
        self.signature = SIGNATURE_CANARY
        self.build_id = BUILD_ID
        self.facet_payload = (ROOT / "examples" / "requests" / "facet-bot.json").read_bytes()
        self.moss_payload = (ROOT / "examples" / "requests" / "moss-hopper.json").read_bytes()
        self.facet = operator_smoke.validate_build_request(self.facet_payload)
        self.moss = operator_smoke.validate_build_request(self.moss_payload)
        self.created = False
        self.polls = 0
        self.stuck = False
        self.artifact_mode = "valid"
        self.ready_disclosure = False
        self.health_status = 200
        self.health_body = b'{"status":"ok"}'
        self.ready_authorizations: list[str | None] = []
        self.api_authorizations: list[str | None] = []
        self.download_authorizations: list[str | None] = []
        self.download_queries: list[str] = []
        self._make_artifacts()

    def _make_artifacts(self, requested_height: int = 95) -> None:
        quality = passed_quality()
        quality["measurements"]["requested_height_mm"] = requested_height  # type: ignore[index]
        quality["measurements"]["dimensions_mm"][2] = requested_height  # type: ignore[index]
        quality["measurements"]["glb_dimensions_mm"][2] = requested_height  # type: ignore[index]
        quality["measurements"]["stl_dimensions_mm"][2] = requested_height  # type: ignore[index]
        qa_payload = operator_smoke.canonical_json_bytes(quality) + b"\n"
        bodies: dict[str, bytes] = {
            "model.blend": b"BLENDER-model-bytes",
            "model.glb": b"glTF-portable-model-bytes",
            "model.stl": b"solid facet-bot\nendsolid facet-bot\n",
            "preview.png": b"\x89PNG\r\n\x1a\npreview",
            "diagnostics/front.png": b"\x89PNG\r\n\x1a\nfront",
            "diagnostics/side.png": b"\x89PNG\r\n\x1a\nside",
            "diagnostics/back.png": b"\x89PNG\r\n\x1a\nback",
            "qa.json": qa_payload,
        }
        entries = {
            path: {
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            for path, payload in bodies.items()
        }
        manifest = {
            "manifest_version": "manifest/v1",
            "request_sha256": self.facet.request_sha256,
            "spec_sha256": self.facet.spec_sha256,
            "input_sha256": {},
            "generator_version": "1.0.0",
            "execution": {
                "mode": "container",
                "project_revision": "d" * 40,
                "blender_version": "4.5.12 LTS",
                "blender_binary_sha256": "e" * 64,
                "worker_image_reference": "ghcr.io/example/builder@sha256:" + ("f" * 64),
                "worker_image_digest": "sha256:" + ("f" * 64),
                "worker_image_id": "sha256:" + ("a" * 64),
            },
            "dimensions_mm": [64, 51, requested_height],
            "artifacts": entries,
            "qa": {
                "status": "passed",
                "manifold": True,
                "non_manifold_edges": 0,
                "minimum_wall_mm": 1.34,
                "minimum_feature_mm": 2.15,
                "connected_shells": 1,
                "positive_volume": True,
                "fresh_reload": True,
                "glb_reimport": True,
                "stl_reimport": True,
            },
        }
        manifest_payload = operator_smoke.canonical_json_bytes(manifest) + b"\n"
        operator_smoke.validate_manifest(manifest_payload)
        operator_smoke.validate_quality_report(qa_payload)
        bodies["manifest.json"] = manifest_payload
        self.bodies = bodies

    def invalidate_manifest(self) -> None:
        self.bodies["manifest.json"] = b"{}\n"

    def use_wrong_height_contracts(self) -> None:
        self._make_artifacts(requested_height=96)

    def metadata(self, path: str) -> Mapping[str, Any]:
        payload = self.bodies[path]
        digest = hashlib.sha256(payload).hexdigest()
        if self.artifact_mode == "hash-mismatch" and path == "model.glb":
            digest = "0" * 64
        return {
            "path": path,
            "content_type": operator_smoke.ARTIFACT_CONTENT_TYPES[path],
            "bytes": len(payload),
            "sha256": digest,
        }

    def build_document(self, *, succeeded: bool) -> Mapping[str, Any]:
        manifest = self.metadata("manifest.json")
        return {
            "build_id": self.build_id,
            "request_sha256": self.facet.request_sha256,
            "spec_sha256": self.facet.spec_sha256,
            "status": "succeeded" if succeeded else "queued",
            "state_version": 2 if succeeded else 1,
            "max_attempts": 2,
            "cancel_requested_at": None,
            "terminal_code": None,
            "manifest_sha256": manifest["sha256"] if succeeded else None,
            "manifest_bytes": manifest["bytes"] if succeeded else None,
            "created_at": TIMESTAMP,
            "updated_at": TIMESTAMP,
            "finished_at": TIMESTAMP if succeeded else None,
            "published_at": TIMESTAMP if succeeded else None,
            "artifacts_url": f"/v1/builds/{self.build_id}/artifacts" if succeeded else None,
        }


class MockHandler(BaseHTTPRequestHandler):
    server: Any

    def log_message(self, _format: str, *args: object) -> None:
        del args

    @property
    def state(self) -> MockState:
        return self.server.state

    def _send_bytes(
        self,
        status: int,
        payload: bytes,
        *,
        content_type: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(
        self,
        status: int,
        document: Mapping[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self._send_bytes(status, payload, content_type="application/json", headers=headers)

    def _unauthorized(self) -> None:
        self._send_json(
            401,
            {
                "error": {
                    "code": "unauthorized",
                    "message": "Bearer authorization is required.",
                    "path": None,
                    "request_id": "22222222-2222-4222-8222-222222222222",
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    def _authorized(self) -> bool:
        value = self.headers.get("Authorization")
        self.state.api_authorizations.append(value)
        if value != "Bearer " + self.state.token:
            self._unauthorized()
            return False
        return True

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/healthz":
            self._send_bytes(
                self.state.health_status,
                self.state.health_body,
                content_type="application/json",
            )
            return
        if parsed.path == "/readyz":
            authorization = self.headers.get("Authorization")
            self.state.ready_authorizations.append(authorization)
            payload = (
                b"private readiness with credential-dependent detail"
                if self.state.ready_disclosure and authorization is not None
                else b"private readiness"
            )
            self._send_bytes(404, payload, content_type="text/plain")
            return
        if parsed.path.startswith("/objects/"):
            path = urllib.parse.unquote(parsed.path[len("/objects/") :])
            self.state.download_authorizations.append(self.headers.get("Authorization"))
            self.state.download_queries.append(parsed.query)
            if path not in self.state.bodies:
                self._send_bytes(404, b"missing", content_type="text/plain")
                return
            self._send_bytes(
                200,
                self.state.bodies[path],
                content_type=operator_smoke.ARTIFACT_CONTENT_TYPES[path],
            )
            return
        if parsed.path == f"/v1/builds/{self.state.build_id}":
            if not self._authorized():
                return
            self.state.polls += 1
            succeeded = not self.state.stuck
            self._send_json(200, self.state.build_document(succeeded=succeeded))
            return
        if parsed.path == f"/v1/builds/{self.state.build_id}/artifacts":
            if not self._authorized():
                return
            entries = []
            for path in operator_smoke.REQUIRED_PUBLISHED_ARTIFACTS:
                entry = dict(self.state.metadata(path))
                quoted = urllib.parse.quote(path, safe="/")
                entry["download_url"] = (
                    f"http://127.0.0.1:{self.server.server_port}/objects/{quoted}"
                    f"?{sigv4_query(signature=self.state.signature)}"
                )
                if self.state.artifact_mode == "late-unsafe-url" and path == "manifest.json":
                    entry["download_url"] = (
                        "https://unapproved.example.test/object?" + sigv4_query()
                    )
                entries.append(entry)
            if self.state.artifact_mode == "extra":
                entries.append(
                    {
                        "path": "unexpected.txt",
                        "content_type": "text/plain",
                        "bytes": 1,
                        "sha256": "0" * 64,
                        "download_url": (
                            f"http://127.0.0.1:{self.server.server_port}/objects/unexpected.txt"
                            f"?{sigv4_query()}"
                        ),
                    }
                )
            self._send_json(
                200,
                {
                    "build_id": self.state.build_id,
                    "published_at": TIMESTAMP,
                    "expires_in_seconds": 300,
                    "artifacts": entries,
                },
            )
            return
        self._send_bytes(404, b"not found", content_type="text/plain")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != "/v1/builds":
            self._send_bytes(404, b"not found", content_type="text/plain")
            return
        if not self._authorized():
            return
        length_text = self.headers.get("Content-Length", "0")
        length = int(length_text) if length_text.isdigit() else 0
        payload = self.rfile.read(length)
        key = self.headers.get("Idempotency-Key")
        try:
            request = operator_smoke.validate_build_request(payload)
        except Exception:
            self._send_json(422, {"error": {"code": "invalid_request"}})
            return
        if request.request_sha256 == self.state.moss.request_sha256:
            self._send_json(
                409,
                {
                    "error": {
                        "code": "idempotency_conflict",
                        "message": "Idempotency-Key is already bound.",
                        "path": None,
                        "request_id": "33333333-3333-4333-8333-333333333333",
                    }
                },
            )
            return
        if request.request_sha256 != self.state.facet.request_sha256 or key is None:
            self._send_json(422, {"error": {"code": "invalid_request"}})
            return
        created = not self.state.created
        self.state.created = True
        document = self.state.build_document(succeeded=False)
        self._send_json(
            202 if created else 200,
            document,
            headers={"Location": f"/v1/builds/{self.state.build_id}"},
        )


@contextlib.contextmanager
def mock_target(state: MockState) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    server.state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def write_token(root: Path, token: str = TOKEN, mode: int = 0o600) -> Path:
    path = root / "operator.token"
    path.write_text(token + "\n", encoding="ascii")
    path.chmod(mode)
    return path


def execute_against(target: str, state: MockState, **overrides: Any) -> Mapping[str, Any]:
    del state
    options = {
        "target_origin": operator_smoke.validate_target_url(
            target, allow_loopback_http=True
        ),
        "token": TOKEN,
        "allowed_artifact_origins": frozenset(),
        "poll_timeout": 1.0,
        "poll_interval": 0.01,
        "request_timeout": 2.0,
    }
    options.update(overrides)
    return operator_smoke.execute_smoke(**options)


class CommandAndPolicyTests(unittest.TestCase):
    def test_executable_default_is_successful_conditional_skip(self) -> None:
        self.assertTrue(SCRIPT.stat().st_mode & stat.S_IXUSR)
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [str(SCRIPT)],
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(
            completed.stdout,
            "OPERATOR_SMOKE: CONDITIONAL_SKIP reason=no_target\n",
        )
        self.assertEqual(completed.stderr, "")

        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "skip.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = operator_smoke.main(["--evidence", str(evidence)])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(evidence.read_text(encoding="utf-8"))["result"], "CONDITIONAL_SKIP")
            self.assertEqual(stat.S_IMODE(evidence.stat().st_mode), 0o600)

    def test_target_policy_rejects_credential_and_location_confusion(self) -> None:
        rejected = (
            "https://user@example.test",
            "https://user:password@example.test",
            "https://example.test/api",
            "https://example.test?query=value",
            "https://example.test?",
            "https://example.test#fragment",
            "https://example.test#",
            "https://example.test\t",
            "https://example.test\n",
        )
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(operator_smoke.SmokeFailure):
                operator_smoke.validate_target_url(value, allow_loopback_http=False)
        with self.assertRaises(operator_smoke.SmokeFailure):
            operator_smoke.validate_target_url(
                "http://127.0.0.1:8080", allow_loopback_http=False
            )
        with self.assertRaises(operator_smoke.SmokeFailure):
            operator_smoke.validate_target_url(
                "http://example.test", allow_loopback_http=True
            )
        origin = operator_smoke.validate_target_url(
            "http://127.0.0.1:8080/", allow_loopback_http=True
        )
        self.assertEqual(origin.base_url, "http://127.0.0.1:8080")
        self.assertEqual(
            operator_smoke.validate_target_url(
                "https://EXAMPLE.test:443/", allow_loopback_http=False
            ).base_url,
            "https://example.test",
        )

    def test_signed_url_origin_policy_is_exact_and_version_pinned(self) -> None:
        target = operator_smoke.validate_target_url(
            "https://api.example.test", allow_loopback_http=False
        )
        assets = operator_smoke.parse_artifact_host("assets.example.test")
        query = sigv4_query()
        accepted = (
            "https://api.example.test/object?" + query,
            "https://assets.example.test/object?" + query,
        )
        for value in accepted:
            self.assertEqual(
                operator_smoke.validate_signed_download_url(
                    value,
                    target_origin=target,
                    allowed_artifact_origins=frozenset({assets}),
                    expires_in_seconds=300,
                ),
                value,
            )
        rejected = (
            "https://assets.example.test/object?signature=secret",
            "https://assets.example.test/object?" + query + "&versionId=duplicate",
            "https://user@assets.example.test/object?" + query,
            "https://assets.example.test/object?" + query + "#fragment",
            "http://assets.example.test/object?" + query,
            "https://other.example.test/object?" + query,
            "https://assets.example.test:8443/object?" + query,
            "https://assets.example.test/object?" + sigv4_query(expires=299),
        )
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(operator_smoke.SmokeFailure):
                operator_smoke.validate_signed_download_url(
                    value,
                    target_origin=target,
                    allowed_artifact_origins=frozenset({assets}),
                    expires_in_seconds=300,
                )

    def test_token_file_requires_regular_nonsymlink_0600_single_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid = write_token(root)
            self.assertEqual(operator_smoke.read_token_file(valid), TOKEN)

            valid.chmod(0o644)
            with self.assertRaises(operator_smoke.SmokeFailure):
                operator_smoke.read_token_file(valid)
            valid.chmod(0o600)
            valid.write_text(TOKEN + "\n" + ("u" * 64) + "\n", encoding="ascii")
            with self.assertRaises(operator_smoke.SmokeFailure):
                operator_smoke.read_token_file(valid)

            valid.write_text(TOKEN + "\n", encoding="ascii")
            valid.chmod(0o600)
            link = root / "linked.token"
            link.symlink_to(valid)
            with self.assertRaises(operator_smoke.SmokeFailure):
                operator_smoke.read_token_file(link)
            with self.assertRaises(operator_smoke.SmokeFailure):
                operator_smoke.read_token_file(root)


class RedirectSinkHandler(BaseHTTPRequestHandler):
    server: Any

    def log_message(self, _format: str, *args: object) -> None:
        del args

    def do_GET(self) -> None:
        self.server.hits += 1
        self.server.authorizations.append(self.headers.get("Authorization"))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")


class RedirectSourceHandler(BaseHTTPRequestHandler):
    server: Any

    def log_message(self, _format: str, *args: object) -> None:
        del args

    def do_GET(self) -> None:
        self.server.authorizations.append(self.headers.get("Authorization"))
        self.send_response(302)
        self.send_header("Location", self.server.destination)
        self.send_header("Content-Length", "0")
        self.end_headers()


class RedirectSecurityTests(unittest.TestCase):
    def test_redirect_is_not_followed_and_bearer_never_crosses_origin(self) -> None:
        sink = ThreadingHTTPServer(("127.0.0.1", 0), RedirectSinkHandler)
        sink.hits = 0
        sink.authorizations = []
        sink_thread = threading.Thread(target=sink.serve_forever, daemon=True)
        sink_thread.start()
        source = ThreadingHTTPServer(("127.0.0.1", 0), RedirectSourceHandler)
        source.authorizations = []
        source.destination = (
            f"http://127.0.0.1:{sink.server_port}/sink"
            f"?{sigv4_query()}"
        )
        source_thread = threading.Thread(target=source.serve_forever, daemon=True)
        source_thread.start()
        try:
            with self.assertRaises(operator_smoke.SmokeFailure) as raised:
                operator_smoke.HttpTransport().request(
                    f"http://127.0.0.1:{source.server_port}/start",
                    "GET",
                    headers={"Authorization": "Bearer " + TOKEN},
                    timeout=2,
                )
            self.assertEqual(raised.exception.code, "redirect_rejected")
            self.assertEqual(source.authorizations, ["Bearer " + TOKEN])
            self.assertEqual(sink.hits, 0)
            self.assertEqual(sink.authorizations, [])

            with self.assertRaises(operator_smoke.SmokeFailure) as download_raised:
                operator_smoke.HttpTransport().download(
                    f"http://127.0.0.1:{source.server_port}/artifact?{sigv4_query()}",
                    expected_bytes=2,
                    expected_content_type="application/json",
                    timeout=2,
                    capture=False,
                )
            self.assertEqual(download_raised.exception.code, "redirect_rejected")
            self.assertEqual(source.authorizations[-1], None)
            self.assertEqual(sink.hits, 0)
            self.assertEqual(sink.authorizations, [])
        finally:
            source.shutdown()
            sink.shutdown()
            source.server_close()
            sink.server_close()
            source_thread.join(timeout=5)
            sink_thread.join(timeout=5)


class FullProtocolTests(unittest.TestCase):
    def test_success_covers_public_boundary_artifacts_and_sanitized_evidence(self) -> None:
        state = MockState()
        with tempfile.TemporaryDirectory() as temporary, mock_target(state) as target:
            root = Path(temporary)
            token_file = write_token(root)
            evidence = root / "evidence" / "operator.json"
            evidence.parent.mkdir()
            evidence.write_text("old", encoding="utf-8")
            evidence.chmod(0o644)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = operator_smoke.main(
                    [
                        "--target",
                        target,
                        "--allow-loopback-http",
                        "--token-file",
                        str(token_file),
                        "--evidence",
                        str(evidence),
                        "--poll-timeout",
                        "1",
                        "--poll-interval",
                        "0.01",
                        "--request-timeout",
                        "2",
                    ]
                )
            self.assertEqual(result, 0)
            self.assertIn("OPERATOR_SMOKE: PASS", stdout.getvalue())
            self.assertEqual(stderr.getvalue(), "")
            combined = stdout.getvalue() + stderr.getvalue() + evidence.read_text(encoding="utf-8")
            self.assertNotIn(TOKEN, combined)
            self.assertNotIn(SIGNATURE_CANARY, combined)
            self.assertNotIn("Authorization", combined)
            self.assertNotIn("download_url", combined)
            self.assertNotIn(target, evidence.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(evidence.stat().st_mode), 0o600)
            document = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(document["result"], "PASS")
            self.assertEqual(document["artifact_count"], 9)
            self.assertEqual(
                state.ready_authorizations,
                [None, "Bearer " + ("A" + TOKEN[1:]), "Bearer " + TOKEN],
            )
            self.assertGreaterEqual(state.api_authorizations.count(None), 1)
            self.assertIn("Bearer " + ("A" + TOKEN[1:]), state.api_authorizations)
            self.assertEqual(len(state.download_authorizations), 9)
            self.assertTrue(all(value is None for value in state.download_authorizations))
            self.assertTrue(all("versionId=opaque-v1" in value for value in state.download_queries))
            self.assertEqual(list(evidence.parent.glob(".*.tmp")), [])

    def test_extra_artifact_and_hash_mismatch_fail_closed(self) -> None:
        for mode, code in (
            ("extra", "artifact_allowlist_mismatch"),
            ("hash-mismatch", "manifest_artifact_mismatch"),
        ):
            state = MockState()
            state.artifact_mode = mode
            with self.subTest(mode=mode), mock_target(state) as target:
                with self.assertRaises(operator_smoke.SmokeFailure) as raised:
                    execute_against(target, state)
                self.assertEqual(raised.exception.code, code)

    def test_invalid_manifest_fails_contract_after_matching_download_hash(self) -> None:
        state = MockState()
        state.invalidate_manifest()
        with mock_target(state) as target:
            with self.assertRaises(operator_smoke.SmokeFailure) as raised:
                execute_against(target, state)
        self.assertEqual(raised.exception.code, "artifact_contract_invalid")

    def test_wrong_height_contracts_do_not_override_submitted_spec(self) -> None:
        state = MockState()
        state.use_wrong_height_contracts()
        with mock_target(state) as target:
            with self.assertRaises(operator_smoke.SmokeFailure) as raised:
                execute_against(target, state)
        self.assertEqual(raised.exception.code, "qa_manifest_mismatch")
        self.assertEqual(len(state.download_authorizations), 2)

    def test_all_signed_urls_are_prevalidated_before_any_download(self) -> None:
        state = MockState()
        state.artifact_mode = "late-unsafe-url"
        with mock_target(state) as target:
            with self.assertRaises(operator_smoke.SmokeFailure) as raised:
                execute_against(target, state)
        self.assertEqual(raised.exception.code, "signed_url_cross_origin")
        self.assertEqual(state.download_authorizations, [])

    def test_private_readiness_is_indistinguishable_across_credentials(self) -> None:
        state = MockState()
        state.ready_disclosure = True
        with mock_target(state) as target:
            with self.assertRaises(operator_smoke.SmokeFailure) as raised:
                execute_against(target, state)
        self.assertEqual(raised.exception.code, "ready_endpoint_disclosure")
        self.assertEqual(state.api_authorizations, [])

    def test_polling_has_a_wall_clock_bound(self) -> None:
        state = MockState()
        state.stuck = True
        with mock_target(state) as target:
            with self.assertRaises(operator_smoke.SmokeFailure) as raised:
                execute_against(
                    target,
                    state,
                    poll_timeout=0.06,
                    poll_interval=0.01,
                )
        self.assertEqual(raised.exception.code, "build_poll_timeout")
        self.assertLessEqual(state.polls, 10)

    def test_failure_output_and_evidence_never_echo_response_or_credentials(self) -> None:
        state = MockState()
        state.health_status = 500
        state.health_body = (
            TOKEN + " Authorization: Bearer " + TOKEN + " https://objects/?signature=" + SIGNATURE_CANARY
        ).encode("ascii")
        with tempfile.TemporaryDirectory() as temporary, mock_target(state) as target:
            root = Path(temporary)
            token_file = write_token(root)
            evidence = root / "failure.json"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = operator_smoke.main(
                    [
                        "--target",
                        target,
                        "--allow-loopback-http",
                        "--token-file",
                        str(token_file),
                        "--evidence",
                        str(evidence),
                        "--request-timeout",
                        "2",
                    ]
                )
            self.assertEqual(result, 1)
            combined = stdout.getvalue() + stderr.getvalue() + evidence.read_text(encoding="utf-8")
            self.assertIn("code=health_check_failed", combined)
            self.assertNotIn(TOKEN, combined)
            self.assertNotIn(SIGNATURE_CANARY, combined)
            self.assertNotIn("Authorization", combined)
            self.assertNotIn("https://objects/", combined)
            self.assertEqual(stat.S_IMODE(evidence.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
