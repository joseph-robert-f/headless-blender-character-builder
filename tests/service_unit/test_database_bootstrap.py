from __future__ import annotations

import unittest

from hbcb_service.config import DatabaseInitializationConfig
from hbcb_service.database_bootstrap import (
    API_TABLE_PRIVILEGES,
    MAINTENANCE_COLUMN_PRIVILEGES,
    MAINTENANCE_SEQUENCES,
    MAINTENANCE_TABLE_PRIVILEGES,
    MIGRATOR_DEFAULT_OBJECTS,
    RUNTIME_SEQUENCES,
    WORKER_TABLE_PRIVILEGES,
)
from hbcb_service.errors import ConfigurationError


def initialization_environment() -> dict[str, str]:
    return {
        "HBCB_DEPLOYMENT_NAMESPACE": "local",
        "POSTGRES_DB": "hbcb",
        "HBCB_DATABASE_ADMIN_URL": "postgresql://hbcb_admin:" + "a" * 32 + "@postgres:5432/hbcb",
        "HBCB_DATABASE_MIGRATOR_URL": "postgresql://hbcb_migrator:" + "b" * 32 + "@postgres:5432/hbcb",
        "HBCB_DATABASE_API_USER": "hbcb_api",
        "HBCB_DATABASE_API_PASSWORD": "c" * 32,
        "HBCB_DATABASE_WORKER_USER": "hbcb_worker",
        "HBCB_DATABASE_WORKER_PASSWORD": "d" * 32,
        "HBCB_DATABASE_MAINTENANCE_USER": "hbcb_maintenance",
        "HBCB_DATABASE_MAINTENANCE_PASSWORD": "e" * 32,
        "HBCB_DATABASE_MIGRATOR_USER": "hbcb_migrator",
        "HBCB_DATABASE_MIGRATOR_PASSWORD": "b" * 32,
    }


class DatabaseInitializationConfigTests(unittest.TestCase):
    def test_roles_and_urls_are_distinct_aligned_and_redacted(self) -> None:
        environment = initialization_environment()
        config = DatabaseInitializationConfig.from_environment(environment)
        self.assertEqual(config.database_name, "hbcb")
        self.assertEqual(config.admin_username, "hbcb_admin")
        rendered = repr(config) + repr(config.redacted())
        for name in (
            "HBCB_DATABASE_ADMIN_URL",
            "HBCB_DATABASE_MIGRATOR_URL",
            "HBCB_DATABASE_API_PASSWORD",
            "HBCB_DATABASE_WORKER_PASSWORD",
            "HBCB_DATABASE_MAINTENANCE_PASSWORD",
            "HBCB_DATABASE_MIGRATOR_PASSWORD",
        ):
            self.assertNotIn(environment[name], rendered)

    def test_role_overlap_url_mismatch_and_placeholder_fail_closed(self) -> None:
        cases = (
            ("HBCB_DATABASE_WORKER_USER", "hbcb_api"),
            ("HBCB_DATABASE_MAINTENANCE_USER", "hbcb_worker"),
            ("HBCB_DATABASE_MIGRATOR_URL", "postgresql://hbcb_migrator:" + "b" * 32 + "@other:5432/hbcb"),
            ("HBCB_DATABASE_API_PASSWORD", "replace-me"),
            ("POSTGRES_DB", "../hbcb"),
        )
        for name, value in cases:
            with self.subTest(name=name):
                environment = initialization_environment()
                environment[name] = value
                with self.assertRaises(ConfigurationError):
                    DatabaseInitializationConfig.from_environment(environment)

    def test_runtime_grants_are_explicit_and_non_destructive(self) -> None:
        allowed = {"SELECT", "INSERT", "UPDATE"}
        for privileges in (*API_TABLE_PRIVILEGES.values(), *WORKER_TABLE_PRIVILEGES.values()):
            self.assertTrue(set(privileges) <= allowed)
            self.assertNotIn("DELETE", privileges)
            self.assertNotIn("TRUNCATE", privileges)
        self.assertEqual(RUNTIME_SEQUENCES, ("build_events_id_seq", "queue_outbox_id_seq"))
        self.assertEqual(MIGRATOR_DEFAULT_OBJECTS, ("TABLES", "SEQUENCES"))
        self.assertEqual(API_TABLE_PRIVILEGES["schema_migrations"], ("SELECT",))
        self.assertNotIn("idempotency_keys", WORKER_TABLE_PRIVILEGES)

    def test_maintenance_grants_match_the_bounded_maintenance_sql(self) -> None:
        self.assertEqual(
            MAINTENANCE_TABLE_PRIVILEGES,
            {
                "artifact_deletion_attempts": ("INSERT",),
                "artifact_deletion_queue": ("SELECT", "INSERT", "UPDATE"),
                "artifact_restore_remaps": ("INSERT",),
                "artifacts": ("SELECT",),
                "builds": ("SELECT", "DELETE"),
            },
        )
        self.assertEqual(
            MAINTENANCE_SEQUENCES,
            (
                "artifact_deletion_attempts_id_seq",
                "artifact_deletion_queue_id_seq",
                "artifact_restore_remaps_id_seq",
            ),
        )
        self.assertEqual(
            MAINTENANCE_COLUMN_PRIVILEGES,
            {
                "artifacts": {"version_id": ("UPDATE",)},
                "builds": {"updated_at": ("UPDATE",)},
            },
        )
        privileges = {
            privilege
            for table_privileges in MAINTENANCE_TABLE_PRIVILEGES.values()
            for privilege in table_privileges
        }
        self.assertEqual(privileges, {"SELECT", "INSERT", "UPDATE", "DELETE"})
        self.assertNotIn("TRUNCATE", privileges)
        self.assertNotIn("schema_migrations", MAINTENANCE_TABLE_PRIVILEGES)
        self.assertNotIn("idempotency_keys", MAINTENANCE_TABLE_PRIVILEGES)


if __name__ == "__main__":
    unittest.main()
