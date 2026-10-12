import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from parallax_lab import cloud_replay
from parallax_lab.engine import run_experiment
from parallax_lab.main import create_app
from parallax_lab.schemas import ExperimentInput

KEY = "owner-test-key-not-real"
NOW = 1_790_000_000
MODELS = ["openai:gpt-6-luna", "openai:gpt-6.1-sol", "openai:gpt-6-astra"]


def result():
    return {"id": "resp_test", "model": "verified-response-model", "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            "output": [{"type": "reasoning", "content": "never exported"},
                       {"type": "message", "content": [{"type": "output_text", "text": json.dumps(
                           {"target_allocation": 0.95, "confidence": 0.8, "summary": "Use the observed trend."})}]}]}


@pytest.fixture
def database_url(tmp_path):
    return f"sqlite:///{tmp_path / 'cloud.db'}"


def inject(client, handler):
    client.app.state.openai_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_catalog_exposes_configured_models_but_never_credentials(database_url, monkeypatch):
    with TestClient(create_app(database_url)) as client:
        assert len(client.get('/api/v1/catalog').json()['models']) == 3
        monkeypatch.setenv('OPENAI_API_KEY', KEY)
        catalog = client.get('/api/v1/catalog').json()
        assert len(catalog['models']) == 6 and catalog['openai']['configured']
        assert KEY not in json.dumps(catalog)
        monkeypatch.setenv('PARALLAX_OPENAI_MODELS', ' gpt-6-luna,unsupported ')
        assert len(client.get('/api/v1/catalog').json()['models']) == 4
        monkeypatch.setenv('PARALLAX_OPENAI_NETWORK', '0')
        assert len(client.get('/api/v1/catalog').json()['models']) == 3


