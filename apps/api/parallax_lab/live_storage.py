"""Mutable paper accounts with atomic, append-only snapshot and event records."""

import json
from contextlib import contextmanager


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


class LiveStore:
    def __init__(self, store):
        self.store = store
        self.p = "%s" if store.dialect == "postgresql" else "?"

    def encode(self, value):
        if self.store.dialect == "postgresql":
            from psycopg.types.json import Jsonb
            return Jsonb(value)
        return json.dumps(value, allow_nan=False, separators=(",", ":"))

    @contextmanager
    def locked(self):
        with self.store.connection() as db:
            if self.store.dialect == "postgresql":
                db.execute("SELECT pg_advisory_xact_lock(719230116)")
            else:
                db.execute("BEGIN IMMEDIATE")
            yield db

    def read(self, db, study_id):
        row = db.execute(f"SELECT payload FROM live_studies WHERE id={self.p}", (study_id,)).fetchone()
        return decode(row["payload"]) if row else None

    def write(self, db, study):
        db.execute(f"UPDATE live_studies SET status={self.p},payload={self.p} WHERE id={self.p}",
                   (study['status'], self.encode(study), study['id']))

    def create(self, study, snapshot):
        with self.locked() as db:
            active = db.execute("SELECT count(*) AS total FROM live_studies WHERE status='active'").fetchone()['total']
            if active >= 2:
                raise ValueError("At most two ongoing studies may be active; pause one before starting another")
            db.execute(f"INSERT INTO live_studies (id,created_at,status,payload) VALUES ({','.join([self.p]*4)})",
                       (study['id'], study['created_at'], study['status'], self.encode(study)))
            self.snapshot(db, study['id'], snapshot)
            self.point(db, study['id'], {'id': study['id'] + ':start', 'timestamp': study['started_at'],
                                       'returns': {account['id']: 0.0 for account in study['accounts']}, 'benchmark_pct': 0.0})

    def snapshot(self, db, study_id, snapshot):
        db.execute(f"INSERT INTO live_snapshots (id,study_id,created_at,payload) VALUES ({','.join([self.p]*4)})",
                   (snapshot['id'], study_id, snapshot['captured_at'], self.encode(snapshot)))

    def point(self, db, study_id, point):
        db.execute(f"INSERT INTO live_points (id,study_id,timestamp,payload) VALUES ({','.join([self.p]*4)})",
                   (point['id'], study_id, point['timestamp'], self.encode(point)))

    def event(self, db, study_id, event):
        db.execute(f"INSERT INTO live_events (id,study_id,timestamp,payload) VALUES ({','.join([self.p]*4)})",
                   (event['id'], study_id, event['timestamp'], self.encode(event)))

    def list(self):
        with self.store.connection() as db:
            rows = db.execute("SELECT payload FROM live_studies ORDER BY created_at DESC,id DESC LIMIT 50").fetchall()
        return [self.summary(decode(row['payload'])) for row in rows]

    @staticmethod
    def summary(study):
        return {key: study[key] for key in ('id','name','status','started_at','created_at','last_tick_at','last_error','config','accounts')}

    def get(self, study_id):
        with self.store.connection() as db:
            study = self.read(db, study_id)
            if not study:
                return None
            study['points'] = [decode(row['payload']) for row in db.execute(
                f"SELECT payload FROM (SELECT timestamp,id,payload FROM live_points WHERE study_id={self.p} ORDER BY timestamp DESC,id DESC LIMIT 9999) recent ORDER BY timestamp,id", (study_id,))]
            first = db.execute(f"SELECT payload FROM live_points WHERE study_id={self.p} ORDER BY timestamp,id LIMIT 1", (study_id,)).fetchone()
            if first:
                first = decode(first['payload'])
                if not study['points'] or study['points'][0]['id'] != first['id']:
                    study['points'].insert(0, first)
            study['events'] = [decode(row['payload']) for row in db.execute(
                f"SELECT payload FROM live_events WHERE study_id={self.p} ORDER BY timestamp DESC,id DESC LIMIT 200", (study_id,))]
            return study

    def snapshot_detail(self, study_id, snapshot_id):
        with self.store.connection() as db:
            row = db.execute(f"SELECT payload FROM live_snapshots WHERE study_id={self.p} AND id={self.p}",
                             (study_id, snapshot_id)).fetchone()
        return decode(row['payload']) if row else None

    def plan(self):
        with self.store.connection() as db:
            rows = db.execute("SELECT payload FROM live_studies WHERE status='active' ORDER BY id").fetchall()
        return [{"id": study['id'], **{key: study['config'][key] for key in ('timezone','window_start','window_end')}}
                for study in (decode(row['payload']) for row in rows)]
