from __future__ import annotations

import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tests" / "security" / "minio_fixture_gate.py"
SPEC = importlib.util.spec_from_file_location("hbcb_minio_fixture_gate", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def completed(
    command: tuple[str, ...],
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    returncode: int = 0,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def valid_document() -> dict[str, object]:
    return {
        "Id": "sha256:" + "a" * 64,
        "Os": "linux",
        "Architecture": "amd64",
        "Config": {
            "Labels": {
                "io.hbcb.mc-revision": GATE.CLIENT_REVISION,
                "io.hbcb.scope": "local-development-only",
                "io.hbcb.security-modules": GATE.SECURITY_MODULE_DATE,
                "org.opencontainers.image.licenses": "AGPL-3.0-or-later",
                "org.opencontainers.image.revision": GATE.SERVER_REVISION,
                "org.opencontainers.image.version": GATE.FIXTURE_VERSION,
            },
            "User": "65532:65532",
            "Entrypoint": ["/usr/local/bin/minio"],
            "Cmd": ["server", "/data", "--address", ":9000"],
            "Env": ["MINIO_BROWSER=off", "MINIO_UPDATE=off"],
        },
    }


class MinioSecurityGateTests(unittest.TestCase):
    def test_image_contract_is_exact_and_mutations_fail(self) -> None:
        expected_id = "sha256:" + "a" * 64
        self.assertEqual(GATE._validate_image(valid_document()), expected_id)

        mutations = []
        for field, value in (("Os", "darwin"), ("Architecture", "arm64"), ("Id", "a" * 64)):
            document = valid_document()
            document[field] = value
            mutations.append(document)
        for field, value in (
            ("User", "0:0"),
            ("Entrypoint", ["/bin/sh"]),
            ("Cmd", ["server", "/data"]),
        ):
            document = valid_document()
            config = document["Config"]
            assert isinstance(config, dict)
            config[field] = value
            mutations.append(document)
        document = valid_document()
        labels = document["Config"]["Labels"]  # type: ignore[index]
        labels["org.opencontainers.image.revision"] = "0" * 40  # type: ignore[index]
        mutations.append(document)
        document = valid_document()
        environment = document["Config"]["Env"]  # type: ignore[index]
        environment.append("MINIO_IDENTITY_OPENID_CONFIG_URL=https://example.invalid")  # type: ignore[union-attr]
        mutations.append(document)

        for document in mutations:
            with self.subTest(document=document):
                with self.assertRaises(GATE.GateError):
                    GATE._validate_image(document)

    def test_binary_probe_is_hardened_and_exact(self) -> None:
        recorded: list[tuple[str, ...]] = []

        def fake_run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
            recorded.append(tuple(command))
            return completed(tuple(command), stdout=b"version DEVELOPMENT.GOGET\n")

        with mock.patch.object(GATE, "_run", side_effect=fake_run):
            GATE._runtime_version("docker", "fixture:reviewed", "/usr/local/bin/minio")

        self.assertEqual(len(recorded), 1)
        command = recorded[0]
        self.assertEqual(command[:3], ("docker", "run", "--rm"))
        for pair in (
            ("--platform", "linux/amd64"),
            ("--network", "none"),
            ("--cap-drop", "ALL"),
            ("--security-opt", "no-new-privileges:true"),
            ("--entrypoint", "/usr/local/bin/minio"),
        ):
            offset = command.index(pair[0])
            self.assertEqual(command[offset : offset + 2], pair)
        self.assertIn("--read-only", command)
        self.assertEqual(command[-2:], ("fixture:reviewed", "--version"))

    def test_feature_probe_is_isolated_and_always_removed(self) -> None:
        recorded: list[tuple[str, ...]] = []
        container_id = "b" * 64
        owned = True

        def fake_run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
            nonlocal owned
            command = tuple(command)
            recorded.append(command)
            if command[1:3] == ("run", "--detach"):
                return completed(command, stdout=(container_id + "\n").encode("ascii"))
            if command[1:3] == ("container", "ls"):
                return completed(
                    command,
                    stdout=((container_id + "\n").encode("ascii") if owned else b""),
                )
            if command[1] == "rm":
                self.assertEqual(command[-1], container_id)
                owned = False
                return completed(command)
            if command[1] == "exec" and "ready" in command[-1]:
                return completed(command)
            if command[1] == "exec" and command[-1].endswith("identity_openid"):
                return completed(command, stdout=b"config_url=\n")
            if command[1] == "exec" and command[-1].endswith("identity_ldap"):
                return completed(command, stdout=b"server_addr=\n")
            raise AssertionError(command)

        with mock.patch.object(GATE, "_run", side_effect=fake_run):
            self.assertEqual(
                GATE._feature_config("docker", "fixture:reviewed"),
                ("config_url=", "server_addr="),
            )

        run = recorded[0]
        for required in (
            "--platform",
            "linux/amd64",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "no-new-privileges:true",
            "127.0.0.1:9000",
        ):
            self.assertIn(required, run)
        self.assertNotIn("--publish", run)
        owner_offset = run.index("--label")
        self.assertRegex(
            run[owner_offset + 1],
            r"^io\.hbcb\.minio-fixture-owner=[0-9a-f]{32}$",
        )
        self.assertTrue(any(command[1:3] == ("rm", "--force") for command in recorded))
        self.assertEqual(recorded[-1][1:3], ("container", "ls"))

    def test_malformed_container_id_still_triggers_cleanup(self) -> None:
        calls: list[tuple[str, ...]] = []
        container_id = "c" * 64
        owned = True

        def fake_run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
            nonlocal owned
            command = tuple(command)
            calls.append(command)
            if command[1] == "run":
                return completed(command, stdout=b"not-a-container-id\n")
            if command[1:3] == ("container", "ls"):
                return completed(
                    command,
                    stdout=((container_id + "\n").encode("ascii") if owned else b""),
                )
            if command[1] == "rm":
                self.assertEqual(command[-1], container_id)
                owned = False
            return completed(command)

        with mock.patch.object(GATE, "_run", side_effect=fake_run):
            with self.assertRaisesRegex(GATE.GateError, "container ID is invalid"):
                GATE._feature_config("docker", "fixture:reviewed")
        self.assertTrue(any(command[1:3] == ("rm", "--force") for command in calls))
        self.assertEqual(calls[-1][1:3], ("container", "ls"))

    def test_foreign_same_name_conflict_is_never_removed(self) -> None:
        calls: list[tuple[str, ...]] = []

        def fake_run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
            command = tuple(command)
            calls.append(command)
            if command[1] == "run":
                raise GATE.GateError("a bounded Docker operation failed")
            if command[1:3] == ("container", "ls"):
                # The exact-name foreign container lacks the random owner label,
                # so the conjunction query intentionally returns no IDs.
                return completed(command, stdout=b"")
            raise AssertionError(command)

        with mock.patch.object(GATE, "_run", side_effect=fake_run):
            with self.assertRaisesRegex(GATE.GateError, "bounded Docker operation failed"):
                GATE._feature_config("docker", "fixture:reviewed")
        ownership_queries = [
            command for command in calls if command[1:3] == ("container", "ls")
        ]
        self.assertTrue(ownership_queries)
        for query in ownership_queries:
            self.assertIn("--no-trunc", query)
            self.assertTrue(any(item.startswith("name=^/hbcb-minio-security-") for item in query))
            self.assertTrue(
                any(item.startswith("label=io.hbcb.minio-fixture-owner=") for item in query)
            )
        self.assertFalse(any(command[1] == "rm" for command in calls))

    def test_ambiguous_run_failure_removes_owned_partial_create_by_id(self) -> None:
        container_id = "c" * 64
        owned = True

        def fake_run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
            nonlocal owned
            command = tuple(command)
            if command[1] == "run":
                raise GATE.GateError("a bounded Docker operation failed")
            if command[1] == "rm":
                self.assertEqual(command[-1], container_id)
                owned = False
                return completed(command)
            if command[1:3] == ("container", "ls"):
                return completed(
                    command,
                    stdout=((container_id + "\n").encode("ascii") if owned else b""),
                )
            raise AssertionError(command)

        with mock.patch.object(GATE, "_run", side_effect=fake_run):
            with self.assertRaisesRegex(GATE.GateError, "bounded Docker operation failed"):
                GATE._feature_config("docker", "fixture:reviewed")
        self.assertFalse(owned)

    def test_failed_cleanup_is_fatal_when_the_owned_container_remains(self) -> None:
        container_id = "c" * 64

        def fake_run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
            command = tuple(command)
            if command[1] == "run":
                raise GATE.GateError("a bounded Docker operation failed")
            if command[1] == "rm":
                self.assertEqual(command[-1], container_id)
                return completed(command, returncode=1)
            if command[1:3] == ("container", "ls"):
                return completed(command, stdout=(container_id + "\n").encode("ascii"))
            raise AssertionError(command)

        with mock.patch.object(GATE, "_run", side_effect=fake_run):
            with self.assertRaisesRegex(GATE.GateError, "could not be removed"):
                GATE._feature_config("docker", "fixture:reviewed")

    @unittest.skipUnless(os.name == "posix", "POSIX signal semantics required")
    def test_signals_are_deferred_until_named_fixture_cleanup_finishes(self) -> None:
        calls: list[tuple[str, ...]] = []
        container_id = "d" * 64
        owned = True

        def fake_run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
            nonlocal owned
            command = tuple(command)
            calls.append(command)
            if command[1] == "run":
                os.kill(os.getpid(), signal.SIGTERM)
                return completed(command, stdout=b"not-a-container-id\n")
            if command[1:3] == ("container", "ls"):
                return completed(
                    command,
                    stdout=((container_id + "\n").encode("ascii") if owned else b""),
                )
            if command[1] == "rm":
                os.kill(os.getpid(), signal.SIGHUP)
                self.assertEqual(command[-1], container_id)
                owned = False
                return completed(command)
            raise AssertionError(command)

        with mock.patch.object(GATE, "_run", side_effect=fake_run):
            with self.assertRaises(GATE._TerminationSignal) as raised:
                GATE._feature_config("docker", "fixture:reviewed")
        self.assertEqual(raised.exception.signum, signal.SIGTERM)
        self.assertTrue(any(command[1:3] == ("rm", "--force") for command in calls))
        self.assertEqual(calls[-1][1:3], ("container", "ls"))

    def test_execute_requires_disabled_features_and_emits_bounded_evidence(self) -> None:
        server = f"minio version DEVELOPMENT.GOGET (commit-id={GATE.SERVER_REVISION})\n"
        client = f"mc version DEVELOPMENT.GOGET (commit-id={GATE.CLIENT_REVISION})\n"
        output = io.StringIO()
        with (
            mock.patch.object(GATE, "_inspect", return_value=valid_document()),
            mock.patch.object(GATE, "_runtime_version", side_effect=(server, client)),
            mock.patch.object(GATE, "_feature_config", return_value=("config_url=", "server_addr=")),
            redirect_stdout(output),
        ):
            self.assertEqual(GATE.execute("docker", "fixture:reviewed"), 0)
        evidence = json.loads(output.getvalue())
        self.assertEqual(evidence["status"], "pass")
        self.assertEqual(evidence["platform"], "linux/amd64")

        for feature_output in (("config_url=https://idp.invalid", "server_addr="), ("config_url=", "server_addr=ldap.invalid")):
            with (
                mock.patch.object(GATE, "_inspect", return_value=valid_document()),
                mock.patch.object(GATE, "_runtime_version", side_effect=(server, client)),
                mock.patch.object(GATE, "_feature_config", return_value=feature_output),
            ):
                with self.assertRaises(GATE.GateError):
                    GATE.execute("docker", "fixture:reviewed")

    def test_unsafe_tool_and_image_are_rejected_before_inspection(self) -> None:
        with mock.patch.object(GATE, "_inspect") as inspect:
            for docker, image in (("-docker", "fixture:reviewed"), ("docker", "-fixture")):
                with self.subTest(docker=docker, image=image):
                    with self.assertRaises(GATE.GateError):
                        GATE.execute(docker, image)
            inspect.assert_not_called()

    def test_absolute_executable_selector_is_supported(self) -> None:
        server = f"minio version DEVELOPMENT.GOGET (commit-id={GATE.SERVER_REVISION})\n"
        client = f"mc version DEVELOPMENT.GOGET (commit-id={GATE.CLIENT_REVISION})\n"
        with (
            mock.patch.object(GATE, "_inspect", return_value=valid_document()) as inspect,
            mock.patch.object(GATE, "_runtime_version", side_effect=(server, client)),
            mock.patch.object(
                GATE,
                "_feature_config",
                return_value=("config_url=", "server_addr="),
            ),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(GATE.execute(sys.executable, "fixture:reviewed"), 0)
        inspect.assert_called_once_with(sys.executable, "fixture:reviewed")


if __name__ == "__main__":
    unittest.main()
