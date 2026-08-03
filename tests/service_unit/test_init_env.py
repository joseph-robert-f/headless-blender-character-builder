from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from hbcb_service.config import (
    DatabaseInitializationConfig,
    MigratorConfig,
    ServiceConfig,
    WorkerConfig,
)

try:
    from .support import ROOT
except ImportError:  # Direct ``unittest -s tests/service_unit`` discovery.
    from support import ROOT


SCRIPT = ROOT / "scripts" / "init-env"


def parse_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator or not key or key in values:
            raise AssertionError("invalid generated environment document")
        values[key] = value
    return values


def role_environments(values: dict[str, str]) -> tuple[dict[str, str], ...]:
    database_prefix = "postgresql://"
    database_suffix = f"@postgres:5432/{values['POSTGRES_DB']}"
    redis_url = f"redis://:{values['REDIS_PASSWORD']}@redis:6379/0"
    shared_storage = {
        "HBCB_DEPLOYMENT_NAMESPACE": values["HBCB_DEPLOYMENT_NAMESPACE"],
        "HBCB_STORAGE_INTERNAL_ENDPOINT": values["HBCB_STORAGE_INTERNAL_ENDPOINT"],
        "HBCB_STORAGE_BUCKET": values["HBCB_STORAGE_BUCKET"],
        "HBCB_STORAGE_INTERNAL_SECURE": values["HBCB_STORAGE_INTERNAL_SECURE"],
        "HBCB_STORAGE_REGION": values["HBCB_STORAGE_REGION"],
    }
    api = {
        **shared_storage,
        "HBCB_API_TOKEN": values["HBCB_API_TOKEN"],
        "HBCB_IDEMPOTENCY_SECRET": values["HBCB_IDEMPOTENCY_SECRET"],
        "HBCB_DATABASE_URL": (
            database_prefix
            + values["HBCB_DATABASE_API_USER"]
            + ":"
            + values["HBCB_DATABASE_API_PASSWORD"]
            + database_suffix
        ),
        "HBCB_REDIS_URL": redis_url,
        "HBCB_STORAGE_PUBLIC_ENDPOINT": values["HBCB_STORAGE_PUBLIC_ENDPOINT"],
        "HBCB_STORAGE_PUBLIC_SECURE": values["HBCB_STORAGE_PUBLIC_SECURE"],
        "HBCB_STORAGE_ACCESS_KEY": values["HBCB_STORAGE_API_ACCESS_KEY"],
        "HBCB_STORAGE_SECRET_KEY": values["HBCB_STORAGE_API_SECRET_KEY"],
        "HBCB_SIGNED_URL_TTL_SECONDS": values["HBCB_SIGNED_URL_TTL_SECONDS"],
    }
    worker = {
        **shared_storage,
        "HBCB_DATABASE_URL": (
            database_prefix
            + values["HBCB_DATABASE_WORKER_USER"]
            + ":"
            + values["HBCB_DATABASE_WORKER_PASSWORD"]
            + database_suffix
        ),
        "HBCB_REDIS_URL": redis_url,
        "HBCB_STORAGE_ACCESS_KEY": values["HBCB_STORAGE_WORKER_ACCESS_KEY"],
        "HBCB_STORAGE_SECRET_KEY": values["HBCB_STORAGE_WORKER_SECRET_KEY"],
    }
    maintenance = {
        **shared_storage,
        "HBCB_DATABASE_URL": (
            database_prefix
            + values["HBCB_DATABASE_MAINTENANCE_USER"]
            + ":"
            + values["HBCB_DATABASE_MAINTENANCE_PASSWORD"]
            + database_suffix
        ),
        "HBCB_REDIS_URL": redis_url,
        "HBCB_STORAGE_ACCESS_KEY": values[
            "HBCB_STORAGE_MAINTENANCE_ACCESS_KEY"
        ],
        "HBCB_STORAGE_SECRET_KEY": values[
            "HBCB_STORAGE_MAINTENANCE_SECRET_KEY"
        ],
    }
    migrator = {
        "HBCB_DEPLOYMENT_NAMESPACE": values["HBCB_DEPLOYMENT_NAMESPACE"],
        "HBCB_DATABASE_URL": (
            database_prefix
            + values["HBCB_DATABASE_MIGRATOR_USER"]
            + ":"
            + values["HBCB_DATABASE_MIGRATOR_PASSWORD"]
            + database_suffix
        ),
    }
    return api, worker, maintenance, migrator


