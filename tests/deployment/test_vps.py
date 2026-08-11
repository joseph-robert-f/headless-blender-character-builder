from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
LOADER = importlib.machinery.SourceFileLoader("hbcb_vps_script", str(ROOT / "scripts" / "vps"))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
VPS = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(VPS)


def valid_lock() -> dict[str, str]:
    return {
        "HBCB_RELEASE_VERSION": "0.1.0",
        "HBCB_API_IMAGE": "ghcr.io/example/api@sha256:" + "1" * 64,
        "HBCB_WORKER_IMAGE": "ghcr.io/example/worker@sha256:" + "2" * 64,
        "HBCB_CADDY_IMAGE": "caddy@sha256:" + "3" * 64,
        "HBCB_BUILDER_IMAGE_REFERENCE": "ghcr.io/example/builder@sha256:" + "4" * 64,
        "HBCB_BUILDER_IMAGE_ID": "sha256:" + "5" * 64,
        "HBCB_BUILDER_SOURCE_REVISION": VPS.FROZEN_BUILDER_REVISION,
        "HBCB_MIGRATION_CATALOG_SHA256": VPS.migration_catalog_sha256(),
    }


def valid_vps_environment(root: Path) -> dict[str, str]:
    return {
        "HBCB_DEPLOYMENT_NAMESPACE": "production",
        "POSTGRES_DB": "hbcb",
        "HBCB_API_DOMAIN": "builder.example.com",
        "HBCB_ACME_EMAIL": "operator@example.com",
        "HBCB_VPS_SECRETS_DIR": str(root / "secrets"),
        "HBCB_VPS_STATE_DIR": str(root / "state"),
        "HBCB_BACKUP_ROOT": str(root / "backups"),
        "HBCB_STORAGE_NETWORK": "hbcb-storage-private",
        "HBCB_STORAGE_INTERNAL_ENDPOINT": "s3.private.example:443",
        "HBCB_STORAGE_PUBLIC_ENDPOINT": "artifacts.example.com:443",
        "HBCB_STORAGE_INTERNAL_SECURE": "true",
        "HBCB_STORAGE_PUBLIC_SECURE": "true",
        "HBCB_STORAGE_REGION": "us-east-1",
        "HBCB_STORAGE_BUCKET": "hbcb-production-artifacts",
        "HBCB_SIGNED_URL_TTL_SECONDS": "300",
        "HBCB_RETENTION_SUCCEEDED_DAYS": "30",
        "HBCB_RETENTION_OTHER_DAYS": "7",
        "HBCB_ORPHAN_GRACE_DAYS": "7",
    }


def secret_files() -> dict[str, dict[str, str]]:
    admin = "a" * 64
    redis = "b" * 64
    api = "c" * 64
    worker = "d" * 64
    maintenance = "e" * 64
    migrator = "f" * 64
    return {
        "postgres.env": {
            "POSTGRES_DB": "hbcb",
            "POSTGRES_USER": "hbcb_admin",
            "POSTGRES_PASSWORD": admin,
        },
        "redis.env": {"REDIS_PASSWORD": redis},
        "database-init.env": {
            "HBCB_DATABASE_ADMIN_URL": f"postgresql://hbcb_admin:{admin}@postgres:5432/hbcb",
            "HBCB_DATABASE_MIGRATOR_URL": f"postgresql://hbcb_migrator:{migrator}@postgres:5432/hbcb",
            "HBCB_DATABASE_API_USER": "hbcb_api",
            "HBCB_DATABASE_API_PASSWORD": api,
            "HBCB_DATABASE_WORKER_USER": "hbcb_worker",
            "HBCB_DATABASE_WORKER_PASSWORD": worker,
            "HBCB_DATABASE_MAINTENANCE_USER": "hbcb_maintenance",
            "HBCB_DATABASE_MAINTENANCE_PASSWORD": maintenance,
            "HBCB_DATABASE_MIGRATOR_USER": "hbcb_migrator",
            "HBCB_DATABASE_MIGRATOR_PASSWORD": migrator,
        },
        "api.env": {
            "HBCB_API_TOKEN": "1" * 64,
            "HBCB_IDEMPOTENCY_SECRET": "2" * 64,
            "HBCB_DATABASE_URL": f"postgresql://hbcb_api:{api}@postgres:5432/hbcb",
            "HBCB_REDIS_URL": f"redis://:{redis}@redis:6379/0",
            "HBCB_STORAGE_ACCESS_KEY": "hbcb_api",
            "HBCB_STORAGE_SECRET_KEY": "3" * 64,
        },
        "worker.env": {
            "HBCB_DATABASE_URL": f"postgresql://hbcb_worker:{worker}@postgres:5432/hbcb",
            "HBCB_REDIS_URL": f"redis://:{redis}@redis:6379/0",
            "HBCB_STORAGE_ACCESS_KEY": "hbcb_worker",
            "HBCB_STORAGE_SECRET_KEY": "4" * 64,
        },
        "maintenance.env": {
            "HBCB_DATABASE_URL": f"postgresql://hbcb_maintenance:{maintenance}@postgres:5432/hbcb",
            "HBCB_REDIS_URL": f"redis://:{redis}@redis:6379/0",
            "HBCB_STORAGE_ACCESS_KEY": "hbcb_maintenance",
            "HBCB_STORAGE_SECRET_KEY": "5" * 64,
        },
    }


