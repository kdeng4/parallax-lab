"""Run against a disposable PostgreSQL database/Neon test branch, never production."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from parallax_lab.engine import run_experiment
from parallax_lab.main import create_app
from parallax_lab.migrate import migrate
from parallax_lab.postgres import PostgresStore
from parallax_lab.schemas import ExperimentInput
from parallax_lab.storage import open_store


@pytest.fixture(scope="module")
def database_url():
    url = os.getenv("PARALLAX_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set PARALLAX_TEST_DATABASE_URL to an isolated PostgreSQL test database")
    migrate(url)
    return url


def test_migration_repeat_and_store_factory(database_url):
    migrate(database_url)
    store = open_store(database_url)
    assert isinstance(store, PostgresStore)
    store.initialize()
    assert not store.has(str(uuid4()))
    assert store.get(str(uuid4())) is None


def test_postgres_roundtrip_restart_and_time_filters(database_url):
    with TestClient(create_app(database_url)) as client:
        assert client.get("/api/v1/health").json()["storage"] == "postgresql"
        response = client.post("/api/v1/experiments", json={"name": "PostgreSQL contract", "bars": 60})
        assert response.status_code == 201
        detail = response.json()
        endpoint = f"/api/v1/experiments/{detail['id']}"
        assert client.get(endpoint).json() == detail
        assert client.get(endpoint + "/export").json() == detail
        result_only = client.app.state.store.get(detail["id"], include_events=False)
        assert "events" not in result_only
        assert result_only["runs"] == detail["runs"]
        assert len(client.app.state.store.list_experiments(limit=1)) == 1
        params = {"type": "decision", "run_id": detail["runs"][0]["id"], "limit": 5, "offset": 5}
        page = client.get(endpoint + "/events", params=params).json()
        assert page["total"] == 60 and len(page["events"]) == 5
        assert all(e["type"] == "decision" and e["run_id"] == params["run_id"] for e in page["events"])
        instant = {"from_time": "2026-01-05T09:30:59-05:00", "to_time": "2026-01-05T14:30:59Z", "type": "decision"}
        assert client.get(endpoint + "/events", params=instant).json()["total"] == 3
        instant["from_time"] = "2026-01-05T14:30:59.000001Z"
        instant["to_time"] = "2026-01-05T14:30:59.000499Z"
        assert client.get(endpoint + "/events", params=instant).json()["total"] == 0
    with TestClient(create_app(database_url)) as restarted:
        assert restarted.get(endpoint).json() == detail
        assert detail["id"] in {e["id"] for e in restarted.get("/api/v1/experiments").json()["experiments"]}


def test_postgres_concurrent_saves_and_atomic_rollback(database_url):
    store = PostgresStore(database_url)
    records = [run_experiment(ExperimentInput(bars=60, seed=i)) for i in range(4)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(store.save, records))
    for detail in records:
        assert store.get(detail["id"]) == detail
    broken = run_experiment(ExperimentInput(bars=60))
    broken["events"][-1]["id"] = records[0]["events"][0]["id"]
    with pytest.raises(psycopg.IntegrityError):
        store.save(broken)
    assert not store.has(broken["id"])
    assert store.filter_events(broken["id"], run_id=None, event_type=None,
                               from_time=None, to_time=None, limit=10, offset=0)["total"] == 0


def test_postgres_records_reject_updates_and_deletes(database_url):
    store = PostgresStore(database_url)
    detail = run_experiment(ExperimentInput(bars=60))
    store.save(detail)
    for sql in ("UPDATE experiments SET summary='{}' WHERE id=%s", "DELETE FROM experiments WHERE id=%s",
                "UPDATE events SET type='fill' WHERE experiment_id=%s", "DELETE FROM events WHERE experiment_id=%s"):
        with pytest.raises(psycopg.IntegrityError, match="immutable"):
            with store.connection() as connection:
                connection.execute(sql, (detail["id"],))
    assert store.get(detail["id"]) == detail


def test_postgres_market_cache_serializes_workers_and_persists_budget(database_url):
    from parallax_lab.market_cache import MarketCache
    cache = MarketCache(PostgresStore(database_url))
    provider, key = str(uuid4()), str(uuid4())
    with ThreadPoolExecutor(max_workers=8) as executor:
        claims = list(executor.map(lambda _: cache.claim(key, provider, 1_790_000_000, ((3600, 1),)), range(8)))
    leases = [lease for _, lease in claims if lease]
    assert len(leases) == 1
    cache.finish(key, provider, leases[0], 1_790_000_001, data={"price": 123})
    restarted = MarketCache(PostgresStore(database_url))
    assert restarted.claim(key, provider, 1_790_000_010, ((3600, 1),))[0]["data"] == {"price": 123}
    assert restarted.claim(key + "-other", provider, 1_790_000_010, ((3600, 1),))[0]["error"] == "budget_exhausted"


def test_postgres_forward_accounts_snapshots_leases_and_atomic_rollback(database_url, monkeypatch):
    from datetime import UTC, datetime
    from parallax_lab.live_feeds import snapshot
    from parallax_lab.live_schemas import StudyInput
    from parallax_lab.live_service import LiveService
    from parallax_lab.market_feeds import MarketService
    clock = [datetime(2026, 10, 12, 14, tzinfo=UTC).timestamp()]
    store = PostgresStore(database_url)
    market = MarketService(store, network=True, token='test-transport-only', clock=lambda: clock[0], persistent_tiingo=True)
    live = LiveService(store, market)
    def quotes(symbols):
        return {symbol: {'price': 100, 'as_of': live.now().isoformat(), 'source': 'Isolated test transport'}
                for symbol in set(symbols) | {'SPY'}}
    monkeypatch.setattr(live.feeds, 'quotes', quotes)
    monkeypatch.setattr(live.feeds, 'window_snapshot', lambda symbols, since: snapshot('shared_window_input', live.now(),
        quotes=quotes(symbols), actions=[], news=[], events=[], news_sources=[{'name': 'Test transport', 'status': 'ok', 'fetched_at': live.now().isoformat()}]))
    study = live.create(StudyInput(name='Isolated PostgreSQL forward test', symbols=['AAPL', 'MSFT'],
                                  model_ids=['buy-and-hold'], strategy_ids=['balanced']))
    live.tick(study['id'])
    clock[0] += 301
    live.tick(study['id'])
    final = live.db.get(study['id'])
    assert len([item for item in final['events'] if item['type'] == 'fill']) == 2
    assert final['accounts'][0]['return_pct'] < 0
    assert live.db.snapshot_detail(study['id'], final['round']['snapshot_id'])['hash'] == final['round']['snapshot_hash']
    for table in ['live_snapshots', 'live_points', 'live_events']:
        for sql in [f"UPDATE {table} SET payload='{{}}'::jsonb WHERE study_id=%s", f'DELETE FROM {table} WHERE study_id=%s']:
            with pytest.raises(psycopg.IntegrityError, match='immutable'):
                with store.connection() as db:
                    db.execute(sql, (study['id'],))
    working = live._claim(study['id'])
    previous = live.db.get(study['id'])
    working['last_error'] = 'This write must roll back'
    with pytest.raises(psycopg.IntegrityError):
        live._save(working, snapshots=[working['round']['snapshot']])
    assert live.db.get(study['id']) == previous
    live.control(study['id'], 'pause')
    assert live.db.get(study['id'])['status'] == 'paused'
