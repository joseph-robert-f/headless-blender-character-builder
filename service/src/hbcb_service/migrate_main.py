"""Forward-only migration process entrypoint."""

from __future__ import annotations

import json
import os
from typing import Mapping, Optional

from .config import MigratorConfig
from .migrations import apply_postgres_migrations
from .runtime import postgres_connection_factory


def migrate(environment: Optional[Mapping[str, str]] = None):
    supplied = os.environ if environment is None else environment
    config = MigratorConfig.from_environment(supplied)
    connection = postgres_connection_factory(config.database_url)()
    try:
        return apply_postgres_migrations(connection)
    finally:
        try:
            connection.close()
        except Exception:
            pass


def main() -> None:
    result = migrate()
    print(
        json.dumps(
            {
                "event": "migrations_complete",
                "applied": list(result.applied),
                "already_current": result.already_current,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
