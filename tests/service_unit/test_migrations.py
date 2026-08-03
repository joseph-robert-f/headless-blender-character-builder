from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from hbcb_service.errors import MigrationError
from hbcb_service.migrations import apply_postgres_migrations, load_migrations


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.closed = False
        self._rows = []

    def execute(self, sql: str, parameters: object = None) -> None:
        self.connection.executions.append((sql, parameters))
        if self.connection.fail_on_schema and "CREATE TABLE hbcb.builds" in sql:
            raise RuntimeError("synthetic database failure")
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT version, sha256 FROM hbcb.schema_migrations"):
            self._rows = sorted(self.connection.applied.items())
        elif normalized.startswith("INSERT INTO hbcb.schema_migrations"):
            version, sha256 = parameters
            self.connection.applied[version] = sha256

    def fetchall(self) -> list[tuple[str, str]]:
        return list(self._rows)

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self) -> None:
        self.applied: dict[str, str] = {}
        self.executions: list[tuple[str, object]] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_on_schema = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class MigrationCatalogTests(unittest.TestCase):
    def test_catalog_is_ordered_utf8_bounded_and_checksum_addressed(self) -> None:
        migrations = load_migrations()
        self.assertEqual([migration.version for migration in migrations], ["0001_g5_foundation"])
        migration = migrations[0]
        self.assertEqual(len(migration.sha256), 64)
        self.assertIn("CREATE TABLE hbcb.builds", migration.sql)

    def test_schema_contains_all_durable_models_and_release_constraints(self) -> None:
        sql = load_migrations()[0].sql
        for table in (
            "hbcb.builds",
            "hbcb.idempotency_keys",
            "hbcb.build_attempts",
            "hbcb.build_events",
            "hbcb.artifacts",
            "hbcb.queue_outbox",
        ):
            self.assertIn("CREATE TABLE " + table, sql)
        for invariant in (
            "octet_length(request_canonical) BETWEEN 1 AND 65536",
            "attempts_one_active_idx",
            "UNIQUE (build_id, build_version)",
            "manifest.json",
            "artifacts_attempt_owner_fk",
            "events_attempt_owner_fk",
            "outbox_pending_idx",
            "finished_at IS NOT NULL",
            "published_at IS NOT NULL",
            "manifest_sha256 IS NOT NULL",
            "manifest_bytes IS NOT NULL",
        ):
            self.assertIn(invariant, sql)

    def test_catalog_rejects_symlink_and_unrecognized_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.txt").write_text("not a migration", encoding="utf-8")
            with self.assertRaises(MigrationError):
                load_migrations(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "outside.sql"
            target.write_text("SELECT 1;", encoding="utf-8")
            (root / "0001_link.sql").symlink_to(target)
            with self.assertRaises(MigrationError):
                load_migrations(root)


class MigrationRunnerTests(unittest.TestCase):
    def test_first_apply_and_idempotent_reapply(self) -> None:
        connection = FakeConnection()
        first = apply_postgres_migrations(connection)
        self.assertEqual(first.applied, ("0001_g5_foundation",))
        self.assertFalse(first.already_current)
        self.assertEqual(connection.commits, 1)
        second = apply_postgres_migrations(connection)
        self.assertEqual(second.applied, ())
        self.assertTrue(second.already_current)
        self.assertEqual(connection.commits, 2)
        inserts = [
            parameters
            for sql, parameters in connection.executions
            if "INSERT INTO hbcb.schema_migrations" in sql
        ]
        self.assertEqual(len(inserts), 1)

    def test_recorded_checksum_drift_rolls_back(self) -> None:
        connection = FakeConnection()
        migration = load_migrations()[0]
        connection.applied[migration.version] = migration.sha256
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = Path(__file__).resolve().parents[2] / "service" / "src" / "hbcb_service" / "migrations" / "0001_g5_foundation.sql"
            changed = root / source.name
            shutil.copyfile(source, changed)
            changed.write_text(changed.read_text(encoding="utf-8") + "\n-- drift\n", encoding="utf-8")
            with self.assertRaises(MigrationError) as captured:
                apply_postgres_migrations(connection, root)
        self.assertEqual(captured.exception.code, "migration_checksum_mismatch")
        self.assertEqual(connection.rollbacks, 1)

    def test_unknown_database_migration_fails_closed(self) -> None:
        connection = FakeConnection()
        connection.applied["9999_future"] = "a" * 64
        with self.assertRaises(MigrationError) as captured:
            apply_postgres_migrations(connection)
        self.assertEqual(captured.exception.code, "database_schema_ahead")
        self.assertEqual(connection.rollbacks, 1)

    def test_database_error_rolls_back_without_commit(self) -> None:
        connection = FakeConnection()
        connection.fail_on_schema = True
        with self.assertRaises(MigrationError) as captured:
            apply_postgres_migrations(connection)
        self.assertEqual(captured.exception.code, "migration_failed")
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_migration_metadata_insert_uses_bound_parameters(self) -> None:
        connection = FakeConnection()
        apply_postgres_migrations(connection)
        insertion = next(
            (sql, parameters)
            for sql, parameters in connection.executions
            if "INSERT INTO hbcb.schema_migrations" in sql
        )
        self.assertIn("VALUES (%s, %s)", insertion[0])
        self.assertEqual(len(insertion[1]), 2)
