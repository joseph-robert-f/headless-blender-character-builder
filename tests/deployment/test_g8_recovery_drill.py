from __future__ import annotations

import importlib.machinery
import importlib.util
import ast
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "g8-recovery-drill"
COMPOSE = ROOT / "tests" / "deployment" / "g8_recovery_compose.yaml"
LOADER = importlib.machinery.SourceFileLoader("g8_recovery_drill_under_test", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
recovery = importlib.util.module_from_spec(SPEC)
sys.modules[LOADER.name] = recovery
LOADER.exec_module(recovery)


def source_environment() -> dict[str, str]:
    return {
        "HBCB_DEPLOYMENT_NAMESPACE": "local",
        "POSTGRES_DB": "hbcb",
        "POSTGRES_USER": "hbcb_admin",
        "HBCB_DATABASE_MAINTENANCE_USER": "hbcb_maintenance",
        "HBCB_DATABASE_MAINTENANCE_PASSWORD": "1" * 64,
        "REDIS_PASSWORD": "2" * 64,
        "HBCB_STORAGE_MAINTENANCE_ACCESS_KEY": "hbcb_maintenance",
        "HBCB_STORAGE_MAINTENANCE_SECRET_KEY": "3" * 64,
        "HBCB_STORAGE_BUCKET": "hbcb-artifacts",
        "HBCB_STORAGE_INTERNAL_ENDPOINT": "minio:9000",
        "HBCB_STORAGE_INTERNAL_SECURE": "false",
        "HBCB_STORAGE_REGION": "us-east-1",
    }


def inventory(version: str) -> dict[str, object]:
    return {
        "artifacts": [
            {
                "build_id": "11111111-1111-4111-8111-111111111111",
                "bucket": "hbcb-artifacts",
                "bytes": 4,
                "namespace": "local",
                "object_key": (
                    "local/v1/builds/11111111-1111-4111-8111-111111111111/"
                    "attempts/1/qa.json"
                ),
                "sha256": "a" * 64,
                "version_id": version,
            }
        ],
        "generated_at": "2026-08-03T12:00:00Z",
        "inventory_version": "backup-inventory/v1",
        "namespace": "local",
    }


class RecoveryDrillTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX signal semantics required")
    def test_each_termination_signal_is_deferred_until_cleanup_finishes(self) -> None:
        for selected in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
            completed_cleanup: list[int] = []
            with self.subTest(signal=selected):
                with self.assertRaises(recovery.GateInterrupted) as raised:
                    with recovery._TerminationGuard():
                        with recovery._CleanupGuard():
                            os.kill(os.getpid(), selected)
                            completed_cleanup.append(selected)
                self.assertEqual(raised.exception.signum, selected)
                self.assertEqual(completed_cleanup, [selected])
                self.assertEqual(recovery._TERMINATION.cleanup_depth, 0)
                self.assertIsNone(recovery._TERMINATION.active)

    @unittest.skipUnless(hasattr(os, "killpg"), "requires POSIX process groups")
    def test_command_runner_timeout_reaps_term_resistant_child_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            started = Path(temporary) / "started"
            survived = Path(temporary) / "survived"
            descendant = (
                "import pathlib,signal,time;"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                f"pathlib.Path({str(started)!r}).write_text('1');"
                "time.sleep(1);"
                f"pathlib.Path({str(survived)!r}).write_text('unsafe')"
            )
            command = (
                sys.executable,
                "-c",
                "import signal,subprocess,sys,time;"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                f"subprocess.Popen([sys.executable,'-c',{descendant!r}]);"
                "time.sleep(60)",
            )
            with (
                mock.patch.object(recovery, "TERMINATION_GRACE_SECONDS", 0.05),
                self.assertRaisesRegex(recovery.GateError, "probe_unavailable"),
            ):
                recovery.CommandRunner().run(command, label="probe", timeout=0.3)
            self.assertTrue(started.exists())
            time.sleep(1.1)
            self.assertFalse(survived.exists())
            self.assertIsNone(recovery._TERMINATION.active)

    @unittest.skipUnless(
        hasattr(signal, "pthread_sigmask") and hasattr(os, "killpg"),
        "requires POSIX signal masks and process groups",
    )
    def test_command_runner_reaps_child_when_pending_signal_fires_during_unmask(
        self,
    ) -> None:
        real_pthread_sigmask = signal.pthread_sigmask
        spawned: list[subprocess.Popen[bytes]] = []
        unmask_returned: list[bool] = []

        def inject_pending_signal(how: int, mask: object) -> object:
            if how == signal.SIG_SETMASK:
                process = recovery._TERMINATION.active
                self.assertIsNotNone(process)
                spawned.append(process)
                os.kill(os.getpid(), signal.SIGINT)
                result = real_pthread_sigmask(how, mask)
                unmask_returned.append(True)
                return result
            return real_pthread_sigmask(how, mask)

        command = (
            sys.executable,
            "-c",
            "import signal,time;"
            "signal.pthread_sigmask(signal.SIG_UNBLOCK,"
            "(signal.SIGHUP,signal.SIGINT,signal.SIGTERM));"
            "time.sleep(60)",
        )
        try:
            with (
                mock.patch.object(recovery, "TERMINATION_GRACE_SECONDS", 0.05),
                mock.patch.object(
                    recovery.signal,
                    "pthread_sigmask",
                    side_effect=inject_pending_signal,
                ),
                self.assertRaises(recovery.GateInterrupted) as raised,
            ):
                with recovery._TerminationGuard():
                    recovery.CommandRunner().run(command, label="probe")
            self.assertEqual(raised.exception.signum, signal.SIGINT)
            self.assertEqual(unmask_returned, [])
            self.assertEqual(len(spawned), 1)
            process = spawned[0]
            self.assertIsNotNone(process.returncode)
            self.assertFalse(recovery._process_group_exists(process.pid))
            self.assertIsNone(recovery._TERMINATION.active)
        finally:
            for process in spawned:
                if process.returncode is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
                for stream in (process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()
                if recovery._TERMINATION.active is process:
                    recovery._TERMINATION.active = None

    def test_interrupted_source_stop_is_always_treated_as_restart_obligation(self) -> None:
        calls: list[tuple[str, ...]] = []

        def source_compose(*arguments: str, **_kwargs: object) -> object:
            calls.append(tuple(arguments))
            if arguments[0] == "stop":
                raise recovery.GateInterrupted(signal.SIGTERM)
            return recovery.CommandResult(b"")

        context = SimpleNamespace(
            source_compose=source_compose,
            target_compose=lambda *_args, **_kwargs: recovery.CommandResult(b""),
            work_root=Path("/fixture/work"),
        )
        running = lambda _context, service: service in {"postgres", "redis", "minio", "api"}
        with (
            mock.patch.object(recovery, "_validate_target_topology"),
            mock.patch.object(recovery, "_source_container_running", side_effect=running),
            mock.patch.object(recovery, "_source_network", return_value="source-network"),
            mock.patch.object(recovery, "_source_maintenance_environment"),
            mock.patch.object(recovery, "_wait_source_service") as wait_source,
            mock.patch.object(recovery, "_remove_work_root"),
            self.assertRaises(recovery.GateInterrupted),
        ):
            recovery.execute_drill(context)
        self.assertIn(("start", "api"), calls)
        wait_source.assert_called_once_with(context, "api", healthy=True)

    def test_interrupted_target_start_always_runs_exact_target_teardown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backup_root = root / "backups"
            source_objects = backup_root / "source-objects"
            source_objects.mkdir(parents=True)
            source_inventory = inventory("source-version")
            payload = json.dumps(source_inventory, sort_keys=True).encode("utf-8")
            (source_objects / "inventory.json").write_bytes(payload)
            calls: list[tuple[str, ...]] = []

            def target_compose(*arguments: str, **_kwargs: object) -> object:
                calls.append(tuple(arguments))
                if "up" in arguments:
                    raise recovery.GateInterrupted(signal.SIGHUP)
                return recovery.CommandResult(b"")

            context = SimpleNamespace(
                source_compose=lambda *_args, **_kwargs: recovery.CommandResult(b""),
                target_compose=target_compose,
                backup_root=backup_root,
                work_root=root,
            )
            maintenance_result = {
                "artifacts": 1,
                "inventory_sha256": recovery.hashlib.sha256(payload).hexdigest(),
            }
            running = lambda _context, service: service in {"postgres", "redis", "minio"}
            with (
                mock.patch.object(recovery, "_validate_target_topology"),
                mock.patch.object(recovery, "_source_container_running", side_effect=running),
                mock.patch.object(recovery, "_source_network", return_value="source-network"),
                mock.patch.object(
                    recovery, "_source_maintenance_environment", return_value=root / "source.env"
                ),
                mock.patch.object(recovery, "_snapshot", return_value="a" * 64),
                mock.patch.object(recovery, "_source_maintenance", return_value=maintenance_result),
                mock.patch.object(recovery, "_validate_private_tree"),
                mock.patch.object(recovery, "_load_inventory", return_value=source_inventory),
                mock.patch.object(recovery, "_database_backup", return_value=(10, "b" * 64)),
                mock.patch.object(recovery, "_verify_target_removed") as verify_removed,
                mock.patch.object(recovery, "_remove_work_root"),
                self.assertRaises(recovery.GateInterrupted),
            ):
                recovery.execute_drill(context)
            self.assertTrue(any("down" in call for call in calls))
            verify_removed.assert_called_once_with(context)

    def test_image_identity_uses_legacy_compatible_inspection_and_checks_platform(self) -> None:
        image_id = "sha256:" + "a" * 64
        calls: list[tuple[object, object, object]] = []

        def inspect(command: object, *, label: object, timeout: object) -> object:
            calls.append((command, label, timeout))
            return recovery.CommandResult(
                ("linux/amd64|" + image_id + "\n").encode("ascii")
            )

        self.assertEqual(
            recovery._image_id(
                SimpleNamespace(run=inspect), "fixture:dev", "fixture_image"
            ),
            image_id,
        )
        self.assertEqual(
            calls,
            [
                (
                    (
                        "docker",
                        "image",
                        "inspect",
                        "--format",
                        "{{.Os}}/{{.Architecture}}|{{.Id}}",
                        "fixture:dev",
                    ),
                    "fixture_image",
                    60,
                )
            ],
        )
        self.assertNotIn("--platform", calls[0][0])

        for output in (
            "linux/arm64|" + image_id,
            image_id,
            "linux/amd64|not-an-image-id",
        ):
            runner = SimpleNamespace(
                run=lambda *_args, value=output, **_kwargs: recovery.CommandResult(
                    (value + "\n").encode("ascii")
                )
            )
            with self.subTest(output=output):
                with self.assertRaisesRegex(recovery.GateError, "fixture_image_invalid"):
                    recovery._image_id(runner, "fixture:dev", "fixture_image")

    def test_selected_project_images_and_docker_binary_are_bounded(self) -> None:
        source = {"HBCB_COMPOSE_PROJECT_NAME": "hbcb-local-fixture"}
        with mock.patch.dict(
            os.environ,
            {
                "DOCKER": "/fixture/docker",
                "COMPOSE_PROJECT_NAME": "hbcb-selected",
                "HBCB_SERVICE_API_IMAGE": "hbcb-selected-api:dev",
                "HBCB_MINIO_IMAGE": "hbcb-selected-minio:dev",
            },
            clear=True,
        ):
            self.assertEqual(recovery._docker_command(), ("/fixture/docker",))
            self.assertEqual(
                recovery._compose_command(), ("/fixture/docker", "compose")
            )
            self.assertEqual(
                recovery._selected_reference(
                    "HBCB_SERVICE_API_IMAGE", "fallback:dev"
                ),
                "hbcb-selected-api:dev",
            )
            self.assertEqual(
                recovery._selected_source_project(source), "hbcb-selected"
            )

        for environment in (
            {"DOCKER": "docker --host hostile"},
            {"DOCKER": "--hostile-docker-option"},
            {"HBCB_SERVICE_API_IMAGE": "bad image"},
            {"HBCB_SERVICE_API_IMAGE": "--hostile-image-option"},
            {"COMPOSE_PROJECT_NAME": "Unsafe.Project"},
        ):
            with self.subTest(environment=environment), mock.patch.dict(
                os.environ, environment, clear=True
            ):
                with self.assertRaises(recovery.GateError):
                    if "DOCKER" in environment:
                        recovery._docker_command()
                    elif "HBCB_SERVICE_API_IMAGE" in environment:
                        recovery._selected_reference(
                            "HBCB_SERVICE_API_IMAGE", "fallback:dev"
                        )
                    else:
                        recovery._selected_source_project(source)

    def test_source_compose_binds_the_selected_source_project(self) -> None:
        captured: list[tuple[str, ...]] = []

        def run(command: object, **_kwargs: object) -> object:
            captured.append(tuple(command))  # type: ignore[arg-type]
            return recovery.CommandResult(b"")

        context = recovery.DrillContext(
            runner=SimpleNamespace(run=run),
            docker=("/fixture/docker",),
            compose=("/fixture/compose",),
            source_environment={},
            source_values={},
            target_environment={},
            source_project_name="hbcb-source",
            project_name="hbcb-target",
            runtime_uid=65532,
            runtime_gid=65532,
            work_root=Path("/fixture/work"),
            backup_root=Path("/fixture/backup"),
            postgres_image="sha256:" + "c" * 64,
            service_image="sha256:" + "a" * 64,
            minio_image="sha256:" + "b" * 64,
        )
        context.source_compose("ps", "--all", label="source")
        self.assertEqual(captured[0][:3], ("/fixture/compose", "--project-name", "hbcb-source"))

    def test_database_backup_binds_the_selected_source_project(self) -> None:
        captured: list[tuple[str, ...]] = []

        def run(command: object, *, stdout: object, **_kwargs: object) -> object:
            captured.append(tuple(command))  # type: ignore[arg-type]
            stdout.write(b"fixture-backup")  # type: ignore[union-attr]
            return recovery.CommandResult(b"")

        context = SimpleNamespace(
            compose=("/fixture/compose",),
            source_project_name="hbcb-source",
            source_values={"POSTGRES_USER": "hbcb_admin", "POSTGRES_DB": "hbcb"},
            source_environment={},
            runner=SimpleNamespace(run=run),
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "database.dump"
            size, digest = recovery._database_backup(context, destination)
        self.assertEqual(size, len(b"fixture-backup"))
        self.assertEqual(digest, recovery.hashlib.sha256(b"fixture-backup").hexdigest())
        self.assertEqual(
            captured[0][:3],
            ("/fixture/compose", "--project-name", "hbcb-source"),
        )

    def test_disposable_compose_has_no_build_or_port_and_one_internal_network(self) -> None:
        text = COMPOSE.read_text(encoding="utf-8")
        self.assertNotIn("\n    ports:", text)
        self.assertNotIn("\n    build:", text)
        self.assertIn("  recovery:\n    internal: true", text)
        self.assertIn("HBCB_G8_POSTGRES_IMAGE", text)
        self.assertRegex(
            text,
            r"(?ms)^  postgres:\n.*?^    user: \"70:70\"$",
        )
        self.assertIn(
            "redis:8.2.8-alpine3.22@sha256:"
            "a7859ed111db3c1f5404a973a4747505d559fb5ca32d37e447afc0ef845a2103",
            text,
        )
        for policy in (
            "auto-aof-rewrite-percentage 100",
            "auto-aof-rewrite-min-size 64mb",
            "maxmemory 384mb",
            "maxmemory-policy noeviction",
        ):
            self.assertIn(policy, text)
        self.assertIn("HBCB_G8_STORAGE_MAINTENANCE_ACCESS_KEY", text)
        self.assertIn("./compose/minio-maintenance-policy.json:/policies/minio-maintenance-policy.json:ro", text)

    def test_script_is_executable_and_contains_finally_cleanup_controls(self) -> None:
        mode = stat.S_IMODE(SCRIPT.stat().st_mode)
        # Git preserves only the executable bit, so a clean checkout is 0755
        # even when the working copy was packaged as 0555.  The deployed
        # root-owned copy is installed 0555; source must at least be executable
        # and never group/world writable.
        self.assertEqual(mode & 0o111, 0o111)
        self.assertEqual(mode & 0o022, 0)
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"down", "--volumes", "--remove-orphans"', text)
        self.assertIn("_verify_target_removed(context)", text)
        self.assertIn("for service in reversed(stopped):", text)
        self.assertNotIn("shell=True", text)

    def test_source_environment_requires_private_mode_and_g8_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            values = source_environment()
            path.write_text(
                "".join(f"{name}={value}\n" for name, value in values.items()),
                encoding="ascii",
            )
            path.chmod(0o600)
            self.assertEqual(recovery._read_source_environment(path), values)

            path.chmod(0o644)
            with self.assertRaisesRegex(recovery.GateError, "unsafe_private_path"):
                recovery._read_source_environment(path)
            path.chmod(0o600)
            missing = dict(values)
            del missing["HBCB_STORAGE_MAINTENANCE_SECRET_KEY"]
            path.write_text(
                "".join(f"{name}={value}\n" for name, value in missing.items()),
                encoding="ascii",
            )
            path.chmod(0o600)
            with self.assertRaisesRegex(
                recovery.GateError, "g8_source_environment_upgrade_required"
            ):
                recovery._read_source_environment(path)

    def test_private_backup_tree_rejects_symlinks_and_permissive_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "backup"
            root.mkdir(mode=0o700)
            payload = root / "inventory.json"
            payload.write_bytes(b"{}")
            payload.chmod(0o600)
            recovery._validate_private_tree(root)
            link = root / "link"
            link.symlink_to(payload)
            with self.assertRaisesRegex(recovery.GateError, "unsafe_private_tree"):
                recovery._validate_private_tree(root)
            link.unlink()
            payload.chmod(0o644)
            with self.assertRaisesRegex(recovery.GateError, "unsafe_private_tree"):
                recovery._validate_private_tree(root)

    def test_target_credentials_are_fresh_distinct_and_not_written_to_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            generated = recovery._target_environment(
                source_environment(),
                postgres_image="sha256:" + "6" * 64,
                service_image="sha256:" + "4" * 64,
                minio_image="sha256:" + "5" * 64,
                backup_root=Path(temporary),
                runtime_uid=65532,
                runtime_gid=65532,
            )
        password_names = [
            name
            for name in generated
            if name.startswith("HBCB_G8_") and name.endswith(("PASSWORD", "SECRET_KEY"))
        ]
        passwords = [generated[name] for name in password_names]
        self.assertEqual(len(passwords), len(set(passwords)))
        self.assertTrue(all(recovery.HEX_64.fullmatch(value) for value in passwords))
        self.assertNotIn(source_environment()["REDIS_PASSWORD"], passwords)

    def test_script_has_no_duplicate_literal_dictionary_keys(self) -> None:
        tree = ast.parse(SCRIPT.read_bytes(), filename=str(SCRIPT))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = [
                key.value
                for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            ]
            self.assertEqual(len(keys), len(set(keys)), f"duplicate dictionary key at line {node.lineno}")

    def test_restore_inventory_requires_new_version_ids_and_identical_hashes(self) -> None:
        source = inventory("source-version")
        target = inventory("target-version")
        build_id, count, total = recovery._compare_restored_inventories(source, target)
        self.assertEqual(build_id, "11111111-1111-4111-8111-111111111111")
        self.assertEqual((count, total), (1, 4))
        target_same = inventory("source-version")
        with self.assertRaisesRegex(recovery.GateError, "restored_inventory_mismatch"):
            recovery._compare_restored_inventories(source, target_same)
        target_bad_hash = inventory("target-version")
        target_bad_hash["artifacts"][0]["sha256"] = "b" * 64  # type: ignore[index]
        with self.assertRaisesRegex(recovery.GateError, "restored_inventory_mismatch"):
            recovery._compare_restored_inventories(source, target_bad_hash)

    def test_command_failures_do_not_surface_captured_secret(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["false"], returncode=1, stdout=b"", stderr=b"secret-canary"
        )
        with mock.patch.object(subprocess, "run", return_value=completed):
            with self.assertRaises(recovery.GateError) as raised:
                recovery.CommandRunner().run(("false",), label="probe")
        self.assertEqual(raised.exception.code, "probe_failed")
        self.assertNotIn("secret-canary", str(raised.exception))

    def test_target_initializers_must_exit_cleanly_before_restore(self) -> None:
        states = {
            "database-init-id": iter(
                [
                    {"Status": "running", "Running": True, "ExitCode": 0},
                    {"Status": "exited", "Running": False, "ExitCode": 0},
                ]
            ),
            "minio-init-id": iter(
                [{"Status": "exited", "Running": False, "ExitCode": 0}]
            ),
        }

        def compose(*arguments: str, **_kwargs: object) -> object:
            service = arguments[-1]
            return recovery.CommandResult((service + "-id\n").encode("ascii"))

        def inspect(command: object, **_kwargs: object) -> object:
            identifier = command[-1]  # type: ignore[index]
            return recovery.CommandResult(
                json.dumps(next(states[identifier])).encode("ascii")  # type: ignore[index]
            )

        context = SimpleNamespace(
            target_compose=compose,
            docker=("docker",),
            runner=SimpleNamespace(run=inspect),
        )
        with mock.patch.object(recovery.time, "sleep"):
            recovery._wait_target_initializers(context)
        self.assertEqual(list(states["database-init-id"]), [])
        self.assertEqual(list(states["minio-init-id"]), [])

        failing_context = SimpleNamespace(
            target_compose=compose,
            docker=("docker",),
            runner=SimpleNamespace(
                run=lambda *_args, **_kwargs: recovery.CommandResult(
                    b'{"Status":"exited","Running":false,"ExitCode":1}'
                )
            ),
        )
        with self.assertRaisesRegex(recovery.GateError, "target_initializer_failed"):
            recovery._wait_target_initializers(failing_context)

        script = SCRIPT.read_text(encoding="utf-8")
        self.assertLess(
            script.index("_wait_target_initializers(context)", script.index("target_start")),
            script.index("_database_restore(context, database_path)"),
        )

    def test_rendered_topology_validation_rejects_a_host_port(self) -> None:
        service_image = "sha256:" + "1" * 64
        minio_image = "sha256:" + "2" * 64
        services = {
            name: {"image": service_image, "networks": {"recovery": None}}
            for name in (
                "postgres", "redis", "minio", "minio-init", "database-init", "maintenance"
            )
        }
        services["minio"]["image"] = minio_image
        payload = {
            "services": services,
            "networks": {"recovery": {"internal": True}},
            "volumes": {"minio-data": {}, "postgres-data": {}, "redis-data": {}},
        }
        context = SimpleNamespace(
            service_image=service_image,
            minio_image=minio_image,
            target_compose=lambda *args, **kwargs: recovery.CommandResult(
                json.dumps(payload).encode("utf-8")
            ),
        )
        recovery._validate_target_topology(context)
        services["postgres"]["ports"] = [{"published": "5432", "target": 5432}]
        with self.assertRaisesRegex(recovery.GateError, "target_exposes_host_or_build"):
            recovery._validate_target_topology(context)


if __name__ == "__main__":
    unittest.main()
