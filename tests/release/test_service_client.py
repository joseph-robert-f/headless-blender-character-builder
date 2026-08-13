from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import signal
import stat
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "service-client"
loader = importlib.machinery.SourceFileLoader("service_client_under_test", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
CLIENT = importlib.util.module_from_spec(spec)
loader.exec_module(CLIENT)


class FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, url: str, status: int = 200) -> None:
        super().__init__(payload)
        self._url = url
        self.status = status

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class ServiceClientTests(unittest.TestCase):
    def test_script_is_safe_executable_and_stdlib_only(self) -> None:
        mode = stat.S_IMODE(SCRIPT.stat().st_mode)
        self.assertEqual(mode & 0o111, 0o111)
        self.assertEqual(mode & 0o022, 0)
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("urllib.request.ProxyHandler({})", text)
        self.assertIn("class RejectRedirects", text)
        self.assertIn("MAX_POLL_ATTEMPTS = 600", text)
        self.assertIn("MAX_POLL_SECONDS = 1200", text)
        self.assertNotIn("requests", text)
        self.assertNotIn("httpx", text)

    def test_download_rejects_nonloopback_redirects_and_hash_mismatches(self) -> None:
        client = CLIENT.Client(8080, 9000, "a" * 64)
        payload = b"verified artifact"
        url = "http://127.0.0.1:9000/local?versionId=fixture"
        with self.assertRaisesRegex(CLIENT.ClientFailure, "outside the selected"):
            client._checked_download_url(
                "https://attacker.invalid/local?versionId=fixture"
            )

        listing = []
        for relative in CLIENT.REQUIRED_ARTIFACTS:
            listing.append(
                {
                    "path": relative,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "download_url": url,
                }
            )
        with tempfile.TemporaryDirectory(prefix="hbcb-client-download-") as raw:
            stage = Path(raw)
            client.opener.open = mock.Mock(
                side_effect=lambda *_args, **_kwargs: FakeResponse(payload, url)
            )
            client.download(listing, stage)
            self.assertEqual((stage / "model.glb").read_bytes(), payload)

            mismatch_stage = Path(raw) / "mismatch"
            mismatch_stage.mkdir()
            listing[0] = {**listing[0], "sha256": "0" * 64}
            with self.assertRaisesRegex(CLIENT.ClientFailure, "did not match"):
                client.download(listing, mismatch_stage)

        redirect = urllib.error.HTTPError(url, 302, "redirect", {}, io.BytesIO(b""))
        client.opener.open = mock.Mock(side_effect=redirect)
        with tempfile.TemporaryDirectory(prefix="hbcb-client-redirect-") as raw:
            with self.assertRaisesRegex(CLIENT.ClientFailure, "redirect was rejected"):
                client.download(
                    [
                        {
                            "path": relative,
                            "bytes": len(payload),
                            "sha256": hashlib.sha256(payload).hexdigest(),
                            "download_url": url,
                        }
                        for relative in CLIENT.REQUIRED_ARTIFACTS
                    ],
                    Path(raw),
                )

    def test_poll_is_bounded_and_cancellation_is_best_effort(self) -> None:
        client = CLIENT.Client(8080, 9000, "a" * 64)
        client.build_id = "00000000-0000-0000-0000-000000000001"
        client._json_request = mock.Mock(
            return_value={
                "build_id": client.build_id,
                "status": "running",
                "terminal_code": None,
            }
        )
        with mock.patch.object(CLIENT, "MAX_POLL_ATTEMPTS", 2), mock.patch.object(
            CLIENT.time, "sleep"
        ), mock.patch.object(
            CLIENT.time, "monotonic", side_effect=(0, 0, 0, 0)
        ):
            with self.assertRaisesRegex(CLIENT.ClientFailure, "bounded deadline"):
                client.poll(0)
        self.assertEqual(client._json_request.call_count, 2)

        client._json_request = mock.Mock(side_effect=CLIENT.ClientFailure("fixture"))
        client.cancel()
        client._json_request.assert_called_once()

    def test_artifact_listing_is_bound_to_the_submitted_build(self) -> None:
        client = CLIENT.Client(8080, 9000, "a" * 64)
        client.build_id = "00000000-0000-0000-0000-000000000001"
        entries = [{"path": path} for path in CLIENT.REQUIRED_ARTIFACTS]
        client._json_request = mock.Mock(
            return_value={
                "build_id": "00000000-0000-0000-0000-000000000099",
                "artifacts": entries,
            }
        )
        with self.assertRaisesRegex(CLIENT.ClientFailure, "incomplete or out of order"):
            client.artifact_listing()

    def test_run_reserves_no_clobber_result_and_removes_failed_private_stage(self) -> None:
        build_id = "00000000-0000-0000-0000-000000000002"
        with tempfile.TemporaryDirectory(prefix="hbcb-client-run-") as raw:
            root = Path(raw)
            request = root / "request.json"
            request.write_bytes(
                (ROOT / "examples" / "requests" / "facet-bot.json").read_bytes()
            )
            env_file = root / ".env"
            env_file.write_text("HBCB_API_TOKEN=" + "a" * 64 + "\n", encoding="ascii")
            env_file.chmod(0o600)
            output_parent = root / "results"
            fake = mock.Mock()
            fake.submit.return_value = build_id
            fake.poll.return_value = {"build_id": build_id, "status": "succeeded"}
            fake.artifact_listing.return_value = []
            fake.download.side_effect = CLIENT.ClientFailure("fixture download failed")
            fake.cancel.return_value = None
            with mock.patch.object(CLIENT, "Client", return_value=fake):
                with self.assertRaisesRegex(CLIENT.ClientFailure, "fixture download failed"):
                    CLIENT.run(
                        [
                            "--request",
                            str(request),
                            "--env-file",
                            str(env_file),
                            "--output-parent",
                            str(output_parent),
                            "--poll-interval-seconds",
                            "0",
                        ]
                    )
            self.assertFalse((output_parent / build_id).exists())
            fake.cancel.assert_called_once()

            sentinel = output_parent / build_id
            sentinel.mkdir()
            (sentinel / "sentinel").write_text("preserve\n", encoding="utf-8")
            fake.download.reset_mock()
            with mock.patch.object(CLIENT, "Client", return_value=fake):
                with self.assertRaisesRegex(CLIENT.ClientFailure, "refusing to overwrite"):
                    CLIENT.run(
                        [
                            "--request",
                            str(request),
                            "--env-file",
                            str(env_file),
                            "--output-parent",
                            str(output_parent),
                        ]
                    )
            self.assertEqual((sentinel / "sentinel").read_text(), "preserve\n")
            fake.download.assert_not_called()

            sentinel_file = output_parent / "00000000-0000-0000-0000-000000000003"
            sentinel_file.write_text("file-sentinel\n", encoding="utf-8")
            fake.submit.return_value = sentinel_file.name
            with mock.patch.object(CLIENT, "Client", return_value=fake):
                with self.assertRaisesRegex(CLIENT.ClientFailure, "refusing to overwrite"):
                    CLIENT.run(
                        [
                            "--request",
                            str(request),
                            "--env-file",
                            str(env_file),
                            "--output-parent",
                            str(output_parent),
                        ]
                    )
            self.assertEqual(sentinel_file.read_text(encoding="utf-8"), "file-sentinel\n")

            sentinel_target = root / "link-target"
            sentinel_target.mkdir()
            (sentinel_target / "sentinel").write_text("link-sentinel\n", encoding="utf-8")
            sentinel_link = output_parent / "00000000-0000-0000-0000-000000000004"
            sentinel_link.symlink_to(sentinel_target, target_is_directory=True)
            fake.submit.return_value = sentinel_link.name
            with mock.patch.object(CLIENT, "Client", return_value=fake):
                with self.assertRaisesRegex(CLIENT.ClientFailure, "refusing to overwrite"):
                    CLIENT.run(
                        [
                            "--request",
                            str(request),
                            "--env-file",
                            str(env_file),
                            "--output-parent",
                            str(output_parent),
                        ]
                    )
            self.assertTrue(sentinel_link.is_symlink())
            self.assertEqual(
                (sentinel_target / "sentinel").read_text(encoding="utf-8"),
                "link-sentinel\n",
            )

    def test_private_reader_rejects_an_open_identity_swap_or_truncation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-client-read-") as raw:
            source = Path(raw) / "source"
            source.write_bytes(b"source")
            original_open = CLIENT.os.open

            def swapped_open(_path, flags):
                replacement = Path(raw) / "replacement"
                replacement.write_bytes(b"source")
                return original_open(replacement, flags)

            with mock.patch.object(CLIENT.os, "open", side_effect=swapped_open):
                with self.assertRaisesRegex(CLIENT.ClientFailure, "unavailable or unsafe"):
                    CLIENT._regular_private_file(source, 1024)

            original_fstat = CLIENT.os.fstat
            calls = 0

            def changed_fstat(descriptor):
                nonlocal calls
                metadata = original_fstat(descriptor)
                calls += 1
                if calls == 2:
                    return mock.Mock(
                        st_dev=metadata.st_dev,
                        st_ino=metadata.st_ino,
                        st_size=metadata.st_size + 1,
                    )
                return metadata

            with mock.patch.object(CLIENT.os, "fstat", side_effect=changed_fstat):
                with self.assertRaisesRegex(CLIENT.ClientFailure, "unavailable or unsafe"):
                    CLIENT._regular_private_file(source, 1024)

            calls = 0

            def same_size_mutation(descriptor):
                nonlocal calls
                metadata = original_fstat(descriptor)
                calls += 1
                if calls == 2:
                    return mock.Mock(
                        st_dev=metadata.st_dev,
                        st_ino=metadata.st_ino,
                        st_size=metadata.st_size,
                        st_mode=metadata.st_mode,
                        st_uid=metadata.st_uid,
                        st_mtime_ns=metadata.st_mtime_ns + 1,
                        st_ctime_ns=metadata.st_ctime_ns + 1,
                    )
                return metadata

            with mock.patch.object(CLIENT.os, "fstat", side_effect=same_size_mutation):
                with self.assertRaisesRegex(CLIENT.ClientFailure, "unavailable or unsafe"):
                    CLIENT._regular_private_file(source, 1024)

    def test_repeated_signals_preserve_first_status_and_finish_cleanup(self) -> None:
        build_id = "00000000-0000-0000-0000-000000000005"
        with tempfile.TemporaryDirectory(prefix="hbcb-client-signal-") as raw:
            root = Path(raw)
            request = root / "request.json"
            request.write_bytes(
                (ROOT / "examples" / "requests" / "facet-bot.json").read_bytes()
            )
            env_file = root / ".env"
            env_file.write_text("HBCB_API_TOKEN=" + "a" * 64 + "\n", encoding="ascii")
            env_file.chmod(0o600)
            output_parent = root / "results"
            fake = mock.Mock()
            fake.submit.return_value = build_id
            fake.poll.return_value = {"build_id": build_id, "status": "succeeded"}
            fake.artifact_listing.return_value = []

            def signal_during_download(_entries, stage, _stop_requested):
                (stage / "partial").write_bytes(b"private partial")
                os.kill(os.getpid(), signal.SIGTERM)
                os.kill(os.getpid(), signal.SIGINT)

            fake.download.side_effect = signal_during_download
            fake.cancel.side_effect = lambda: os.kill(os.getpid(), signal.SIGINT)
            with mock.patch.object(CLIENT, "Client", return_value=fake):
                result = CLIENT.run(
                    [
                        "--request",
                        str(request),
                        "--env-file",
                        str(env_file),
                        "--output-parent",
                        str(output_parent),
                        "--poll-interval-seconds",
                        "0",
                    ]
                )
            self.assertEqual(result, 128 + signal.SIGTERM)
            self.assertFalse((output_parent / build_id).exists())
            fake.cancel.assert_called_once()

    def test_cancel_exception_cannot_skip_private_cleanup_or_handler_restore(self) -> None:
        build_id = "00000000-0000-0000-0000-000000000007"
        with tempfile.TemporaryDirectory(prefix="hbcb-client-cancel-failure-") as raw:
            root = Path(raw)
            request = root / "request.json"
            request.write_bytes(
                (ROOT / "examples" / "requests" / "facet-bot.json").read_bytes()
            )
            env_file = root / ".env"
            env_file.write_text("HBCB_API_TOKEN=" + "a" * 64 + "\n", encoding="ascii")
            env_file.chmod(0o600)
            output_parent = root / "results"
            fake = mock.Mock()
            fake.submit.return_value = build_id
            fake.poll.return_value = {"build_id": build_id, "status": "succeeded"}
            fake.artifact_listing.return_value = []

            def leave_partial(_entries, stage, _stop_requested):
                (stage / "partial").write_bytes(b"private partial")
                raise CLIENT.ClientFailure("fixture primary failure")

            fake.download.side_effect = leave_partial
            fake.cancel.side_effect = RuntimeError("fixture cancel failure")
            original_handlers = {
                item: signal.getsignal(item)
                for item in (
                    signal.SIGINT,
                    signal.SIGTERM,
                    getattr(signal, "SIGHUP", signal.SIGTERM),
                )
            }
            with mock.patch.object(CLIENT, "Client", return_value=fake):
                with self.assertRaisesRegex(CLIENT.ClientFailure, "fixture primary failure"):
                    CLIENT.run(
                        [
                            "--request",
                            str(request),
                            "--env-file",
                            str(env_file),
                            "--output-parent",
                            str(output_parent),
                        ]
                    )
            self.assertFalse((output_parent / build_id).exists())
            for item, handler in original_handlers.items():
                self.assertIs(signal.getsignal(item), handler)

    def test_success_publishes_exact_private_result_without_canceling(self) -> None:
        build_id = "00000000-0000-0000-0000-000000000006"
        with tempfile.TemporaryDirectory(prefix="hbcb-client-success-") as raw:
            root = Path(raw)
            request = root / "request.json"
            request.write_bytes(
                (ROOT / "examples" / "requests" / "facet-bot.json").read_bytes()
            )
            env_file = root / ".env"
            env_file.write_text("HBCB_API_TOKEN=" + "a" * 64 + "\n", encoding="ascii")
            env_file.chmod(0o600)
            output_parent = root / "results"
            fake = mock.Mock()
            fake.submit.return_value = build_id
            fake.poll.return_value = {
                "build_id": build_id,
                "status": "succeeded",
                "terminal_code": None,
            }
            fake.artifact_listing.return_value = [
                {"path": path} for path in CLIENT.REQUIRED_ARTIFACTS
            ]

            def create_artifacts(entries, stage, _stop_requested):
                self.assertEqual(
                    tuple(item["path"] for item in entries),
                    CLIENT.REQUIRED_ARTIFACTS,
                )
                for relative in CLIENT.REQUIRED_ARTIFACTS:
                    destination = stage.joinpath(*relative.split("/"))
                    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    destination.write_bytes(relative.encode("ascii"))
                    destination.chmod(0o600)

            fake.download.side_effect = create_artifacts
            with mock.patch.object(CLIENT, "Client", return_value=fake):
                result = CLIENT.run(
                    [
                        "--request",
                        str(request),
                        "--env-file",
                        str(env_file),
                        "--output-parent",
                        str(output_parent),
                        "--poll-interval-seconds",
                        "0",
                    ]
                )
            self.assertEqual(result, 0)
            published = output_parent / build_id / "artifacts"
            expected = set(CLIENT.REQUIRED_ARTIFACTS) | {"build.json"}
            actual = {
                path.relative_to(published).as_posix()
                for path in published.rglob("*")
                if path.is_file()
            }
            self.assertEqual(actual, expected)
            self.assertEqual(stat.S_IMODE(published.stat().st_mode), 0o700)
            for relative in expected:
                self.assertEqual(
                    stat.S_IMODE((published / relative).stat().st_mode),
                    0o600,
                    relative,
                )
            self.assertEqual(
                json.loads((published / "build.json").read_text(encoding="utf-8"))["build_id"],
                build_id,
            )
            fake.cancel.assert_not_called()


if __name__ == "__main__":
    unittest.main()
