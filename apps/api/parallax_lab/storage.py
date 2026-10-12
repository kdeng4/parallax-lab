"""SQLite transaction boundary: an experiment and its immutable audit commit together."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

SUMMARY_KEYS = ("id", "name", "comparison", "symbol", "status", "created_at", "data_source", "seed", "bars", "initial_cash", "participants", "best_return_pct")


def epoch_microseconds(value: str) -> int:
    delta = datetime.fromisoformat(value.replace("Z", "+00:00")) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


class Store:
    dialect = "sqlite"
    def __init__(self, database_url: str):
        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            raise ValueError("Milestone 1 supports sqlite:/// database URLs only")
        self.path = Path(database_url[len(prefix):]).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.create_function("epoch_us", 1, epoch_microseconds, deterministic=True)
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS market_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL CHECK (length(value) <= 1048576)
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL REFERENCES experiments(id),
                    sequence INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    run_id TEXT,
                    type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(experiment_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS events_filter ON events(experiment_id, run_id, type, timestamp);
                CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN
                    SELECT RAISE(ABORT, 'Audit events are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN
                    SELECT RAISE(ABORT, 'Audit events are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS experiments_no_update BEFORE UPDATE ON experiments BEGIN
                    SELECT RAISE(ABORT, 'Completed experiments are immutable');
                END;
            """)

    def has(self, experiment_id: str) -> bool:
        with self.connection() as connection:
            return connection.execute("SELECT 1 FROM experiments WHERE id=?", (experiment_id,)).fetchone() is not None

    def save(self, detail: dict):
        summary = {key: detail[key] for key in SUMMARY_KEYS}
        payload = {key: value for key, value in detail.items() if key != "events"}
        with self.connection() as connection:
            connection.execute("INSERT INTO experiments VALUES (?, ?, ?, ?)",
                               (detail["id"], detail["created_at"], json.dumps(summary, allow_nan=False), json.dumps(payload, allow_nan=False)))
            connection.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   [(event["id"], detail["id"], event["sequence"], event["timestamp"], event["run_id"], event["type"], json.dumps(event, allow_nan=False)) for event in detail["events"]])

    def list_experiments(self, *, limit: int | None = None) -> list[dict]:
        query = "SELECT summary FROM experiments ORDER BY created_at DESC, id DESC"
        if limit is not None:
            query += " LIMIT ?"
        with self.connection() as connection:
            return [json.loads(row["summary"]) for row in connection.execute(query, (limit,) if limit is not None else ())]

    def get(self, experiment_id: str, *, include_events: bool = True) -> dict | None:
        with self.connection() as connection:
            row = connection.execute("SELECT payload FROM experiments WHERE id=?", (experiment_id,)).fetchone()
            if row is None:
                return None
            result = json.loads(row["payload"])
            if include_events:
                result["events"] = [json.loads(event["payload"]) for event in connection.execute(
                    "SELECT payload FROM events WHERE experiment_id=? ORDER BY sequence", (experiment_id,))]
            return result

    def filter_events(self, experiment_id: str, *, run_id: str | None, event_type: str | None, from_time: str | None,
                      to_time: str | None, limit: int, offset: int) -> dict:
        clauses, values = ["experiment_id=?"], [experiment_id]
        for column, operator, value in (("run_id", "=", run_id), ("type", "=", event_type), ("timestamp", ">=", from_time), ("timestamp", "<=", to_time)):
            if value is not None:
                clauses.append(f"epoch_us({column}){operator}epoch_us(?)" if column == "timestamp" else f"{column}{operator}?")
                values.append(value)
        where = " AND ".join(clauses)
        with self.connection() as connection:
            count = connection.execute(f"SELECT count(*) FROM events WHERE {where}", values).fetchone()[0]
            rows = connection.execute(f"SELECT payload FROM events WHERE {where} ORDER BY sequence LIMIT ? OFFSET ?", [*values, limit, offset])
            return {"events": [json.loads(row["payload"]) for row in rows], "total": count, "limit": limit, "offset": offset}


def open_store(database_url: str):
    if database_url.startswith(("postgresql://", "postgres://")):
        from .postgres import PostgresStore
        return PostgresStore(database_url)
    return Store(database_url)
