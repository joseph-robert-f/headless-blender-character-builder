"""One-shot Compose database initializer entrypoint."""

from __future__ import annotations

import json
import os

from .config import DatabaseInitializationConfig
from .database_bootstrap import initialize_database


def main() -> None:
    config = DatabaseInitializationConfig.from_environment(os.environ)
    result = initialize_database(config)
    print(
        json.dumps(
            {
                "event": "database_initialized",
                "applied_migrations": list(result.applied_migrations),
                "api_table_grants": len(result.api_tables),
                "worker_table_grants": len(result.worker_tables),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