def write_env(path: Path, values: dict[str, str], mode: int = 0o600) -> None:
    path.write_text(
        "".join(f"{name}={value}\n" for name, value in values.items()),
        encoding="utf-8",
    )
    path.chmod(mode)


@contextlib.contextmanager
def portable_root_ownership():
    """Model the production UID contract without requiring root in unit tests."""

    current_uid = os.getuid()
    with (
        mock.patch.object(VPS, "ROOT_OPERATOR_UID", current_uid),
        mock.patch.object(VPS, "MAINTENANCE_CONTAINER_UID", current_uid),
        mock.patch.object(VPS, "_validate_root_owned_ancestors"),
    ):
        yield


def make_valid_bundle(root: Path) -> tuple[Path, dict[str, str], Path]:
    backup_root = root / "backups"
    backup_root.mkdir(mode=0o700)
    bundle = backup_root / "20260803T000000Z-0.1.0-production-test"
    bundle.mkdir(mode=0o700)
    objects = bundle / VPS.BACKUP_OBJECTS
    objects.mkdir(mode=0o700)
    (objects / "objects").mkdir(mode=0o700)
    inventory = b'{"artifacts":[],"created_at":"2026-08-03T00:00:00+00:00","namespace":"production","version":"backup-inventory/v1"}\n'
    (objects / "inventory.json").write_bytes(inventory)
    (objects / "inventory.json").chmod(0o600)
    database = bundle / VPS.BACKUP_DATABASE
    database.write_bytes(b"PGDMP-test")
    database.chmod(0o600)

    vps = valid_vps_environment(root)
    config_path = bundle / VPS.BACKUP_CONFIG
    write_env(config_path, vps)
    lock = valid_lock()
    lock_path = bundle / VPS.BACKUP_LOCK
    write_env(lock_path, lock)
    database_sha256, database_bytes = VPS._sha256_file(database)
    tree_sha256, tree_files, tree_bytes = VPS._object_tree_sha256(objects)
    manifest = {
        "format": VPS.BACKUP_FORMAT,
        "created_at": "2026-08-03T00:00:00+00:00",
        "release_version": lock["HBCB_RELEASE_VERSION"],
        "migration_catalog_sha256": lock["HBCB_MIGRATION_CATALOG_SHA256"],
        "namespace": vps["HBCB_DEPLOYMENT_NAMESPACE"],
        "bucket": vps["HBCB_STORAGE_BUCKET"],
        "database_sha256": database_sha256,
        "database_bytes": database_bytes,
        "objects_tree_sha256": tree_sha256,
        "object_inventory_sha256": hashlib.sha256(inventory).hexdigest(),
        "artifact_count": 0,
        "artifact_bytes": 0,
        "object_tree_files": tree_files,
        "object_tree_bytes": tree_bytes,
        "release_lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "vps_env_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
    }
    manifest_path = bundle / VPS.BACKUP_MANIFEST
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
    )
    manifest_path.chmod(0o600)
    return bundle, vps, lock_path


