from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from hbcb_service.config import MigratorConfig, ServiceConfig, WorkerConfig

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
        "HBCB_STORAGE_SECURE": values["HBCB_STORAGE_SECURE"],
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
    return api, worker, migrator


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
                "HBCB_DATABASE_MIGRATOR_PASSWORD",
                "REDIS_PASSWORD",
                "MINIO_ROOT_PASSWORD",
                "HBCB_STORAGE_API_SECRET_KEY",
                "HBCB_STORAGE_WORKER_SECRET_KEY",
            )
            secrets = [values[name] for name in secret_names]
            self.assertEqual(len(set(secrets)), len(secrets))
            self.assertTrue(all(len(secret) == 64 for secret in secrets))
            self.assertTrue(all(secret not in completed.stdout for secret in secrets))
            self.assertNotEqual(
                values["HBCB_STORAGE_API_ACCESS_KEY"],
                values["HBCB_STORAGE_WORKER_ACCESS_KEY"],
            )
            self.assertEqual(values["HBCB_STORAGE_API_ACCESS_KEY"], "hbcb_api")
            self.assertEqual(values["HBCB_STORAGE_WORKER_ACCESS_KEY"], "hbcb_worker")
            api_environment, worker_environment, migrator_environment = role_environments(values)
            self.assertIsInstance(ServiceConfig.from_environment(api_environment), ServiceConfig)
            self.assertIsInstance(WorkerConfig.from_environment(worker_environment), WorkerConfig)
            self.assertIsInstance(MigratorConfig.from_environment(migrator_environment), MigratorConfig)
            self.assertNotIn("HBCB_API_TOKEN", worker_environment)
            self.assertNotIn(values["HBCB_STORAGE_WORKER_SECRET_KEY"], api_environment.values())
            self.assertNotIn(values["HBCB_STORAGE_API_SECRET_KEY"], worker_environment.values())
            self.assertEqual(
                set(migrator_environment),
                {"HBCB_DEPLOYMENT_NAMESPACE", "HBCB_DATABASE_URL"},
            )

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
