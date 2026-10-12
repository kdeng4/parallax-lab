import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from parallax_lab.engine import run_experiment
from parallax_lab.main import create_app
from parallax_lab.schemas import ExperimentInput
from parallax_lab.storage import Store


@pytest.fixture
def database_url(tmp_path):
    return f"sqlite:///{tmp_path / 'research.db'}"


@pytest.fixture
def client(database_url):
    with TestClient(create_app(database_url)) as client:
        yield client


def test_health_catalog_and_empty_list(client):
    assert client.get("/openapi.json").json()["info"]["title"] == "Parallax Lab · paper-trading research"
    assert client.get("/api/v1/health").json() == {"status": "ok", "mode": "paper", "storage": "sqlite"}
    catalog = client.get("/api/v1/catalog").json()
    assert {m["id"] for m in catalog["models"]} == {"momentum", "mean-reversion", "buy-and-hold"}
    assert all(m["provider"] == "Local baseline" for m in catalog["models"])
    assert len(catalog["strategies"]) == 3 and catalog["data_source"] == "synthetic"
    assert client.get("/api/v1/experiments").json() == {"experiments": []}


def test_create_persist_export_and_restart(client, database_url):
    response = client.post("/api/v1/experiments", json={"name": "First study", "bars": 60})
    assert response.status_code == 201
    detail = response.json()
    assert detail["participants"] == 3 and detail["name"] == "First study"
    endpoint = f"/api/v1/experiments/{detail['id']}"
    assert client.get(endpoint).json() == detail
    export = client.get(endpoint + "/export")
    assert export.headers["content-disposition"] == f'attachment; filename="parallax-lab-{detail["id"]}.json"'
    assert export.json() == detail
    result_only = client.app.state.store.get(detail["id"], include_events=False)
    assert "events" not in result_only
    assert result_only["runs"] == detail["runs"]
    assert len(client.app.state.store.list_experiments(limit=1)) == 1
    metadata = export.json()["metadata"]
    assert metadata["dataset"]["hash"] == detail["data_hash"]
    assert metadata["dataset"]["generator"] == "parallax-lab-v1"
    assert metadata["strategies"][0]["markdown"].startswith("# ")
    assert metadata["execution"]["fill"] == "next_bar_open"
    with TestClient(create_app(database_url)) as reopened:
        assert reopened.get(endpoint).json() == detail
        assert reopened.get("/api/v1/experiments").json()["experiments"][0]["id"] == detail["id"]


def test_database_configuration_prefers_new_name_and_preserves_existing_local_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("PARALLAX_DATABASE_URL", "PATRICK_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    legacy = tmp_path / ".data" / "patrick.db"
    legacy.parent.mkdir()
    legacy.touch()
    with TestClient(create_app()) as old_client:
        assert old_client.app.state.store.path == legacy

    legacy.unlink()
    current = tmp_path / ".data" / "parallax-lab.db"
    with TestClient(create_app()) as fresh_client:
        assert fresh_client.app.state.store.path == current

    monkeypatch.setenv("PATRICK_DATABASE_URL", f"sqlite:///{legacy}")
    monkeypatch.setenv("PARALLAX_DATABASE_URL", f"sqlite:///{current}")
    with TestClient(create_app()) as new_client:
        assert new_client.app.state.store.path == current


@pytest.mark.parametrize("change", [
    {"model_ids": ["momentum"]}, {"model_ids": ["momentum", "momentum"]},
    {"model_ids": ["openai", "momentum"]}, {"strategy_ids": ["balanced", "responsive"]},
    {"comparison": "strategies"}, {"comparison": "anything"}, {"bars": 59}, {"bars": 1441},
    {"bars": "180"}, {"seed": -1}, {"seed": True}, {"symbol": "UNKNOWN"},
    {"initial_cash": 99}, {"initial_cash": 100_000_001}, {"name": "  "}, {"name": "a" * 101},
    {"api_key": "never-accepted"}, {"strategy_ids": ["balanced", "balanced"]},
])
def test_invalid_inputs_leave_no_experiment(client, change):
    response = client.post("/api/v1/experiments", json=change)
    assert response.status_code == 422, response.text
    assert client.get("/api/v1/experiments").json() == {"experiments": []}


def test_nan_cash_rejected(client):
    response = client.post("/api/v1/experiments", content='{"initial_cash":"NaN"}', headers={"content-type": "application/json"})
    assert response.status_code == 422


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonstandard_nonfinite_json_has_useful_422(client, value):
    response = client.post("/api/v1/experiments", content='{"initial_cash":' + value + '}', headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "initial_cash"]


def test_filtered_events_pagination_time_zones_and_invalid_bounds(client):
    detail = client.post("/api/v1/experiments", json={"bars": 60}).json()
    endpoint = f"/api/v1/experiments/{detail['id']}/events"
    run_id = detail["runs"][0]["id"]
    first = client.get(endpoint, params={"run_id": run_id, "type": "decision", "limit": 5}).json()
    assert first["total"] == 60 and len(first["events"]) == 5
    assert all(e["run_id"] == run_id and e["type"] == "decision" for e in first["events"])
    next_page = client.get(endpoint, params={"run_id": run_id, "type": "decision", "limit": 5, "offset": 5}).json()
    assert first["events"][-1]["sequence"] < next_page["events"][0]["sequence"]
    same_instant = {"from_time": "2026-01-05T09:30:59-05:00", "to_time": "2026-01-05T14:30:59Z", "type": "decision"}
    assert client.get(endpoint, params=same_instant).json()["total"] == 3
    fractional = {"from_time": "2026-01-05T14:30:59.001Z", "to_time": "2026-01-05T14:31:58.999Z", "type": "decision"}
    assert client.get(endpoint, params=fractional).json()["total"] == 0
    submillisecond = {"from_time": "2026-01-05T14:30:59.000001Z", "to_time": "2026-01-05T14:30:59.000499Z"}
    assert client.get(endpoint, params=submillisecond).json()["total"] == 0
    for params in [{"limit": 0}, {"limit": 2001}, {"offset": -1}, {"type": "garbage"},
                   {"from_time": "2026-01-05T14:30:00"}, {"from_time": "2026-01-06T00:00:00Z", "to_time": "2026-01-05T00:00:00Z"}]:
        assert client.get(endpoint, params=params).status_code == 422


@pytest.mark.parametrize("suffix", ["", "/events", "/export"])
def test_missing_resource_404(client, suffix):
    assert client.get(f"/api/v1/experiments/{uuid4()}{suffix}").status_code == 404


def test_audit_append_only_and_atomic_rollback(database_url):
    store = Store(database_url)
    store.initialize()
    good = run_experiment(ExperimentInput(bars=60))
    store.save(good)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with store.connection() as connection:
            connection.execute("DELETE FROM events WHERE experiment_id=?", (good["id"],))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with store.connection() as connection:
            connection.execute("UPDATE events SET type='fill' WHERE experiment_id=?", (good["id"],))
    broken = run_experiment(ExperimentInput(bars=60))
    broken["events"][1]["id"] = broken["events"][0]["id"]
    with pytest.raises(sqlite3.IntegrityError):
        store.save(broken)
    assert not store.has(broken["id"])
    assert store.get(good["id"]) == good
