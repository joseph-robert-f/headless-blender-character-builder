"""Checksum-verified, forward-only PostgreSQL migration runner."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

from .errors import MigrationError


MIGRATION_NAME_PATTERN = re.compile(r"^[0-9]{4}_[a-z][a-z0-9_]*\.sql$")
MAX_MIGRATION_BYTES = 1024 * 1024
ADVISORY_LOCK_ID = 381_242_011_274_829_113


@dataclass(frozen=True)
class Migration:
    version: str
    sha256: str
    sql: str


@dataclass(frozen=True)
class MigrationResult:
    applied: Tuple[str, ...]
    already_current: bool


def load_migrations(directory: Optional[Path] = None) -> Tuple[Migration, ...]:
    root = Path(directory) if directory is not None else Path(__file__).with_name("migrations")
    if root.is_symlink() or not root.is_dir():
        raise MigrationError("migration_catalog_missing", "migration catalog is unavailable")
    migrations = []
    for path in sorted(root.iterdir(), key=lambda candidate: candidate.name):
        if path.name.startswith("."):
            continue
        if path.is_symlink() or not path.is_file() or MIGRATION_NAME_PATTERN.fullmatch(path.name) is None:
            raise MigrationError("invalid_migration_catalog", "migration catalog contains an unsafe entry")
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise MigrationError("migration_unreadable", "migration could not be read") from exc
        if not payload or len(payload) > MAX_MIGRATION_BYTES:
            raise MigrationError("invalid_migration", "migration size is outside policy")
        try:
            sql = payload.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise MigrationError("invalid_migration", "migration is not UTF-8") from exc
        migrations.append(
            Migration(
                version=path.name[:-4],
                sha256=hashlib.sha256(payload).hexdigest(),
                sql=sql,
            )
        )
    if not migrations or len({migration.version for migration in migrations}) != len(migrations):
        raise MigrationError("invalid_migration_catalog", "migration catalog is empty or ambiguous")
    return tuple(migrations)


def apply_postgres_migrations(connection: Any, directory: Optional[Path] = None) -> MigrationResult:
    """Apply pending migrations in one database transaction.

    ``connection`` is a psycopg-compatible DB-API connection.  The runner uses
    no driver-specific imports so its ordering, drift, rollback, and SQL
    contract can be unit-tested without adding service dependencies to G4.
    """

    migrations = load_migrations(directory)
    applied_versions = []
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_ID,))
        cursor.execute("CREATE SCHEMA IF NOT EXISTS hbcb")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS hbcb.schema_migrations (
                version varchar(128) PRIMARY KEY,
                sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
                applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute("SELECT version, sha256 FROM hbcb.schema_migrations ORDER BY version")
        rows = cursor.fetchall()
        recorded = {}
        for row in rows:
            if not isinstance(row, (tuple, list)) or len(row) != 2:
                raise MigrationError("invalid_migration_state", "migration table returned invalid state")
            version, sha256 = row
            if not isinstance(version, str) or not isinstance(sha256, str):
                raise MigrationError("invalid_migration_state", "migration table returned invalid state")
            recorded[version] = sha256
        available = {migration.version: migration for migration in migrations}
        unknown = sorted(set(recorded) - set(available))
        if unknown:
            raise MigrationError("database_schema_ahead", "database contains unknown migrations")
        for version, digest in recorded.items():
            if available[version].sha256 != digest:
                raise MigrationError("migration_checksum_mismatch", "recorded migration checksum changed")
        for migration in migrations:
            if migration.version in recorded:
                continue
            cursor.execute(migration.sql)
            cursor.execute(
                "INSERT INTO hbcb.schema_migrations (version, sha256) VALUES (%s, %s)",
                (migration.version, migration.sha256),
            )
            applied_versions.append(migration.version)
        connection.commit()
    except Exception as exc:
        try:
            connection.rollback()
        except Exception:
            pass
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError("migration_failed", "PostgreSQL migration failed") from exc
    finally:
        try:
            cursor.close()
        except (AttributeError, UnboundLocalError):
            pass
    return MigrationResult(tuple(applied_versions), not applied_versions)
