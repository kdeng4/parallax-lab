"""PostgreSQL persistence with the same atomic, immutable contract as SQLite."""

from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .storage import SUMMARY_KEYS


class PostgresStore:
    dialect = "postgresql"
    integrity_error = psycopg.IntegrityError

    def __init__(self, database_url: str):
        self._database_url = database_url

    @contextmanager
    def connection(self):
        # Neon provides transaction pooling. Close each client connection rather
        # than retaining sockets across a serverless instance's suspension.
        with psycopg.connect(self._database_url, connect_timeout=15,
                             prepare_threshold=None, row_factory=dict_row) as connection:
            connection.execute("SET LOCAL statement_timeout = '30s'")
            yield connection

    def initialize(self):
        # Runtime credentials cannot migrate the schema. Run the versioned
        # migration explicitly with the direct owner connection before deploy.
        try:
            with self.connection() as connection:
                row = connection.execute("SELECT version FROM schema_migrations WHERE version=1").fetchone()
                if row is None:
                    raise RuntimeError("Run the PostgreSQL migration before starting the API")
        except psycopg.errors.UndefinedTable:
            raise RuntimeError("Run the PostgreSQL migration before starting the API") from None

    def has(self, experiment_id: str) -> bool:
        with self.connection() as connection:
            return connection.execute("SELECT 1 FROM experiments WHERE id=%s", (experiment_id,)).fetchone() is not None

    def save(self, detail: dict):
        summary = {key: detail[key] for key in SUMMARY_KEYS}
        payload = {key: value for key, value in detail.items() if key != "events"}
        with self.connection() as connection:
            connection.execute("INSERT INTO experiments (id, created_at, summary, payload) VALUES (%s, %s, %s, %s)",
                               (detail["id"], detail["created_at"], Jsonb(summary), Jsonb(payload)))
            with connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO events (id, experiment_id, sequence, timestamp, run_id, type, payload) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    [(event["id"], detail["id"], event["sequence"], event["timestamp"],
                      event["run_id"], event["type"], Jsonb(event)) for event in detail["events"]],
                )

    def list_experiments(self) -> list[dict]:
        with self.connection() as connection:
            return [row["summary"] for row in connection.execute(
                "SELECT summary FROM experiments ORDER BY created_at DESC, id DESC")]

    def get(self, experiment_id: str) -> dict | None:
        with self.connection() as connection:
            row = connection.execute("SELECT payload FROM experiments WHERE id=%s", (experiment_id,)).fetchone()
            if row is None:
                return None
            result = row["payload"]
            result["events"] = [event["payload"] for event in connection.execute(
                "SELECT payload FROM events WHERE experiment_id=%s ORDER BY sequence", (experiment_id,))]
            return result

    def filter_events(self, experiment_id: str, *, run_id: str | None, event_type: str | None,
                      from_time: str | None, to_time: str | None, limit: int, offset: int) -> dict:
        clauses, values = ["experiment_id=%s"], [experiment_id]
        # Identifiers and operators are internal constants; all values are bound.
        for column, operator, value in (("run_id", "=", run_id), ("type", "=", event_type),
                                         ("timestamp", ">=", from_time), ("timestamp", "<=", to_time)):
            if value is not None:
                clauses.append(f"{column}{operator}%s")
                values.append(value)
        where = " AND ".join(clauses)
        with self.connection() as connection:
            count = connection.execute(f"SELECT count(*) AS total FROM events WHERE {where}", values).fetchone()["total"]
            rows = connection.execute(f"SELECT payload FROM events WHERE {where} ORDER BY sequence LIMIT %s OFFSET %s",
                                      [*values, limit, offset])
            return {"events": [row["payload"] for row in rows], "total": count, "limit": limit, "offset": offset}