class InitEnvironmentTests(unittest.TestCase):
    def test_generation_is_mode_0600_random_keyless_and_secret_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            completed = subprocess.run(
                (str(SCRIPT),),
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                env={"PATH": os.environ.get("PATH", "")},
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertEqual(completed.stdout, "INIT_ENV: created .env (mode 0600)\n")
            output = cwd / ".env"
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            values = parse_env(output)
            self.assertEqual(values["HBCB_DEPLOYMENT_NAMESPACE"], "local")
            self.assertNotIn("OPENAI_API_KEY", values)
            secret_names = (
                "HBCB_API_TOKEN",
                "HBCB_IDEMPOTENCY_SECRET",
                "POSTGRES_PASSWORD",
                "HBCB_DATABASE_API_PASSWORD",
                "HBCB_DATABASE_WORKER_PASSWORD",
                "HBCB_DATABASE_MAINTENANCE_PASSWORD",
                "HBCB_DATABASE_MIGRATOR_PASSWORD",
                "REDIS_PASSWORD",
                "MINIO_ROOT_PASSWORD",
                "HBCB_STORAGE_API_SECRET_KEY",
                "HBCB_STORAGE_WORKER_SECRET_KEY",
                "HBCB_STORAGE_MAINTENANCE_SECRET_KEY",
            )
            secrets = [values[name] for name in secret_names]
            self.assertEqual(len(set(secrets)), len(secrets))
            self.assertTrue(all(len(secret) == 64 for secret in secrets))
            self.assertTrue(all(secret not in completed.stdout for secret in secrets))
            self.assertEqual(
                len(
                    {
                        values["HBCB_STORAGE_API_ACCESS_KEY"],
                        values["HBCB_STORAGE_WORKER_ACCESS_KEY"],
                        values["HBCB_STORAGE_MAINTENANCE_ACCESS_KEY"],
                    }
                ),
                3,
            )
            self.assertEqual(values["HBCB_STORAGE_API_ACCESS_KEY"], "hbcb_api")
            self.assertEqual(values["HBCB_STORAGE_WORKER_ACCESS_KEY"], "hbcb_worker")
            self.assertEqual(
                values["HBCB_STORAGE_MAINTENANCE_ACCESS_KEY"],
                "hbcb_maintenance",
            )
            (
                api_environment,
                worker_environment,
                maintenance_environment,
                migrator_environment,
            ) = role_environments(values)
            self.assertIsInstance(ServiceConfig.from_environment(api_environment), ServiceConfig)
            self.assertIsInstance(WorkerConfig.from_environment(worker_environment), WorkerConfig)
            self.assertIsInstance(
                WorkerConfig.from_environment(maintenance_environment), WorkerConfig
            )
            self.assertIsInstance(MigratorConfig.from_environment(migrator_environment), MigratorConfig)
            self.assertNotIn("HBCB_API_TOKEN", worker_environment)
            self.assertNotIn(values["HBCB_STORAGE_WORKER_SECRET_KEY"], api_environment.values())
            self.assertNotIn(values["HBCB_STORAGE_API_SECRET_KEY"], worker_environment.values())
            self.assertNotIn(
                values["HBCB_STORAGE_MAINTENANCE_SECRET_KEY"],
                api_environment.values(),
            )
            self.assertNotIn(
                values["HBCB_STORAGE_MAINTENANCE_SECRET_KEY"],
                worker_environment.values(),
            )
            self.assertEqual(
                set(migrator_environment),
                {"HBCB_DEPLOYMENT_NAMESPACE", "HBCB_DATABASE_URL"},
            )
            initializer = {
                **values,
                "HBCB_DATABASE_ADMIN_URL": (
                    "postgresql://"
                    + values["POSTGRES_USER"]
                    + ":"
                    + values["POSTGRES_PASSWORD"]
                    + "@postgres:5432/"
                    + values["POSTGRES_DB"]
                ),
                "HBCB_DATABASE_MIGRATOR_URL": migrator_environment[
                    "HBCB_DATABASE_URL"
                ],
            }
            self.assertIsInstance(
                DatabaseInitializationConfig.from_environment(initializer),
                DatabaseInitializationConfig,
            )

    def test_upgrade_g8_is_atomic_secret_quiet_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            created = subprocess.run(
                (str(SCRIPT),),
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(created.returncode, 0, created.stdout)
            output = cwd / ".env"
            original_values = parse_env(output)
            maintenance_names = {
                "HBCB_DATABASE_MAINTENANCE_USER",
                "HBCB_DATABASE_MAINTENANCE_PASSWORD",
                "HBCB_STORAGE_MAINTENANCE_ACCESS_KEY",
                "HBCB_STORAGE_MAINTENANCE_SECRET_KEY",
            }
            legacy_lines = [
                f"{name}={value}"
                for name, value in original_values.items()
                if name not in maintenance_names
            ]
            output.write_text("\n".join(legacy_lines) + "\n", encoding="utf-8")
            output.chmod(0o600)
            legacy_hash = hashlib.sha256(output.read_bytes()).hexdigest()

            upgraded = subprocess.run(
                (str(SCRIPT), "--upgrade-g8"),
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(upgraded.returncode, 0, upgraded.stdout)
            self.assertEqual(
                upgraded.stdout,
                "INIT_ENV: upgraded .env to G8 runtime settings (mode 0600)\n",
            )
            self.assertNotEqual(hashlib.sha256(output.read_bytes()).hexdigest(), legacy_hash)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            values = parse_env(output)
            self.assertEqual(
                {name: values[name] for name in original_values if name not in maintenance_names},
                {name: value for name, value in original_values.items() if name not in maintenance_names},
            )
            self.assertEqual(values["HBCB_DATABASE_MAINTENANCE_USER"], "hbcb_maintenance")
            self.assertEqual(
                values["HBCB_STORAGE_MAINTENANCE_ACCESS_KEY"], "hbcb_maintenance"
            )
            generated_secrets = {
                values["HBCB_DATABASE_MAINTENANCE_PASSWORD"],
                values["HBCB_STORAGE_MAINTENANCE_SECRET_KEY"],
            }
            self.assertEqual(len(generated_secrets), 2)
            self.assertTrue(all(len(secret) == 64 for secret in generated_secrets))
            self.assertTrue(all(secret not in upgraded.stdout for secret in generated_secrets))

            before_second = hashlib.sha256(output.read_bytes()).hexdigest()
            repeated = subprocess.run(
                (str(SCRIPT), "--upgrade-g8"),
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(repeated.returncode, 0, repeated.stdout)
            self.assertEqual(
                repeated.stdout,
                "INIT_ENV: .env already satisfies G8 runtime settings (mode 0600)\n",
            )
            self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), before_second)

    def test_upgrade_g8_migrates_a_genuine_g7_storage_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            created = subprocess.run(
                (str(SCRIPT),),
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(created.returncode, 0, created.stdout)
            output = cwd / ".env"
            current = parse_env(output)
            omitted = {
                "HBCB_DATABASE_MAINTENANCE_USER",
                "HBCB_DATABASE_MAINTENANCE_PASSWORD",
                "HBCB_STORAGE_MAINTENANCE_ACCESS_KEY",
                "HBCB_STORAGE_MAINTENANCE_SECRET_KEY",
                "HBCB_STORAGE_INTERNAL_SECURE",
                "HBCB_STORAGE_PUBLIC_SECURE",
                "HBCB_STORAGE_REGION",
            }
            legacy_lines = []
            for name, value in current.items():
                if name == "HBCB_STORAGE_INTERNAL_SECURE":
                    legacy_lines.append("HBCB_STORAGE_SECURE=false")
                elif name not in omitted:
                    legacy_lines.append(f"{name}={value}")
            output.write_text("\n".join(legacy_lines) + "\n", encoding="utf-8")
            output.chmod(0o600)

            upgraded = subprocess.run(
                (str(SCRIPT), "--upgrade-g8"),
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(upgraded.returncode, 0, upgraded.stdout)
            self.assertEqual(
                upgraded.stdout,
                "INIT_ENV: upgraded .env to G8 runtime settings (mode 0600)\n",
            )
            values = parse_env(output)
            self.assertNotIn("HBCB_STORAGE_SECURE", values)
            self.assertEqual(values["HBCB_STORAGE_INTERNAL_SECURE"], "false")
            self.assertEqual(values["HBCB_STORAGE_PUBLIC_SECURE"], "false")
            self.assertEqual(values["HBCB_STORAGE_REGION"], "us-east-1")
            for name, value in current.items():
                if name not in omitted:
                    self.assertEqual(values[name], value)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

    def test_upgrade_g8_rejects_mixed_partial_and_nonlocal_storage_states(self) -> None:
        cases = {
            "mixed": lambda values: {
                **values,
                "HBCB_STORAGE_SECURE": "false",
            },
            "partial": lambda values: {
                name: value
                for name, value in values.items()
                if name != "HBCB_STORAGE_PUBLIC_SECURE"
            },
            "legacy_true": lambda values: {
                **{
                    name: value
                    for name, value in values.items()
                    if name
                    not in {
                        "HBCB_STORAGE_INTERNAL_SECURE",
                        "HBCB_STORAGE_PUBLIC_SECURE",
                        "HBCB_STORAGE_REGION",
                    }
                },
                "HBCB_STORAGE_SECURE": "true",
            },
        }
        for label, mutate in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                cwd = Path(temporary)
                created = subprocess.run(
                    (str(SCRIPT),),
                    cwd=cwd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                self.assertEqual(created.returncode, 0, created.stdout)
                output = cwd / ".env"
                invalid = mutate(parse_env(output))
                output.write_text(
                    "".join(f"{name}={value}\n" for name, value in invalid.items()),
                    encoding="utf-8",
                )
                output.chmod(0o600)
                before = hashlib.sha256(output.read_bytes()).hexdigest()
                completed = subprocess.run(
                    (str(SCRIPT), "--upgrade-g8"),
                    cwd=cwd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                self.assertEqual(completed.returncode, 4)
                self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), before)

    def test_upgrade_g8_rejects_partial_configuration_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            output = cwd / ".env"
            output.write_text(
                "HBCB_DEPLOYMENT_NAMESPACE=local\n"
                "HBCB_DATABASE_MAINTENANCE_USER=hbcb_maintenance\n",
                encoding="utf-8",
            )
            output.chmod(0o600)
            before = hashlib.sha256(output.read_bytes()).hexdigest()
            completed = subprocess.run(
                (str(SCRIPT), "--upgrade-g8"),
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 4)
            self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), before)
            self.assertNotIn("hbcb_maintenance", completed.stdout)

    def test_existing_file_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            output = cwd / ".env"
            output.write_text("sentinel=true\n", encoding="utf-8")
            before = hashlib.sha256(output.read_bytes()).hexdigest()
            completed = subprocess.run(
                (str(SCRIPT),),
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 4)
            self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), before)
            self.assertNotIn("sentinel", completed.stdout)

    def test_existing_symlink_is_never_followed_or_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            sentinel = cwd / "sentinel"
            sentinel.write_text("preserve\n", encoding="utf-8")
            (cwd / ".env").symlink_to(sentinel)
            completed = subprocess.run(
                (str(SCRIPT),),
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 4)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve\n")
            self.assertTrue((cwd / ".env").is_symlink())

    def test_example_contains_placeholders_only_and_no_provider_key(self) -> None:
        payload = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("replace-me", payload)
        self.assertNotIn("OPENAI_API_KEY", payload)
        self.assertNotIn("sk-", payload)
