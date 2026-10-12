import pytest
from fastapi.testclient import TestClient

from parallax_lab.main import create_app


def test_api_token_protects_reads_writes_exports_and_docs(tmp_path, monkeypatch):
    token = "test-only-token-" + "a" * 32
    monkeypatch.setenv("PARALLAX_API_TOKEN", token)
    with TestClient(create_app(f"sqlite:///{tmp_path / 'secured.db'}", seed_demo=False)) as client:
        for path in ("/api/v1/health", "/api/v1/catalog", "/api/v1/experiments", "/docs", "/openapi.json"):
            assert client.get(path).status_code == 401
            assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.post("/api/v1/experiments", json={"bars": 60}).status_code == 401
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post("/api/v1/experiments", json={"bars": 60}, headers=headers)
        assert created.status_code == 201
        path = f"/api/v1/experiments/{created.json()['id']}"
        for suffix in ("", "/events", "/export"):
            assert client.get(path + suffix).status_code == 401
            response = client.get(path + suffix, headers=headers)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert token not in response.text


@pytest.mark.parametrize("url,token", [
    ("sqlite:///unused.db", "x" * 32),
    ("postgresql://unused", ""),
    ("postgresql://unused", "short"),
])
def test_hosted_api_fails_closed_without_durable_storage_and_auth(monkeypatch, url, token):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("PARALLAX_API_TOKEN", token)
    with pytest.raises(RuntimeError, match="Hosted API requires"):
        with TestClient(create_app(url, seed_demo=False)):
            pass


def test_large_export_is_streamed_without_content_length(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'large.db'}", seed_demo=False)) as client:
        response = client.post("/api/v1/experiments", json={"bars": 1440})
        assert response.status_code == 201
        assert "content-length" not in response.headers
        detail = response.json()
        exported = client.get(f"/api/v1/experiments/{detail['id']}/export")
        assert len(exported.content) > 4_500_000
        assert "content-length" not in exported.headers
        assert exported.json() == detail


def test_new_workspace_is_empty_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("PARALLAX_SEED_DEMO", raising=False)
    monkeypatch.delenv("PATRICK_SEED_DEMO", raising=False)
    url = f"sqlite:///{tmp_path / 'empty.db'}"
    for _ in range(2):
        with TestClient(create_app(url)) as client:
            assert client.get("/api/v1/experiments").json() == {"experiments": []}


@pytest.mark.parametrize("override", [None, True])
def test_hosted_workspace_never_seeds_demo_data(tmp_path, monkeypatch, override):
    from parallax_lab.storage import open_store
    # Real store, but isolate this startup policy test from external Postgres.
    isolated = open_store(f"sqlite:///{tmp_path / 'hosted.db'}")
    monkeypatch.setattr("parallax_lab.main.open_store", lambda _url: isolated)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("PARALLAX_API_TOKEN", "x" * 32)
    monkeypatch.setenv("PARALLAX_SEED_DEMO", "1")
    with TestClient(create_app("postgresql://test-only", seed_demo=override)) as client:
        result = client.get("/api/v1/experiments", headers={"Authorization": f"Bearer {'x' * 32}"})
        assert result.json() == {"experiments": []}