class VpsOperatorTests(unittest.TestCase):
    def test_release_lock_requires_exact_non_placeholder_digests_and_catalog(self) -> None:
        values = valid_lock()
        VPS.validate_release_lock(values)
        for name, value in (
            ("HBCB_API_IMAGE", "ghcr.io/example/api:latest"),
            ("HBCB_WORKER_IMAGE", "ghcr.io/example/worker@sha256:" + "0" * 64),
            ("HBCB_BUILDER_SOURCE_REVISION", "9" * 64),
            ("HBCB_MIGRATION_CATALOG_SHA256", "8" * 64),
        ):
            with self.subTest(name=name):
                invalid = dict(values)
                invalid[name] = value
                with self.assertRaises(VPS.OperatorError):
                    VPS.validate_release_lock(invalid)

    def test_vps_environment_requires_tls_distinct_storage_and_bounded_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            values = valid_vps_environment(Path(temporary))
            VPS.validate_vps_environment(values)
            for name, value in (
                ("HBCB_STORAGE_INTERNAL_SECURE", "false"),
                ("HBCB_STORAGE_PUBLIC_ENDPOINT", values["HBCB_STORAGE_INTERNAL_ENDPOINT"]),
                ("HBCB_STORAGE_PUBLIC_ENDPOINT", "artifacts.example.com:443?redirect=bad"),
                ("HBCB_STORAGE_INTERNAL_ENDPOINT", "s3.private.example:443#fragment"),
                ("HBCB_RETENTION_OTHER_DAYS", "0"),
                ("HBCB_API_DOMAIN", "https://builder.example.com"),
            ):
                with self.subTest(name=name):
                    invalid = dict(values)
                    invalid[name] = value
                    with self.assertRaises(VPS.OperatorError):
                        VPS.validate_vps_environment(invalid)

    def test_secret_files_are_exact_scoped_mode_0600_and_cross_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "secrets"
            directory.mkdir(mode=0o700)
            values = secret_files()
            for filename, entries in values.items():
                path = directory / filename
                path.write_text(
                    "".join(f"{name}={value}\n" for name, value in entries.items()),
                    encoding="utf-8",
                )
                path.chmod(0o600)
            parsed = VPS.validate_secret_files(directory)
            self.assertEqual(set(parsed), set(VPS.SECRET_FILE_KEYS))

            for filename, name, value in (
                ("postgres.env", "POSTGRES_USER", "Unsafe-Role"),
                ("redis.env", "REDIS_PASSWORD", "change-me-" + "x" * 40),
                ("worker.env", "HBCB_STORAGE_SECRET_KEY", "x" * 129),
                ("maintenance.env", "HBCB_STORAGE_ACCESS_KEY", "placeholder_key"),
            ):
                with self.subTest(filename=filename, name=name):
                    invalid = dict(values[filename])
                    invalid[name] = value
                    write_env(directory / filename, invalid)
                    with self.assertRaises(VPS.OperatorError):
                        VPS.validate_secret_files(directory)
                    write_env(directory / filename, values[filename])

            with self.assertRaisesRegex(VPS.OperatorError, "unsafe owner"):
                VPS.validate_secret_files(directory, owner_uid=os.getuid() + 1)

            worker = directory / "worker.env"
            worker.chmod(0o644)
            with self.assertRaises(VPS.OperatorError):
                VPS.validate_secret_files(directory)
            worker.chmod(0o600)

            worker.unlink()
            worker.symlink_to(directory / "api.env")
            with self.assertRaises(VPS.OperatorError):
                VPS.validate_secret_files(directory)

    def test_env_parser_rejects_duplicates_shell_syntax_and_nonregular_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "values.env"
            path.write_text("ONE=value\nONE=again\n", encoding="utf-8")
            with self.assertRaises(VPS.OperatorError):
                VPS._parse_env(path)
            path.write_text("ONE=$HOME\n", encoding="utf-8")
            with self.assertRaises(VPS.OperatorError):
                VPS._parse_env(path)
            target = root / "target.env"
            target.write_text("ONE=value\n", encoding="utf-8")
            path.unlink()
            path.symlink_to(target)
            with self.assertRaises(VPS.OperatorError):
                VPS._parse_env(path)

    def test_root_trust_rejects_wrong_owners_and_writable_nonsecret_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "vps.env"
            write_env(config, {"ONE": "value"}, mode=0o644)
            directory = root / "protected"
            directory.mkdir(mode=0o700)
            with (
                mock.patch.object(VPS, "ROOT_OPERATOR_UID", os.getuid()),
                mock.patch.object(VPS, "_validate_root_owned_ancestors"),
            ):
                VPS._root_trusted_file(config, "VPS configuration")
                VPS._root_trusted_directory(str(directory), "backup root", mode=0o700)

                config.chmod(0o664)
                with self.assertRaisesRegex(VPS.OperatorError, "group/world writable"):
                    VPS._root_trusted_file(config, "VPS configuration")
                config.chmod(0o644)

                with mock.patch.object(VPS, "ROOT_OPERATOR_UID", os.getuid() + 1):
                    with self.assertRaisesRegex(VPS.OperatorError, "unsafe owner"):
                        VPS._root_trusted_file(config, "release lock")
                    with self.assertRaisesRegex(VPS.OperatorError, "unsafe owner"):
                        VPS._root_trusted_directory(
                            str(directory),
                            "backup root",
                            mode=0o700,
                        )

    def test_root_invocation_enables_preflight_trust_validation(self) -> None:
        config = Path("/etc/hbcb/vps.env")
        lock = Path("/etc/hbcb/release.lock.env")
        with (
            mock.patch.object(VPS.os, "geteuid", return_value=VPS.ROOT_OPERATOR_UID),
            mock.patch.object(
                VPS,
                "preflight",
                return_value=({}, {}, []),
            ) as preflight,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = VPS.main(
                [
                    "preflight",
                    "--config",
                    str(config),
                    "--release-lock",
                    str(lock),
                    "--offline",
                ]
            )
        self.assertEqual(result, 0)
        preflight.assert_called_once_with(
            config,
            lock,
            compose_bin=None,
            offline=True,
            root_trust=True,
        )

    def test_root_compose_executable_and_environment_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compose = root / "docker-compose"
            compose.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
            compose.chmod(0o755)
            with (
                mock.patch.object(VPS, "ROOT_OPERATOR_UID", os.getuid()),
                mock.patch.object(VPS, "_validate_root_owned_ancestors"),
            ):
                self.assertEqual(
                    VPS._compose_command(str(compose), root_trust=True),
                    [str(compose)],
                )
                compose.chmod(0o775)
                with self.assertRaisesRegex(VPS.OperatorError, "group/world writable"):
                    VPS._compose_command(str(compose), root_trust=True)
                compose.chmod(0o755)
                with mock.patch.object(VPS, "ROOT_OPERATOR_UID", os.getuid() + 1):
                    with self.assertRaisesRegex(VPS.OperatorError, "unsafe owner"):
                        VPS._compose_command(str(compose), root_trust=True)

                docker = root / "docker"
                docker.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
                docker.chmod(0o755)
                with mock.patch.object(VPS, "ROOT_DOCKER_CANDIDATES", (docker,)):
                    self.assertEqual(
                        VPS._compose_command(None, root_trust=True),
                        [str(docker), "compose"],
                    )

            with mock.patch.dict(
                VPS.os.environ,
                {"DOCKER_HOST": "tcp://attacker.invalid:2375", "PATH": "/unsafe"},
                clear=True,
            ):
                with self.assertRaisesRegex(VPS.OperatorError, "DOCKER_HOST"):
                    VPS._operator_environment({}, {}, root_trust=True)
            with mock.patch.dict(VPS.os.environ, {"PATH": "/unsafe"}, clear=True):
                environment = VPS._operator_environment({}, {}, root_trust=True)
            self.assertEqual(environment["PATH"], VPS.ROOT_OPERATOR_PATH)
            self.assertEqual(environment["HOME"], "/root")
            self.assertEqual(environment["XDG_CONFIG_HOME"], "/root/.config")

    def test_compose_version_preflight_requires_2_24_4_or_newer(self) -> None:
        environment = {"PATH": "/usr/bin:/bin"}
        for rendered in (
            "2.24.4",
            "v2.24.4",
            "2.24.4-desktop.1",
            "2.25.0",
            "3.0.0",
        ):
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=(rendered + "\n").encode("ascii"),
                stderr=b"",
            )
            with self.subTest(rendered=rendered), mock.patch.object(
                VPS.subprocess, "run", return_value=completed
            ) as run:
                VPS._validate_compose_version(["/usr/bin/docker", "compose"], environment)
                self.assertEqual(
                    run.call_args.args[0],
                    ["/usr/bin/docker", "compose", "version", "--short"],
                )
                self.assertEqual(run.call_args.kwargs["timeout"], 30)

        for rendered in ("1.29.2", "2.24.3", "2.24", "Docker Compose 2.24.4", ""):
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=(rendered + "\n").encode("ascii"),
                stderr=b"",
            )
            with self.subTest(rendered=rendered), mock.patch.object(
                VPS.subprocess, "run", return_value=completed
            ):
                with self.assertRaisesRegex(VPS.OperatorError, "2.24.4 or newer"):
                    VPS._validate_compose_version(["compose"], environment)

        failed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b"private"
        )
        with mock.patch.object(VPS.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(VPS.OperatorError, "2.24.4 or newer") as raised:
                VPS._validate_compose_version(["compose"], environment)
        self.assertNotIn("private", str(raised.exception))

    def test_operator_lock_is_private_persistent_and_excludes_another_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            state.mkdir(mode=0o700)
            probe = (
                "import fcntl,os,sys; "
                "fd=os.open(sys.argv[1],os.O_RDWR); "
                "blocked=False; "
                "\ntry:\n fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)"
                "\nexcept BlockingIOError:\n blocked=True"
                "\nos.close(fd); raise SystemExit(0 if blocked else 23)"
            )
            with portable_root_ownership():
                with VPS._exclusive_operator_lock(state):
                    lock_path = state / "operator.lock"
                    metadata = lock_path.lstat()
                    self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o600)
                    self.assertEqual(metadata.st_uid, os.getuid())
                    result = subprocess.run(
                        [sys.executable, "-c", probe, str(lock_path)],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
                self.assertTrue(lock_path.is_file())

    def test_backup_bundle_rejects_wrong_root_or_maintenance_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, vps, archived_lock = make_valid_bundle(root)
            with portable_root_ownership():
                VPS._validate_backup_bundle(
                    bundle,
                    root / "backups",
                    vps,
                    archived_lock,
                    require_current_lock=True,
                )
                with mock.patch.object(
                    VPS,
                    "MAINTENANCE_CONTAINER_UID",
                    os.getuid() + 1,
                ):
                    with self.assertRaisesRegex(VPS.OperatorError, "unsafe owner"):
                        VPS._validate_backup_bundle(
                            bundle,
                            root / "backups",
                            vps,
                            archived_lock,
                            require_current_lock=True,
                        )
                with mock.patch.object(VPS, "ROOT_OPERATOR_UID", os.getuid() + 1):
                    with self.assertRaisesRegex(VPS.OperatorError, "unsafe owner"):
                        VPS._validate_backup_bundle(
                            bundle,
                            root / "backups",
                            vps,
                            archived_lock,
                            require_current_lock=True,
                        )

    def test_database_namespace_invariant_rejects_a_second_namespace(self) -> None:
        with mock.patch.object(
            VPS,
            "_postgres_scalar",
            return_value="production,staging",
        ) as scalar:
            with self.assertRaisesRegex(VPS.OperatorError, "outside the deployment namespace"):
                VPS._assert_single_namespace(["compose"], os.environ, "production")
        query = scalar.call_args.args[2]
        for table in (
            "hbcb.builds",
            "hbcb.idempotency_keys",
            "hbcb.artifact_deletion_queue",
            "hbcb.artifact_restore_remaps",
        ):
            self.assertIn(table, query)

    def test_restart_never_starts_application_or_ingress_for_foreign_namespace(self) -> None:
        with (
            mock.patch.object(VPS, "_run_safe") as run_safe,
            mock.patch.object(
                VPS,
                "_assert_single_namespace",
                side_effect=VPS.OperatorError("foreign namespace"),
            ),
        ):
            with self.assertRaisesRegex(VPS.OperatorError, "foreign namespace"):
                VPS._restart_live_application(
                    ["compose"],
                    os.environ,
                    "production",
                )
        self.assertEqual(run_safe.call_count, 1)
        substrate_command = run_safe.call_args.args[0]
        self.assertIn("database-init", substrate_command)
        self.assertNotIn("api", substrate_command)
        self.assertNotIn("worker", substrate_command)
        self.assertNotIn("caddy", substrate_command)

    def test_upgrade_handoff_is_atomic_bound_read_only_and_consumable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            state.mkdir(mode=0o700)
            bundle, vps, source_lock = make_valid_bundle(root)
            with (
                portable_root_ownership(),
                mock.patch.object(VPS, "_set_database_read_only") as set_read_only,
                mock.patch.object(
                    VPS,
                    "_database_handoff_identity",
                    return_value=("123456789", 16384, True),
                ),
                mock.patch.object(VPS, "_assert_single_namespace") as namespace_check,
                mock.patch.object(VPS, "_maintenance_probe", return_value=(True, None)),
            ):
                preparing = VPS._prepare_upgrade_handoff(state, vps, source_lock)
                self.assertEqual(preparing["status"], "preparing")
                ready = VPS._finalize_upgrade_handoff(
                    state,
                    preparing,
                    bundle,
                    vps,
                    source_lock,
                    ["compose"],
                    os.environ,
                )
                self.assertEqual(ready["status"], "ready")
                set_read_only.assert_called_once_with(
                    ["compose"],
                    os.environ,
                    enabled=True,
                )
                VPS._validate_ready_upgrade_handoff(
                    state,
                    ready,
                    bundle,
                    vps,
                    source_lock,
                    ["compose"],
                    os.environ,
                )
                namespace_check.assert_called_once()
                upgrading = VPS._begin_upgrade_handoff(state, ready, source_lock)
                self.assertEqual(upgrading["status"], "upgrading")
                self.assertEqual(
                    upgrading["target_release_lock_sha256"],
                    hashlib.sha256(source_lock.read_bytes()).hexdigest(),
                )
                VPS._remove_upgrade_handoff(state, upgrading)
                self.assertIsNone(VPS._load_upgrade_handoff(state))

    def test_failed_upgrade_persists_target_and_forbids_source_abort(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            state.mkdir(mode=0o700)
            bundle, vps, source_lock = make_valid_bundle(root)
            config_path = root / "current-vps.env"
            write_env(config_path, vps)
            target_values = valid_lock()
            target_values["HBCB_RELEASE_VERSION"] = "0.2.0"
            target_values["HBCB_API_IMAGE"] = (
                "ghcr.io/example/api@sha256:" + "6" * 64
            )
            target_lock = root / "target-release.lock.env"
            write_env(target_lock, target_values)
            with (
                portable_root_ownership(),
                mock.patch.object(VPS, "_set_database_read_only"),
                mock.patch.object(
                    VPS,
                    "_database_handoff_identity",
                    return_value=("123456789", 16384, True),
                ),
            ):
                preparing = VPS._prepare_upgrade_handoff(state, vps, source_lock)
                ready = VPS._finalize_upgrade_handoff(
                    state,
                    preparing,
                    bundle,
                    vps,
                    source_lock,
                    ["compose"],
                    os.environ,
                )
                self.assertEqual(ready["status"], "ready")

            upgrade_args = VPS._parse_args(
                ["upgrade", "--backup", str(bundle), "--confirm"]
            )
            with (
                portable_root_ownership(),
                mock.patch.object(VPS, "_stop_writers"),
                mock.patch.object(VPS, "_validate_ready_upgrade_handoff"),
                mock.patch.object(
                    VPS,
                    "_upgrade_from_verified_backup",
                    side_effect=VPS.OperatorError("startup failed after migration"),
                ),
                mock.patch.object(VPS, "_set_database_read_only"),
                mock.patch.object(
                    VPS,
                    "_database_handoff_identity",
                    return_value=("123456789", 16384, True),
                ),
                mock.patch.object(VPS, "_assert_single_namespace"),
            ):
                with self.assertRaisesRegex(VPS.OperatorError, "after migration"):
                    VPS._execute_operator_action(
                        upgrade_args,
                        vps,
                        os.environ,
                        ["compose"],
                        config_path,
                        target_lock,
                    )

                upgrading = VPS._load_upgrade_handoff(state)
                assert upgrading is not None
                self.assertEqual(upgrading["status"], "upgrading")
                self.assertEqual(
                    upgrading["target_release_lock_sha256"],
                    hashlib.sha256(target_lock.read_bytes()).hexdigest(),
                )

                abort_args = VPS._parse_args(["handoff-abort", "--confirm"])
                with self.assertRaisesRegex(
                    VPS.OperatorError,
                    "forbidden after upgrade started",
                ):
                    VPS._execute_operator_action(
                        abort_args,
                        vps,
                        os.environ,
                        ["compose"],
                        config_path,
                        source_lock,
                    )

                VPS._validate_upgrading_upgrade_handoff(
                    upgrading,
                    bundle,
                    vps,
                    target_lock,
                    ["compose"],
                    os.environ,
                )

    def test_active_handoff_blocks_unrelated_operator_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            state.mkdir(mode=0o700)
            _bundle, vps, source_lock = make_valid_bundle(root)
            config_path = root / "current-vps.env"
            write_env(config_path, vps)
            with portable_root_ownership():
                VPS._prepare_upgrade_handoff(state, vps, source_lock)
                args = VPS._parse_args(["up"])
                with self.assertRaisesRegex(VPS.OperatorError, "upgrade handoff is active"):
                    VPS._execute_operator_action(
                        args,
                        vps,
                        os.environ,
                        ["compose"],
                        config_path,
                        source_lock,
                    )

    def test_backup_bundle_validation_is_exact_and_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, vps, archived_lock = make_valid_bundle(root)
            with portable_root_ownership():
                manifest = VPS._validate_backup_bundle(
                    bundle,
                    root / "backups",
                    vps,
                    archived_lock,
                    require_current_lock=True,
                )
                self.assertEqual(manifest["format"], VPS.BACKUP_FORMAT)

                database = bundle / VPS.BACKUP_DATABASE
                database.write_bytes(database.read_bytes() + b"tamper")
                database.chmod(0o600)
                with self.assertRaises(VPS.OperatorError):
                    VPS._validate_backup_bundle(
                        bundle,
                        root / "backups",
                        vps,
                        archived_lock,
                        require_current_lock=True,
                    )

    def test_backup_bundle_rejects_wrong_lock_extra_entries_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, vps, archived_lock = make_valid_bundle(root)
            other_lock = root / "other-lock.env"
            changed = valid_lock()
            changed["HBCB_RELEASE_VERSION"] = "0.1.1"
            write_env(other_lock, changed)
            with portable_root_ownership():
                with self.assertRaisesRegex(VPS.OperatorError, "exact release lock"):
                    VPS._validate_backup_bundle(
                        bundle,
                        root / "backups",
                        vps,
                        other_lock,
                        require_current_lock=True,
                    )

                extra = bundle / "unexpected"
                extra.write_text("x", encoding="ascii")
                extra.chmod(0o600)
                with self.assertRaises(VPS.OperatorError):
                    VPS._validate_backup_bundle(
                        bundle,
                        root / "backups",
                        vps,
                        archived_lock,
                        require_current_lock=True,
                    )
                extra.unlink()

                inventory = bundle / VPS.BACKUP_OBJECTS / "inventory.json"
                target = root / "outside"
                target.write_text("outside", encoding="ascii")
                inventory.unlink()
                inventory.symlink_to(target)
                with self.assertRaises(VPS.OperatorError):
                    VPS._validate_backup_bundle(
                        bundle,
                        root / "backups",
                        vps,
                        archived_lock,
                        require_current_lock=True,
                    )

    def test_maintenance_command_mount_is_explicit_and_read_only(self) -> None:
        command = VPS._maintenance_command(
            ["docker", "compose"],
            ["restore-objects", "--input", "/backup"],
            host_backup=Path("/var/backups/hbcb/example/objects"),
            read_only=True,
        )
        self.assertEqual(command.count("--volume"), 1)
        self.assertIn("/var/backups/hbcb/example/objects:/backup:ro", command)
        self.assertEqual(command[-3:], ["restore-objects", "--input", "/backup"])

    def test_backup_failure_restarts_application_and_cleans_private_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backup_root = root / "backups"
            backup_root.mkdir(mode=0o700)
            vps = valid_vps_environment(root)
            lock = valid_lock()
            config_path = root / "vps.env"
            lock_path = root / "lock.env"
            write_env(config_path, vps)
            write_env(lock_path, lock)
            with (
                portable_root_ownership(),
                mock.patch.object(VPS, "_require_root_operator"),
                mock.patch.object(VPS, "_stop_writers"),
                mock.patch.object(
                    VPS,
                    "_wait_for_quiescence",
                    side_effect=VPS.OperatorError("not quiescent"),
                ),
                mock.patch.object(VPS, "_restart_live_application") as restart,
            ):
                with self.assertRaisesRegex(VPS.OperatorError, "not quiescent"):
                    VPS._backup_bundle(
                        vps,
                        lock,
                        config_path,
                        lock_path,
                        ["compose"],
                        os.environ,
                        drain_timeout_seconds=30,
                    )
            restart.assert_called_once()
            self.assertEqual(list(backup_root.iterdir()), [])

    def test_backup_partial_stop_failure_still_converges_live_application(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backup_root = root / "backups"
            backup_root.mkdir(mode=0o700)
            vps = valid_vps_environment(root)
            lock = valid_lock()
            config_path = root / "vps.env"
            lock_path = root / "lock.env"
            write_env(config_path, vps)
            write_env(lock_path, lock)
            with (
                portable_root_ownership(),
                mock.patch.object(VPS, "_require_root_operator"),
                mock.patch.object(
                    VPS,
                    "_stop_writers",
                    side_effect=VPS.OperatorError("partial stop"),
                ),
                mock.patch.object(VPS, "_restart_live_application") as restart,
            ):
                with self.assertRaisesRegex(VPS.OperatorError, "partial stop"):
                    VPS._backup_bundle(
                        vps,
                        lock,
                        config_path,
                        lock_path,
                        ["compose"],
                        os.environ,
                        drain_timeout_seconds=30,
                    )
            restart.assert_called_once()
            self.assertEqual(list(backup_root.iterdir()), [])

    def test_successful_backup_is_atomic_self_verifying_and_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backup_root = root / "backups"
            backup_root.mkdir(mode=0o700)
            vps = valid_vps_environment(root)
            lock = valid_lock()
            config_path = root / "vps.env"
            lock_path = root / "lock.env"
            write_env(config_path, vps)
            write_env(lock_path, lock)

            def database_dump(_prefix, _environment, destination):
                destination.write_bytes(b"PGDMP-test")
                destination.chmod(0o600)
                return VPS._sha256_file(destination)

            def object_export(
                _prefix,
                _arguments,
                *,
                label,
                environment,
                expected_keys,
                host_backup,
                read_only=False,
            ):
                del label, environment, expected_keys, read_only
                exported = host_backup / VPS.BACKUP_OBJECTS
                exported.mkdir(mode=0o700)
                (exported / "objects").mkdir(mode=0o700)
                inventory = exported / "inventory.json"
                inventory.write_bytes(b"{}\n")
                inventory.chmod(0o600)
                return {
                    "artifact_bytes": 0,
                    "artifacts": 0,
                    "inventory_sha256": hashlib.sha256(b"{}\n").hexdigest(),
                }

            with (
                portable_root_ownership(),
                mock.patch.object(VPS, "_require_root_operator"),
                mock.patch.object(VPS, "_stop_writers"),
                mock.patch.object(VPS, "_wait_for_quiescence"),
                mock.patch.object(VPS, "_run_safe"),
                mock.patch.object(VPS, "_maintenance_probe", return_value=(True, None)),
                mock.patch.object(VPS, "_assert_single_namespace") as namespace_check,
                mock.patch.object(VPS, "_database_dump", side_effect=database_dump),
                mock.patch.object(VPS, "_maintenance_result", side_effect=object_export),
                mock.patch.object(VPS.os, "chown"),
                mock.patch.object(VPS, "_restart_live_application") as restart,
            ):
                bundle = VPS._backup_bundle(
                    vps,
                    lock,
                    config_path,
                    lock_path,
                    ["compose"],
                    os.environ,
                    drain_timeout_seconds=30,
                )
            restart.assert_called_once()
            self.assertEqual(namespace_check.call_count, 2)
            self.assertEqual(bundle.parent, backup_root)
            self.assertFalse(any(path.name.startswith(".partial-") for path in backup_root.iterdir()))
            with portable_root_ownership():
                manifest = VPS._validate_backup_bundle(
                    bundle,
                    backup_root,
                    vps,
                    lock_path,
                    require_current_lock=True,
                )
            self.assertEqual(manifest["artifact_count"], 0)
            self.assertEqual(manifest["database_bytes"], len(b"PGDMP-test"))

    def test_restore_requires_validated_empty_target_and_leaves_ingress_down(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, vps, archived_lock = make_valid_bundle(root)
            dry = {
                "artifact_bytes": 0,
                "artifacts": 0,
                "dry_run": True,
                "remapped": 0,
                "uploaded": 0,
            }
            applied = dict(dry, dry_run=False)
            rebuilt = {"derived_queued_builds": 0, "dry_run": False, "enqueued": 0}
            with (
                portable_root_ownership(),
                mock.patch.object(VPS, "_require_root_operator"),
                mock.patch.object(VPS, "_stop_writers") as stop,
                mock.patch.object(VPS, "_run_safe"),
                mock.patch.object(VPS, "_assert_empty_database") as database_empty,
                mock.patch.object(VPS, "_assert_empty_redis") as redis_empty,
                mock.patch.object(VPS, "_restore_database") as restore_database,
                mock.patch.object(
                    VPS,
                    "_maintenance_result",
                    side_effect=(dry, applied, rebuilt),
                ) as maintenance,
                mock.patch.object(VPS, "_start_private_application") as start_private,
                mock.patch.object(VPS, "_restart_live_application") as start_public,
            ):
                VPS._restore_bundle(
                    vps,
                    archived_lock,
                    ["compose"],
                    os.environ,
                    bundle,
                )
            stop.assert_called_once_with(["compose"], os.environ, include_worker=True)
            database_empty.assert_called_once()
            redis_empty.assert_called_once()
            restore_database.assert_called_once()
            start_private.assert_called_once()
            start_public.assert_not_called()
            object_backup = bundle / VPS.BACKUP_OBJECTS
            self.assertEqual(stat.S_IMODE(bundle.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(object_backup.stat().st_mode), 0o700)
            self.assertEqual(
                maintenance.call_args_list[0].args[1],
                ["restore-objects", "--input", "/backup"],
            )
            self.assertEqual(
                maintenance.call_args_list[0].kwargs["host_backup"],
                object_backup,
            )
            self.assertEqual(
                maintenance.call_args_list[1].args[1],
                ["restore-objects", "--input", "/backup", "--apply"],
            )
            self.assertEqual(
                maintenance.call_args_list[1].kwargs["host_backup"],
                object_backup,
            )

    def test_action_contract_requires_confirmations_and_backup_paths(self) -> None:
        parsed = VPS._parse_args(["restore", "--backup", "/var/backups/hbcb/example"])
        self.assertFalse(parsed.confirm)
        self.assertFalse(parsed.confirm_empty_target)
        self.assertEqual(parsed.action, "restore")
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                VPS._parse_args(["image-only-rollback"])

    def test_script_is_executable_and_not_group_world_writable(self) -> None:
        mode = stat.S_IMODE((ROOT / "scripts" / "vps").stat().st_mode)
        # Git records executable versus non-executable, not an exact 0555 mode.
        # The deployment instructions install the root-owned copy as 0555.
        self.assertEqual(mode & 0o111, 0o111)
        self.assertEqual(mode & 0o022, 0)

    def test_live_storage_network_must_be_docker_internal(self) -> None:
        with mock.patch.object(
            VPS.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="true\n", stderr=""),
        ):
            VPS._validate_private_storage_network("hbcb-storage-private", os.environ)
        with mock.patch.object(
            VPS.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="false\n", stderr=""),
        ):
            with self.assertRaises(VPS.OperatorError):
                VPS._validate_private_storage_network("hbcb-storage-private", os.environ)


if __name__ == "__main__":
    unittest.main()
