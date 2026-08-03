"""Idempotent PostgreSQL role, migration, and least-privilege bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Tuple

from .config import DatabaseInitializationConfig
from .errors import MigrationError
from .migrations import apply_postgres_migrations
from .runtime import postgres_connection_factory


API_TABLE_PRIVILEGES = {
    "artifacts": ("SELECT",),
    "build_attempts": ("SELECT",),
    "build_events": ("SELECT", "INSERT"),
    "builds": ("SELECT", "INSERT", "UPDATE"),
    "idempotency_keys": ("SELECT", "INSERT"),
    "queue_outbox": ("INSERT",),
    "schema_migrations": ("SELECT",),
}

WORKER_TABLE_PRIVILEGES = {
    "artifacts": ("SELECT", "INSERT"),
    "build_attempts": ("SELECT", "INSERT", "UPDATE"),
    "build_events": ("SELECT", "INSERT"),
    "builds": ("SELECT", "UPDATE"),
    "queue_outbox": ("SELECT", "INSERT", "UPDATE"),
}

RUNTIME_SEQUENCES = ("build_events_id_seq", "queue_outbox_id_seq")
MIGRATOR_DEFAULT_OBJECTS = ("TABLES", "SEQUENCES")


@dataclass(frozen=True)
class DatabaseInitializationResult:
    applied_migrations: Tuple[str, ...]
    api_tables: Tuple[str, ...]
    worker_tables: Tuple[str, ...]


def _close(connection: Any) -> None:
    try:
        connection.close()
    except Exception:
        pass


def _ensure_roles(connection: Any, config: DatabaseInitializationConfig) -> None:
    from psycopg import sql

    roles = (
        (config.api_username, config.api_password.reveal()),
        (config.worker_username, config.worker_password.reveal()),
        (config.migrator_username, config.migrator_password.reveal()),
    )
    try:
        cursor = connection.cursor()
        for username, password in roles:
            cursor.execute("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s", (username,))
            exists = cursor.fetchone() is not None
            template = (
                "ALTER ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                if exists
                else "CREATE ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
            )
            cursor.execute(
                sql.SQL(template).format(sql.Identifier(username), sql.Literal(password))
            )
            cursor.execute(
                """
                SELECT granted.rolname
                FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid
                JOIN pg_catalog.pg_roles AS member_role ON member_role.oid = membership.member
                WHERE member_role.rolname = %s
                """,
                (username,),
            )
            for (granted_role,) in cursor.fetchall():
                cursor.execute(
                    sql.SQL("REVOKE {} FROM {}").format(
                        sql.Identifier(granted_role), sql.Identifier(username)
                    )
                )
        cursor.execute(
            sql.SQL("REVOKE ALL PRIVILEGES ON DATABASE {} FROM PUBLIC").format(
                sql.Identifier(config.database_name)
            )
        )
        for username in (config.api_username, config.worker_username, config.migrator_username):
            cursor.execute(
                sql.SQL("REVOKE ALL PRIVILEGES ON DATABASE {} FROM {}").format(
                    sql.Identifier(config.database_name), sql.Identifier(username)
                )
            )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(config.database_name), sql.Identifier(username)
                )
            )
        cursor.execute(
            sql.SQL("GRANT CREATE ON DATABASE {} TO {}").format(
                sql.Identifier(config.database_name), sql.Identifier(config.migrator_username)
            )
        )
        cursor.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        connection.commit()
    except Exception as exc:
        try:
            connection.rollback()
        except Exception:
            pass
        raise MigrationError(
            "database_role_bootstrap_failed", "database roles could not be initialized"
        ) from exc
    finally:
        try:
            cursor.close()
        except (AttributeError, UnboundLocalError):
            pass


def _grant_table(
    cursor: Any,
    sql: Any,
    *,
    table: str,
    privileges: Tuple[str, ...],
    role: str,
) -> None:
    privilege_sql = sql.SQL(", ").join(sql.SQL(value) for value in privileges)
    cursor.execute(
        sql.SQL("GRANT {} ON TABLE hbcb.{} TO {}").format(
            privilege_sql,
            sql.Identifier(table),
            sql.Identifier(role),
        )
    )


def _grant_runtime_privileges(
    connection: Any, config: DatabaseInitializationConfig
) -> None:
    from psycopg import sql

    try:
        cursor = connection.cursor()
        default_grantees = (
            sql.SQL("PUBLIC"),
            sql.Identifier(config.api_username),
            sql.Identifier(config.worker_username),
        )
        for object_type in MIGRATOR_DEFAULT_OBJECTS:
            for grantee in default_grantees:
                cursor.execute(
                    sql.SQL(
                        "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA hbcb "
                        "REVOKE ALL ON {} FROM {}"
                    ).format(
                        sql.Identifier(config.migrator_username),
                        sql.SQL(object_type),
                        grantee,
                    )
                )
        cursor.execute("REVOKE ALL ON SCHEMA hbcb FROM PUBLIC")
        cursor.execute("REVOKE ALL ON ALL TABLES IN SCHEMA hbcb FROM PUBLIC")
        cursor.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA hbcb FROM PUBLIC")
        for role in (config.api_username, config.worker_username):
            cursor.execute(
                sql.SQL("REVOKE ALL ON SCHEMA hbcb FROM {}").format(sql.Identifier(role))
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA hbcb TO {}").format(sql.Identifier(role))
            )
            cursor.execute(
                sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA hbcb FROM {}").format(
                    sql.Identifier(role)
                )
            )
            cursor.execute(
                sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA hbcb FROM {}").format(
                    sql.Identifier(role)
                )
            )
        for table, privileges in API_TABLE_PRIVILEGES.items():
            _grant_table(
                cursor,
                sql,
                table=table,
                privileges=privileges,
                role=config.api_username,
            )
        for table, privileges in WORKER_TABLE_PRIVILEGES.items():
            _grant_table(
                cursor,
                sql,
                table=table,
                privileges=privileges,
                role=config.worker_username,
            )
        for role in (config.api_username, config.worker_username):
            for sequence in RUNTIME_SEQUENCES:
                cursor.execute(
                    sql.SQL("GRANT USAGE, SELECT ON SEQUENCE hbcb.{} TO {}").format(
                        sql.Identifier(sequence), sql.Identifier(role)
                    )
                )
        connection.commit()
    except Exception as exc:
        try:
            connection.rollback()
        except Exception:
            pass
        raise MigrationError(
            "database_privilege_bootstrap_failed",
            "database runtime privileges could not be initialized",
        ) from exc
    finally:
        try:
            cursor.close()
        except (AttributeError, UnboundLocalError):
            pass


def initialize_database(
    config: DatabaseInitializationConfig,
    *,
    connection_factory: Callable[[object], Callable[[], Any]] = postgres_connection_factory,
) -> DatabaseInitializationResult:
    if not isinstance(config, DatabaseInitializationConfig):
        raise MigrationError("invalid_initialization_config", "database initialization is invalid")

    admin = connection_factory(config.admin_database_url)()
    try:
        _ensure_roles(admin, config)
    finally:
        _close(admin)

    migrator = connection_factory(config.migrator_database_url)()
    try:
        migration = apply_postgres_migrations(migrator)
    finally:
        _close(migrator)

    admin = connection_factory(config.admin_database_url)()
    try:
        _grant_runtime_privileges(admin, config)
    finally:
        _close(admin)

    return DatabaseInitializationResult(
        applied_migrations=migration.applied,
        api_tables=tuple(sorted(API_TABLE_PRIVILEGES)),
        worker_tables=tuple(sorted(WORKER_TABLE_PRIVILEGES)),
    )


__all__ = [
    "API_TABLE_PRIVILEGES",
    "MIGRATOR_DEFAULT_OBJECTS",
    "WORKER_TABLE_PRIVILEGES",
    "DatabaseInitializationResult",
    "initialize_database",
]
