#!/usr/bin/env python3
"""Apply G5 migrations twice and probe constraints on real PostgreSQL."""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg

from hbcb_service.migrations import apply_postgres_migrations, load_migrations


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SQL = Path(__file__).with_name("g5_postgres_contract.sql")


def main() -> int:
    dsn = os.environ.get("HBCB_G5_POSTGRES_DSN")
    if not dsn:
        raise SystemExit("G5_POSTGRES_GATE: HBCB_G5_POSTGRES_DSN is required")

    with psycopg.connect(dsn) as connection:
        first = apply_postgres_migrations(connection)
        second = apply_postgres_migrations(connection)
        if first.applied != (
            "0001_g5_foundation",
            "0002_g6_outbox_counter",
        ) or not second.already_current:
            raise RuntimeError("migration application was not forward-only and idempotent")
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version")
            server_version = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT count(*)
                FROM information_schema.tables
                WHERE table_schema = 'hbcb'
                """
            )
            if cursor.fetchone()[0] != 7:
                raise RuntimeError("unexpected durable table inventory")
            cursor.execute(
                """
                SELECT conname
                FROM pg_constraint
                WHERE connamespace = 'hbcb'::regnamespace
                """
            )
            constraints = {row[0] for row in cursor.fetchall()}
            required_constraints = {
                "builds_manifest_state_check",
                "builds_terminal_code_state_check",
                "attempts_terminal_timestamp_check",
                "events_attempt_owner_fk",
                "events_status_check",
                "artifacts_attempt_owner_fk",
                "artifacts_content_type_check",
            }
            if not required_constraints <= constraints:
                raise RuntimeError("required PostgreSQL constraints are missing")
            cursor.execute(CONTRACT_SQL.read_text(encoding="utf-8"))
            contract_result = None
            while True:
                if cursor.description is not None:
                    row = cursor.fetchone()
                    if row:
                        contract_result = row[0]
                if not cursor.nextset():
                    break
            if contract_result != "G5_POSTGRES_CONTRACT: PASS":
                raise RuntimeError("PostgreSQL contract probe did not reach PASS")
        connection.rollback()

    migration = load_migrations()[0]
    print(
        json.dumps(
            {
                "gate": "G5_POSTGRES_GATE",
                "migration": migration.version,
                "migration_sha256": migration.sha256,
                "postgres": server_version,
                "result": "PASS",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
