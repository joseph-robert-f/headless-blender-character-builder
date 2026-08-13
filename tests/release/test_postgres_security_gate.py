from __future__ import annotations

import importlib.util
import io
import json
import os
import signal
import subprocess
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests.release.support import load_script


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tests" / "security" / "postgres_fixture_gate.py"
SPEC = importlib.util.spec_from_file_location("hbcb_postgres_fixture_gate", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
SCAN = load_script("hbcb_postgres_gate_dependency_scan", "dependency-scan")


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
            "Entrypoint": ["docker-entrypoint.sh"],
            "Cmd": ["postgres"],
            "Env": [
                "GOSU_VERSION=1.19",
                "PG_MAJOR=16",
                "PG_VERSION=16.14",
                "PGDATA=/var/lib/postgresql/data",
            ],
            "Volumes": {"/var/lib/postgresql/data": {}},
        },
    }


class PostgresSecurityGateTests(unittest.TestCase):
    def test_parent_termination_grace_exceeds_owned_operation_and_cleanup_bound(self) -> None:
        cleanup_bound = (
            GATE.CLEANUP_DOCKER_TIMEOUT_SECONDS
            * GATE.CLEANUP_DOCKER_OPERATION_COUNT
        )
        self.assertGreater(
            SCAN.POSTGRES_GATE_TERM_GRACE_SECONDS,
            GATE.MAX_OWNED_RUNTIME_DOCKER_TIMEOUT_SECONDS + cleanup_bound,
        )

    def test_make_target_uses_the_exact_gate_and_image(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        target = makefile.split("\npostgres-security-check:\n", 1)[1].split(
            "\n\n", 1
        )[0]
        self.assertIn("tests/security/postgres_fixture_gate.py", target)
        self.assertIn('--docker "$(DOCKER)"', target)
        self.assertNotIn("--image", target)

    def test_image_contract_is_exact_and_mutations_fail(self) -> None:
        expected_id = "sha256:" + "a" * 64
        self.assertEqual(
            GATE._validate_image(valid_document(), GATE.EXPECTED_IMAGE),
            expected_id,
        )
        mutations = []
        for field, value in (
            ("Id", "a" * 64),
            ("Os", "darwin"),
            ("Architecture", "arm64"),
        ):
            document = valid_document()
            document[field] = value
            mutations.append(document)
        for field, value in (
            ("Entrypoint", ["/bin/sh"]),
            ("Cmd", ["postgres", "--help"]),
            ("Volumes", {}),
        ):
            document = valid_document()
            config = document["Config"]
            assert isinstance(config, dict)
            config[field] = value
            mutations.append(document)
        document = valid_document()
        environment = document["Config"]["Env"]  # type: ignore[index]
        environment.remove("GOSU_VERSION=1.19")  # type: ignore[union-attr]
        mutations.append(document)

        for document in mutations:
            with self.subTest(document=document), self.assertRaises(GATE.GateError):
                GATE._validate_image(document, GATE.EXPECTED_IMAGE)
        with self.assertRaisesRegex(GATE.GateError, "reviewed exact pin"):
            GATE._validate_image(valid_document(), "postgres:latest")

    def test_runtime_gate_is_hardened_proves_uid_and_removes_owned_resources(self) -> None:
        calls: list[tuple[str, ...]] = []
        container_id = "c" * 64
        container_owned = False
        volume_owned = False
        resource_name = ""
        owner_label = ""

        def fake_run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
            nonlocal container_owned, volume_owned, resource_name, owner_label
            command = tuple(command)
            calls.append(command)
            if command[1:3] == ("volume", "create"):
                owner_label = command[command.index("--label") + 1]
                resource_name = command[-1]
                volume_owned = True
                return completed(command, stdout=(resource_name + "\n").encode("ascii"))
            if command[1:3] == ("volume", "ls"):
                return completed(
                    command,
                    stdout=((resource_name + "\n").encode("ascii") if volume_owned else b""),
                )
            if command[1:3] == ("run", "--detach"):
                container_owned = True
                return completed(command, stdout=(container_id + "\n").encode("ascii"))
            if command[1:3] == ("container", "ls"):
                return completed(
                    command,
                    stdout=((container_id + "\n").encode("ascii") if container_owned else b""),
                )
            if command[1:3] == ("exec", container_id):
                if "pg_isready" in command:
                    return completed(command)
                return completed(command, stdout=b"hbcb_gate|hbcb_gate\n")
            if command[1:3] == ("rm", "--force"):
                self.assertEqual(command[-1], container_id)
                container_owned = False
                return completed(command)
            if command[1:3] == ("volume", "rm"):
                self.assertEqual(command[-1], resource_name)
                volume_owned = False
                return completed(command)
            raise AssertionError(command)

        with mock.patch.object(GATE, "_run", side_effect=fake_run):
            observed_id, sentinel_sha = GATE._runtime_gate("docker", GATE.EXPECTED_IMAGE)

        self.assertEqual(observed_id, container_id)
        self.assertRegex(sentinel_sha, r"^[0-9a-f]{64}$")
        run = next(command for command in calls if command[1:3] == ("run", "--detach"))
        self.assertRegex(resource_name, GATE.RESOURCE_NAME)
        self.assertRegex(owner_label, r"^io\.hbcb\.postgres-fixture-owner=[0-9a-f]{32}$")
        for required in (
            "--platform",
            "linux/amd64",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "no-new-privileges:true",
            "--user",
            "70:70",
            GATE.EXPECTED_IMAGE,
        ):
            self.assertIn(required, run)
        self.assertNotIn("--publish", run)
        self.assertTrue(any("target=/usr/local/bin/gosu,readonly" in item for item in run))
        proof = next(
            command
            for command in calls
            if command[1:3] == ("exec", container_id) and "/bin/sh" in command
        )
        script = proof[-1]
        for required in (
            "/proc/1/status",
            "/proc/1/comm",
            "/proc/1/cmdline",
            GATE.EXPECTED_ENTRYPOINT_SHA256,
            sentinel_sha,
            "PGDATA/PG_VERSION",
            "current_database()",
        ):
            self.assertIn(required, script)
        self.assertFalse(container_owned)
        self.assertFalse(volume_owned)
        self.assertEqual(calls[-1][1:3], ("volume", "ls"))

    def test_ambiguous_start_failure_removes_only_owned_resources(self) -> None:
        calls: list[tuple[str, ...]] = []
        container_id = "d" * 64
        container_owned = False
        volume_owned = False
        resource_name = ""

        def fake_run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
            nonlocal container_owned, volume_owned, resource_name
            command = tuple(command)
            calls.append(command)
            if command[1:3] == ("volume", "create"):
                resource_name = command[-1]
                volume_owned = True
                return completed(command, stdout=(resource_name + "\n").encode("ascii"))
            if command[1:3] == ("volume", "ls"):
                return completed(
                    command,
                    stdout=((resource_name + "\n").encode("ascii") if volume_owned else b""),
                )
            if command[1:3] == ("run", "--detach"):
                container_owned = True
                return completed(command, stdout=b"not-a-container-id\n")
            if command[1:3] == ("container", "ls"):
                return completed(
                    command,
                    stdout=((container_id + "\n").encode("ascii") if container_owned else b""),
                )
            if command[1:3] == ("rm", "--force"):
                self.assertEqual(command[-1], container_id)
                container_owned = False
                return completed(command)
            if command[1:3] == ("volume", "rm"):
                self.assertEqual(command[-1], resource_name)
                volume_owned = False
                return completed(command)
            raise AssertionError(command)

        with mock.patch.object(GATE, "_run", side_effect=fake_run):
            with self.assertRaisesRegex(GATE.GateError, "container ID is invalid"):
                GATE._runtime_gate("docker", GATE.EXPECTED_IMAGE)
        self.assertFalse(container_owned)
        self.assertFalse(volume_owned)
        self.assertTrue(any(command[1:3] == ("rm", "--force") for command in calls))

    def test_foreign_same_name_volume_is_never_removed(self) -> None:
        calls: list[tuple[str, ...]] = []

        def fake_run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
            command = tuple(command)
            calls.append(command)
            if command[1:3] == ("volume", "create"):
                return completed(command, stdout=(command[-1] + "\n").encode("ascii"))
            if command[1:3] in (("volume", "ls"), ("container", "ls")):
                return completed(command)
            raise AssertionError(command)

        with mock.patch.object(GATE, "_run", side_effect=fake_run):
            with self.assertRaisesRegex(GATE.GateError, "volume ownership is invalid"):
                GATE._runtime_gate("docker", GATE.EXPECTED_IMAGE)
        self.assertFalse(any(command[1:3] == ("volume", "rm") for command in calls))
        self.assertFalse(any(command[1:3] == ("rm", "--force") for command in calls))

    def test_container_cleanup_failure_still_attempts_volume_cleanup(self) -> None:
        container_failure = GATE.GateError("container cleanup failure")
        operation_failure = GATE.GateError("fixture operation failure")
        with mock.patch.object(
            GATE,
            "_run",
            side_effect=operation_failure,
        ), mock.patch.object(
            GATE,
            "_remove_owned_container",
            side_effect=container_failure,
        ) as container_cleanup, mock.patch.object(
            GATE,
            "_remove_owned_volume",
        ) as volume_cleanup:
            with self.assertRaisesRegex(
                GATE.GateError,
                "container: container cleanup failure",
            ) as raised:
                GATE._runtime_gate("docker", GATE.EXPECTED_IMAGE)
        container_cleanup.assert_called_once()
        volume_cleanup.assert_called_once()
        self.assertIs(raised.exception.__context__, operation_failure)

    def test_both_cleanup_failures_are_aggregated(self) -> None:
        with mock.patch.object(
            GATE,
            "_run",
            side_effect=GATE.GateError("fixture operation failure"),
        ), mock.patch.object(
            GATE,
            "_remove_owned_container",
            side_effect=GATE.GateError("container cleanup failure"),
        ), mock.patch.object(
            GATE,
            "_remove_owned_volume",
            side_effect=GATE.GateError("volume cleanup failure"),
        ):
            with self.assertRaises(GATE.GateError) as raised:
                GATE._runtime_gate("docker", GATE.EXPECTED_IMAGE)
        self.assertIn("container: container cleanup failure", str(raised.exception))
        self.assertIn("volume: volume cleanup failure", str(raised.exception))

    @unittest.skipUnless(os.name == "posix", "POSIX signal semantics required")
    def test_signals_are_deferred_until_owned_cleanup_finishes(self) -> None:
        calls: list[tuple[str, ...]] = []
        container_id = "e" * 64
        container_owned = False
        volume_owned = False
        resource_name = ""

        def fake_run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
            nonlocal container_owned, volume_owned, resource_name
            command = tuple(command)
            calls.append(command)
            if command[1:3] == ("volume", "create"):
                resource_name = command[-1]
                volume_owned = True
                return completed(command, stdout=(resource_name + "\n").encode("ascii"))
            if command[1:3] == ("volume", "ls"):
                return completed(
                    command,
                    stdout=((resource_name + "\n").encode("ascii") if volume_owned else b""),
                )
            if command[1:3] == ("run", "--detach"):
                container_owned = True
                os.kill(os.getpid(), signal.SIGTERM)
                return completed(command, stdout=b"not-a-container-id\n")
            if command[1:3] == ("container", "ls"):
                return completed(
                    command,
                    stdout=((container_id + "\n").encode("ascii") if container_owned else b""),
                )
            if command[1:3] == ("rm", "--force"):
                os.kill(os.getpid(), signal.SIGHUP)
                container_owned = False
                return completed(command)
            if command[1:3] == ("volume", "rm"):
                volume_owned = False
                return completed(command)
            raise AssertionError(command)

        with mock.patch.object(GATE, "_run", side_effect=fake_run):
            with self.assertRaises(GATE._TerminationSignal) as raised:
                GATE._runtime_gate("docker", GATE.EXPECTED_IMAGE)
        self.assertEqual(raised.exception.signum, signal.SIGTERM)
        self.assertFalse(container_owned)
        self.assertFalse(volume_owned)
        self.assertTrue(any(command[1:3] == ("rm", "--force") for command in calls))
        self.assertTrue(any(command[1:3] == ("volume", "rm") for command in calls))
        self.assertEqual(calls[-1][1:3], ("volume", "ls"))

    def test_execute_pulls_exact_image_and_emits_bounded_evidence(self) -> None:
        calls: list[tuple[str, ...]] = []

        def fake_run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
            command = tuple(command)
            calls.append(command)
            if command[1:3] == ("image", "inspect"):
                return completed(command, stdout=json.dumps([valid_document()]).encode("utf-8"))
            return completed(command)

        output = io.StringIO()
        with mock.patch.object(GATE, "_run", side_effect=fake_run), mock.patch.object(
            GATE,
            "_runtime_gate",
            return_value=("e" * 64, "f" * 64),
        ), redirect_stdout(output):
            self.assertEqual(GATE.execute("docker", GATE.EXPECTED_IMAGE), 0)
        self.assertEqual(
            calls[0],
            (
                "docker",
                "pull",
                "--quiet",
                "--platform",
                "linux/amd64",
                GATE.EXPECTED_IMAGE,
            ),
        )
        self.assertEqual(
            calls[1],
            (
                "docker",
                "image",
                "inspect",
                "--platform",
                "linux/amd64",
                GATE.EXPECTED_IMAGE,
            ),
        )
        evidence = json.loads(output.getvalue())
        self.assertEqual(evidence["status"], "pass")
        self.assertEqual(evidence["runtime_uid"], 70)
        self.assertEqual(evidence["image_reference"], GATE.EXPECTED_IMAGE)


if __name__ == "__main__":
    unittest.main()
