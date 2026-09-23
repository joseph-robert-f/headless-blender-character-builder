from __future__ import annotations

import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tarfile
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
TEST_IMAGE_ID = "sha256:" + "a" * 64
TEST_CONFIG_ID = "sha256:" + "b" * 64


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
        "Id": TEST_IMAGE_ID,
        "Os": "linux",
        "Architecture": "amd64",
        "Config": {
            "Entrypoint": ["docker-entrypoint.sh"],
            "Cmd": ["postgres"],
            "User": "70:70",
            "WorkingDir": "/",
            "StopSignal": "SIGINT",
            "ExposedPorts": {"5432/tcp": {}},
            "Env": [
                "PG_MAJOR=16",
                "PG_VERSION=16.15",
                "PG_SHA256=c1575341fa7bd40f5274ea465b34390f4dc64cdd0770af327005caaeb9f6b7ed",
                "PGDATA=/var/lib/postgresql/data",
                "DOCKER_PG_LLVM_DEPS=llvm21-dev \t\tclang21",
            ],
            "Volumes": {"/var/lib/postgresql/data": {}},
            "Labels": {
                "org.opencontainers.image.version": GATE.EXPECTED_VERSION,
                "org.opencontainers.image.revision": GATE.EXPECTED_UPSTREAM_REVISION,
                "org.opencontainers.image.source": GATE.EXPECTED_UPSTREAM_SOURCE,
                "org.opencontainers.image.licenses": "PostgreSQL",
                "org.opencontainers.image.base.name": "postgres:16.15-alpine3.24",
                "org.opencontainers.image.base.digest": "sha256:"
                + GATE.EXPECTED_BASE_IMAGE.rsplit("sha256:", 1)[1],
                "io.hbcb.postgres.recipe-id": GATE.EXPECTED_RECIPE_ID,
            },
        },
    }


