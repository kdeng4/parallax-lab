"""Apply versioned schema changes using a direct PostgreSQL owner connection."""

import os
from pathlib import Path

import psycopg


def migrate(database_url: str):
    with psycopg.connect(database_url, connect_timeout=15) as connection:
        # Serializes concurrent migration runners; released on commit/rollback.
        connection.execute("SELECT pg_advisory_xact_lock(719230014)")
        exists = connection.execute("SELECT to_regclass('public.schema_migrations')").fetchone()[0]
        versions = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")} if exists else set()
        if exists and (not versions or versions != set(range(1, max(versions) + 1)) or max(versions) > 2):
            raise RuntimeError("Unexpected migration state; inspect the schema before retrying")
        for version, name in ((1, "001_initial.sql"), (2, "002_market_cache.sql")):
            if version not in versions:
                connection.execute((Path(__file__).parent / "migrations" / name).read_text())


if __name__ == "__main__":
    url = os.environ.get("PARALLAX_DATABASE_URL_UNPOOLED")
    if not url or not url.startswith(("postgresql://", "postgres://")):
        raise SystemExit("Set PARALLAX_DATABASE_URL_UNPOOLED to the direct PostgreSQL owner connection")
    migrate(url)
    print("PostgreSQL schema is at version 2")
