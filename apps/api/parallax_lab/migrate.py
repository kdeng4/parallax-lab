"""Apply versioned schema changes using a direct PostgreSQL owner connection."""

import os
from pathlib import Path

import psycopg


def migrate(database_url: str):
    with psycopg.connect(database_url, connect_timeout=15) as connection:
        # Serializes concurrent migration runners; released on commit/rollback.
        connection.execute("SELECT pg_advisory_xact_lock(719230014)")
        exists = connection.execute("SELECT to_regclass('public.schema_migrations')").fetchone()[0]
        if exists:
            if connection.execute("SELECT 1 FROM schema_migrations WHERE version=1").fetchone():
                return
            raise RuntimeError("Unexpected migration state; inspect the schema before retrying")
        connection.execute((Path(__file__).parent / "migrations" / "001_initial.sql").read_text())


if __name__ == "__main__":
    url = os.environ.get("PARALLAX_DATABASE_URL_UNPOOLED")
    if not url or not url.startswith(("postgresql://", "postgres://")):
        raise SystemExit("Set PARALLAX_DATABASE_URL_UNPOOLED to the direct PostgreSQL owner connection")
    migrate(url)
    print("PostgreSQL schema is at version 1")