class PostgresSecurityGateTests(unittest.TestCase):
    def test_docker_failure_names_operation_without_exposing_arguments(self) -> None:
        def fail(_command: tuple[str, ...], **options: object) -> None:
            raise GATE.GateError(str(options["check_failure_message"]))

        with mock.patch.object(GATE.fixture_gate_common, "_run", side_effect=fail):
            with self.assertRaisesRegex(GATE.GateError, "during Docker run") as raised:
                GATE._run(("docker", "run", "--env", "POSTGRES_PASSWORD=private"))
            self.assertNotIn("private", str(raised.exception))
            with self.assertRaisesRegex(GATE.GateError, "during Docker image save"):
                GATE._run(("docker", "image", "save", "--output", "/tmp/private"))

    def test_parent_termination_grace_exceeds_owned_operation_and_cleanup_bound(self) -> None:
        cleanup_bound = (
            GATE.CLEANUP_DOCKER_TIMEOUT_SECONDS
            * GATE.CLEANUP_DOCKER_OPERATION_COUNT
        )
        self.assertGreater(
            SCAN.POSTGRES_GATE_TERM_GRACE_SECONDS,
            (GATE.CHILD_TERMINATION_GRACE_SECONDS * 2) + cleanup_bound,
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
        self.assertEqual(
            GATE._validate_image(valid_document(), TEST_IMAGE_ID),
            TEST_IMAGE_ID,
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
            ("User", ""),
            ("Volumes", {}),
        ):
            document = valid_document()
            config = document["Config"]
            assert isinstance(config, dict)
            config[field] = value
            mutations.append(document)
        document = valid_document()
        environment = document["Config"]["Env"]  # type: ignore[index]
        environment.append("GOSU_VERSION=1.19")  # type: ignore[union-attr]
        mutations.append(document)
        document = valid_document()
        environment = document["Config"]["Env"]  # type: ignore[index]
        environment.remove("DOCKER_PG_LLVM_DEPS=llvm21-dev \t\tclang21")  # type: ignore[union-attr]
        mutations.append(document)
        document = valid_document()
        document["Config"]["Labels"]["io.hbcb.postgres.recipe-id"] = "changed"  # type: ignore[index]
        mutations.append(document)

        for document in mutations:
            with self.subTest(document=document), self.assertRaises(GATE.GateError):
                GATE._validate_image(document, TEST_IMAGE_ID)
        with self.assertRaisesRegex(GATE.GateError, "exact image ID"):
            GATE._validate_image(valid_document(), "postgres:latest")

    def test_prebuilt_selection_binds_runnable_and_archive_config_ids(self) -> None:
        selected = valid_document()
        selected["Descriptor"] = {"digest": TEST_IMAGE_ID}
        with mock.patch.object(GATE, "_inspect_tag", return_value=selected), mock.patch.object(
            GATE, "_inspect_image", return_value=valid_document()
        ), mock.patch.object(
            GATE, "_exported_config_id", return_value=TEST_CONFIG_ID
        ):
            self.assertEqual(
                GATE._validate_selected_image(
                    "docker", TEST_IMAGE_ID, TEST_CONFIG_ID
                ),
                TEST_IMAGE_ID,
            )
            with self.assertRaisesRegex(GATE.GateError, "config identity changed"):
                GATE._validate_selected_image(
                    "docker", TEST_IMAGE_ID, "sha256:" + "c" * 64
                )

    def test_archive_config_identity_is_content_derived_and_platform_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "image.tar"
            config_payload = json.dumps(
                {"architecture": "amd64", "config": {}, "os": "linux"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            config_name = "config.json"
            manifest_payload = json.dumps(
                [{"Config": config_name, "Layers": [], "RepoTags": None}],
                separators=(",", ":"),
            ).encode("ascii")
            with tarfile.open(archive, "w") as handle:
                for name, payload in (
                    ("manifest.json", manifest_payload),
                    (config_name, config_payload),
                ):
                    member = tarfile.TarInfo(name)
                    member.size = len(payload)
                    handle.addfile(member, io.BytesIO(payload))
            expected = "sha256:" + __import__("hashlib").sha256(config_payload).hexdigest()
            self.assertEqual(GATE._archive_config_id(archive), expected)

            wrong_platform = json.dumps(
                {"architecture": "arm64", "config": {}, "os": "linux"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            with tarfile.open(archive, "w") as handle:
                for name, payload in (
                    ("manifest.json", manifest_payload),
                    (config_name, wrong_platform),
                ):
                    member = tarfile.TarInfo(name)
                    member.size = len(payload)
                    handle.addfile(member, io.BytesIO(payload))
            with self.assertRaisesRegex(GATE.GateError, "archive config is invalid"):
                GATE._archive_config_id(archive)

    def test_runtime_gate_is_hardened_proves_uid_and_removes_owned_resources(self) -> None:
        calls: list[tuple[str, ...]] = []
        container_id = "c" * 64
        container_owned = False
        volume_owned = False
        resource_name = ""
        owner_label = ""
        poll_attempts = 0

        def is_poll(command: tuple[str, ...]) -> bool:
            return (
                len(command) >= 4
                and command[3] == "/bin/sh"
                and "pg_isready" in command[-1]
            )

        def fake_run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
            nonlocal container_owned, volume_owned, resource_name, owner_label, poll_attempts
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
                if is_poll(command):
                    poll_attempts += 1
                    if poll_attempts == 1:
                        # Simulates the entrypoint's temporary initdb
                        # bootstrap server still running as PID 1: the
                        # compound check must fail on this iteration
                        # rather than accepting a one-shot pg_isready.
                        return completed(command, returncode=1)
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
            observed_id = GATE._runtime_gate("docker", TEST_IMAGE_ID)

        self.assertEqual(observed_id, container_id)
        self.assertEqual(poll_attempts, 2)
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
            TEST_IMAGE_ID,
        ):
            self.assertIn(required, run)
        self.assertNotIn("--publish", run)
        self.assertFalse(any("/usr/local/bin/gosu" in item for item in run))
        polls = [command for command in calls if command[1:3] == ("exec", container_id) and is_poll(command)]
        self.assertEqual(len(polls), 2)
        for poll in polls:
            self.assertEqual(poll[3:6], ("/bin/sh", "-eu", "-c"))
            self.assertIn('test "$(cat /proc/1/comm)" = postgres', poll[-1])
            self.assertIn(
                "exec pg_isready --quiet --username hbcb_gate --dbname hbcb_gate",
                poll[-1],
            )
        proof = next(
            command
            for command in calls
            if command[1:3] == ("exec", container_id)
            and "/bin/sh" in command
            and not is_poll(command)
        )
        script = proof[-1]
        for required in (
            "/proc/1/status",
            "/proc/1/comm",
            "/proc/1/cmdline",
            GATE.EXPECTED_ENTRYPOINT_SHA256,
            "test ! -e /usr/local/bin/gosu",
            "test ! -L /usr/local/bin/gosu",
            "PGDATA/PG_VERSION",
            "current_database()",
        ):
            self.assertIn(required, script)
        self.assertFalse(container_owned)
        self.assertFalse(volume_owned)
        self.assertEqual(calls[-1][1:3], ("volume", "ls"))

    def test_invalid_owned_build_is_removed_but_foreign_race_winner_survives(self) -> None:
        tag = "hbcb-postgres-security-build-" + "b" * 16 + ":local"
        owner_label = GATE.BUILD_OWNER_LABEL_KEY + "=" + "c" * 32
        owned = valid_document()
        owned["Config"]["Labels"][GATE.BUILD_OWNER_LABEL_KEY] = "c" * 32  # type: ignore[index]
        foreign = valid_document()
        foreign["Config"]["Labels"][GATE.BUILD_OWNER_LABEL_KEY] = "d" * 32  # type: ignore[index]

        for document, removed in ((owned, True), (foreign, False)):
            calls: list[tuple[str, ...]] = []
            present = True

            def fake_run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
                nonlocal present
                command = tuple(command)
                calls.append(command)
                if command[1:3] == ("image", "ls"):
                    return completed(command, stdout=((TEST_IMAGE_ID + "\n").encode() if present else b""))
                if command[1:3] == ("image", "inspect"):
                    return completed(command, stdout=json.dumps([document]).encode())
                if command[1:3] == ("image", "rm"):
                    present = False
                    return completed(command)
                raise AssertionError(command)

            with mock.patch.object(GATE, "_run", side_effect=fake_run):
                if removed:
                    GATE._remove_owned_image_tag("docker", tag, owner_label, None)
                else:
                    with self.assertRaisesRegex(GATE.GateError, "not owned"):
                        GATE._remove_owned_image_tag("docker", tag, owner_label, None)
            self.assertEqual(any(call[1:3] == ("image", "rm") for call in calls), removed)

    def test_build_tag_query_error_fails_closed(self) -> None:
        with mock.patch.object(
            GATE,
            "_run",
            return_value=completed(("docker", "image", "ls"), returncode=1),
        ):
            with self.assertRaisesRegex(GATE.GateError, "could not be queried"):
                GATE._tag_image_ids("docker", "hbcb-postgres-security-build-" + "a" * 16 + ":local")

    @unittest.skipUnless(os.name == "posix", "POSIX process groups required")
    def test_live_signal_reaps_term_resistant_descendant_after_leader_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            identity = Path(temporary) / "group"
            script = (
                "import os,signal,subprocess,sys; "
                "child=subprocess.Popen([sys.executable,'-c',"
                "'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)']); "
                "open(sys.argv[1],'w').write(str(os.getpgrp())+'|'+str(child.pid))"
            )
            timer = threading.Timer(0.3, os.kill, (os.getpid(), signal.SIGTERM))
            started = time.monotonic()
            with self.assertRaises(GATE._TerminationSignal) as raised:
                with GATE._TerminationGuard():
                    timer.start()
                    GATE._run((sys.executable, "-c", script, str(identity)), timeout=10)
            timer.join(timeout=2)
            self.assertEqual(raised.exception.signum, signal.SIGTERM)
            self.assertLess(time.monotonic() - started, 8)
            process_group = int(identity.read_text(encoding="ascii").split("|", 1)[0])
            self.assertFalse(GATE._process_group_exists(process_group))

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
                GATE._runtime_gate("docker", TEST_IMAGE_ID)
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
                GATE._runtime_gate("docker", TEST_IMAGE_ID)
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
                GATE._runtime_gate("docker", TEST_IMAGE_ID)
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
                GATE._runtime_gate("docker", TEST_IMAGE_ID)
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
                GATE._runtime_gate("docker", TEST_IMAGE_ID)
        self.assertEqual(raised.exception.signum, signal.SIGTERM)
        self.assertFalse(container_owned)
        self.assertFalse(volume_owned)
        self.assertTrue(any(command[1:3] == ("rm", "--force") for command in calls))
        self.assertTrue(any(command[1:3] == ("volume", "rm") for command in calls))
        self.assertEqual(calls[-1][1:3], ("volume", "ls"))

    def test_execute_inspects_exact_image_id_and_emits_bounded_evidence(self) -> None:
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
            return_value="e" * 64,
        ), mock.patch.object(
            GATE,
            "_exported_config_id",
            return_value=TEST_CONFIG_ID,
        ), redirect_stdout(output):
            self.assertEqual(
                GATE.execute("docker", TEST_IMAGE_ID, TEST_CONFIG_ID), 0
            )
        self.assertEqual(
            calls[0],
            (
                "docker",
                "image",
                "inspect",
                TEST_IMAGE_ID,
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
                TEST_IMAGE_ID,
            ),
        )
        evidence = json.loads(output.getvalue())
        self.assertEqual(evidence["status"], "pass")
        self.assertEqual(evidence["runtime_uid"], 70)
        self.assertEqual(evidence["image_id"], TEST_IMAGE_ID)
        self.assertFalse(evidence["gosu_present"])
        self.assertEqual(evidence["linux_amd64_config_id"], TEST_CONFIG_ID)
        self.assertEqual(evidence["base_image_reference"], GATE.EXPECTED_BASE_IMAGE)

    def test_prebuilt_execution_requires_both_exact_ids(self) -> None:
        for image, config in (
            (TEST_IMAGE_ID, None),
            (None, TEST_CONFIG_ID),
            ("postgres:latest", TEST_CONFIG_ID),
            (TEST_IMAGE_ID, "config-latest"),
        ):
            with self.subTest(image=image, config=config), self.assertRaises(GATE.GateError):
                GATE.execute("docker", image, config)


if __name__ == "__main__":
    unittest.main()