def test_cloud_replay_matches_observed_prefix_schedule_risk_caps_and_audit(database_url, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', KEY)
    calls = []
    def handler(request):
        body = json.loads(request.content)
        assert request.url == 'https://api.openai.com/v1/responses'
        assert body['store'] is False and body['max_output_tokens'] == 1024
        assert body['reasoning'] == {'effort': 'low'}
        calls.append(json.loads(body['input'][1]['content']))
        return httpx.Response(200, json=result())
    with TestClient(create_app(database_url)) as client:
        inject(client, handler)
        response = client.post('/api/v1/experiments', json={'bars': 60, 'model_ids': [MODELS[0], 'buy-and-hold']})
        assert response.status_code == 201, response.text
        detail = response.json()
        checkpoints = detail['metadata']['execution']['decision_bar_indices']
        assert checkpoints == [12, 58]
        assert [len(call['candles']) for call in calls] == [13, 59]
        assert calls[0]['current_allocation'] == 0 and calls[1]['current_allocation'] > 0
        for call, index in zip(calls, checkpoints):
            assert call['candles'][-1]['timestamp'] == detail['runs'][0]['equity_curve'][index + 1]['timestamp']
            assert call['max_allocation'] == .7
        decisions = [e for e in detail['events'] if e['type'] == 'decision']
        assert len(decisions) == 4 and {e['details']['bar_index'] for e in decisions} == set(checkpoints)
        cloud = next(run for run in detail['runs'] if run['provider'] == 'OpenAI')
        assert cloud['model_name'] == 'GPT-6 Luna' and len(cloud['equity_curve']) == 61
        remote_events = [e for e in decisions if e['run_id'] == cloud['id']]
        assert all(e['details']['target_allocation'] == .7 for e in remote_events)
        assert remote_events[0]['details']['observable_inputs']['usage']['total_tokens'] == 120
        assert remote_events[0]['details']['observable_inputs']['response_model'] == 'verified-response-model'
        fills = [e for e in detail['events'] if e['type'] == 'fill']
        assert all(e['details']['execution_bar_index'] == e['details']['observed_bar_index'] + 1 for e in fills)
        assert detail['metadata']['openai']['calls_attempted'] == 2
        exported = client.get(f"/api/v1/experiments/{detail['id']}/export").json()
        assert exported == detail and KEY not in json.dumps(exported) and 'never exported' not in json.dumps(exported)


@pytest.mark.parametrize('change,status', [
    ({'model_ids': ['openai:unapproved', 'momentum']}, 422),
    ({'model_ids': MODELS, 'decision_checkpoints': 3}, 422),
    ({'bars': 253}, 422),
    ({'decision_checkpoints': 4}, 422),
])
def test_invalid_cloud_requests_fail_before_billable_io(database_url, monkeypatch, change, status):
    monkeypatch.setenv('OPENAI_API_KEY', KEY)
    with TestClient(create_app(database_url)) as client:
        inject(client, lambda _: pytest.fail('Rejected input must not make a provider request'))
        payload = {'bars': 60, 'model_ids': [MODELS[0], 'momentum'], **change}
        assert client.post('/api/v1/experiments', json=payload).status_code == status
        assert client.get('/api/v1/experiments').json()['experiments'] == []


def test_unconfigured_model_and_local_entry_point_never_use_a_fake_baseline(database_url):
    request = {'bars': 60, 'model_ids': [MODELS[0], 'momentum']}
    with TestClient(create_app(database_url)) as client:
        assert client.post('/api/v1/experiments', json=request).status_code == 503
    with pytest.raises(ValueError, match='configured decision provider'):
        run_experiment(ExperimentInput(**request))


def test_cloud_quota_persists_across_restarts_and_rolling_windows(database_url, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', KEY)
    clock = [NOW]
    monkeypatch.setattr(cloud_replay, 'time', SimpleNamespace(time=lambda: clock[0]))
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=result())
    payload = {'bars': 60, 'model_ids': MODELS, 'decision_checkpoints': 2}
    for study in range(4):
        with TestClient(create_app(database_url)) as client:
            inject(client, handler)
            assert client.post('/api/v1/experiments', json=payload).status_code == 201
            assert client.post('/api/v1/experiments', json=payload).status_code == 429
        clock[0] += 61
    assert len(calls) == 24
    with TestClient(create_app(database_url)) as client:
        inject(client, handler)
        assert client.post('/api/v1/experiments', json=payload).status_code == 429
        assert len(client.get('/api/v1/experiments').json()['experiments']) == 4
        clock[0] += 86_400
        assert client.post('/api/v1/experiments', json=payload).status_code == 201


@pytest.mark.parametrize('failure', ['429', '401', 'incomplete', 'transport', 'decision_timeout', 'replay_timeout'])
def test_provider_failure_saves_no_partial_experiment_and_consumes_quota(database_url, monkeypatch, failure):
    monkeypatch.setenv('OPENAI_API_KEY', KEY)
    monkeypatch.setattr(cloud_replay, 'time', SimpleNamespace(time=lambda: NOW))
    if failure == 'decision_timeout':
        monkeypatch.setattr(cloud_replay, 'OPENAI_TIMEOUT', .001)
    if failure == 'replay_timeout':
        monkeypatch.setattr(cloud_replay, 'OPENAI_REPLAY_TIMEOUT', .001)
    calls = []
    async def handler(request):
        calls.append(request)
        if failure in ('decision_timeout', 'replay_timeout'):
            await asyncio.sleep(.01)
        if failure == 'transport':
            raise httpx.ReadTimeout(KEY, request=request)
        if failure in ('429', '401'):
            return httpx.Response(int(failure), headers={'Retry-After': '3600'}, text=KEY)
        return httpx.Response(200, json={**result(), 'status': 'incomplete'})
    with TestClient(create_app(database_url)) as client:
        inject(client, handler)
        payload = {'bars': 60, 'model_ids': [MODELS[0], 'momentum']}
        response = client.post('/api/v1/experiments', json=payload)
        assert response.status_code == 503 and KEY not in response.text
        assert client.get('/api/v1/experiments').json()['experiments'] == []
        assert client.post('/api/v1/experiments', json=payload).status_code == 429
        assert len(calls) == 1
        with client.app.state.store.connection() as db:
            state = client.app.state.market.cache.read(db, 'provider:openai')
        assert state['attempts'] == [NOW] and state['blocked_until'] >= NOW + 900
        if failure == '429':
            assert state['blocked_until'] >= NOW + 3600


def test_storage_licence_gate_precedes_cloud_calls(database_url, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', KEY)
    monkeypatch.delenv('PARALLAX_MARKET_SOURCE')
    monkeypatch.setenv('PARALLAX_TIINGO_STORAGE_APPROVED', '0')
    with TestClient(create_app(database_url)) as client:
        inject(client, lambda _: pytest.fail('No licensed data, no billable OpenAI call'))
        response = client.post('/api/v1/experiments', json={'bars': 60, 'model_ids': [MODELS[0], 'momentum']})
        assert response.status_code == 503 and 'licence' in response.text
