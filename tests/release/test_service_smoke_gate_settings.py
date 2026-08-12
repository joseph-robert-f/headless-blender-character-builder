from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from tests.service_integration import g7_service_smoke as gate


class ServiceSmokeGateSettingsTests(unittest.TestCase):
    def test_commands_use_selected_docker_and_compose_project(self) -> None:
        with mock.patch.dict(
            gate.os.environ,
            {"DOCKER": "/fixture/docker", "HBCB_COMPOSE_BIN": "/fixture/compose"},
            clear=True,
        ):
            self.assertEqual(
                gate.docker_command("inspect", "container-id"),
                ["/fixture/docker", "inspect", "container-id"],
            )
            self.assertEqual(
                gate.compose_command("hbcb-project", "ps", "--all"),
                [
                    "/fixture/compose",
                    "--project-name",
                    "hbcb-project",
                    "ps",
                    "--all",
                ],
            )

    def test_download_rejects_signed_url_on_another_storage_port(self) -> None:
        payload = b"preview"
        artifact = {
            "artifacts": [
                {
                    "bytes": len(payload),
                    "download_url": "http://localhost:19001/object?versionId=one",
                    "path": path,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                for path in gate.REQUIRED_ARTIFACTS
            ]
        }
        with tempfile.TemporaryDirectory(prefix="hbcb-g7-storage-port-") as raw:
            output = Path(raw) / "artifacts"
            with mock.patch.object(
                gate,
                "http",
                return_value=(
                    200,
                    {},
                    json.dumps(artifact, sort_keys=True).encode("utf-8"),
                ),
            ):
                with self.assertRaisesRegex(
                    gate.GateFailure,
                    "exact selected storage host port",
                ):
                    gate.download_artifacts(
                        "http://127.0.0.1:18080",
                        "token",
                        "build-id",
                        output,
                        19000,
                    )
            self.assertFalse(output.exists())

    def test_download_never_follows_an_artifact_redirect(self) -> None:
        payload = b"preview"
        source_url = "http://127.0.0.1:19000/object?versionId=one"
        document = {
            "artifacts": [
                {
                    "bytes": len(payload),
                    "download_url": source_url,
                    "path": path,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                for path in gate.REQUIRED_ARTIFACTS
            ]
        }
        redirect = urllib.error.HTTPError(
            source_url,
            302,
            "redirect",
            {"Location": "http://127.0.0.1:19001/sink?versionId=one"},
            io.BytesIO(),
        )
        with tempfile.TemporaryDirectory(prefix="hbcb-g7-redirect-") as raw:
            output = Path(raw) / "artifacts"
            with mock.patch.object(
                gate,
                "http",
                return_value=(200, {}, json.dumps(document).encode("utf-8")),
            ), mock.patch.object(gate, "NO_REDIRECT_OPENER") as opener:
                opener.open.side_effect = redirect
                with self.assertRaisesRegex(
                    gate.GateFailure, "redirect was rejected"
                ):
                    gate.download_artifacts(
                        "http://127.0.0.1:18080",
                        "token",
                        "build-id",
                        output,
                        19000,
                    )
                opener.open.assert_called_once_with(source_url, timeout=30)
        handler = gate.RejectRedirects()
        self.assertIsNone(
            handler.redirect_request(
                mock.Mock(), mock.Mock(), 302, "redirect", {}, "http://foreign/"
            )
        )

    def test_download_opener_ignores_poisoned_proxy_environment(self) -> None:
        with mock.patch.dict(
            gate.os.environ,
            {
                "HTTP_PROXY": "http://foreign.invalid:3128",
                "HTTPS_PROXY": "http://foreign.invalid:3128",
                "NO_PROXY": "",
            },
            clear=False,
        ):
            # urllib omits an empty ProxyHandler from the installed handler
            # list. The important invariant is that no configured proxy
            # handler survives into this opener.
            proxies = [
                handler
                for handler in gate.NO_REDIRECT_OPENER.handlers
                if isinstance(handler, urllib.request.ProxyHandler)
            ]
        self.assertEqual(proxies, [])
        self.assertTrue(
            any(
                isinstance(handler, gate.RejectRedirects)
                for handler in gate.NO_REDIRECT_OPENER.handlers
            )
        )

    def test_runtime_requires_exact_selected_api_binding(self) -> None:
        api_id = "api-container"
        worker_id = "worker-container"
        base_host = {
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "PidsLimit": 128,
        }
        api = {
            "Config": {"Env": []},
            "HostConfig": {
                **base_host,
                "PortBindings": {
                    "8080/tcp": [
                        {"HostIp": "127.0.0.1", "HostPort": "18081"}
                    ]
                },
            },
            "Mounts": [],
            "NetworkSettings": {
                "Networks": {
                    "internal": {"NetworkID": "internal-id"},
                    "ingress": {"NetworkID": "ingress-id"},
                }
            },
        }
        worker = {
            "Config": {"Env": []},
            "HostConfig": {**base_host, "PortBindings": {}},
            "Mounts": [],
            "NetworkSettings": {
                "Networks": {"internal": {"NetworkID": "internal-id"}}
            },
        }

        def fake_run(command: list[str], **_kwargs: object) -> str:
            if "ps" in command:
                return api_id + "\n" if command[-1] == "api" else worker_id + "\n"
            if command[:2] == ["docker", "inspect"]:
                return json.dumps([api if command[-1] == api_id else worker])
            if command[:3] == ["docker", "network", "inspect"]:
                return json.dumps([{"Internal": command[-1] == "internal-id"}])
            raise AssertionError(command)

        with mock.patch.dict(gate.os.environ, {}, clear=True), mock.patch.object(
            gate, "run_command", side_effect=fake_run
        ):
            with self.assertRaisesRegex(
                gate.GateFailure,
                "exact selected loopback host port",
            ):
                gate.inspect_runtime(Path(".env"), "hbcb-project", 18080)


if __name__ == "__main__":
    unittest.main()
