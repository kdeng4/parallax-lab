import json
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from parallax_lab.context_feeds import ContextFeeds, earnings, filings, link, news, releases
from parallax_lab.engine import run_experiment
from parallax_lab.market import Candle, MarketDataset
from parallax_lab.market_feeds import FeedError, MarketService
from parallax_lab.main import create_app
from parallax_lab.public_dashboard import attach_benchmark, public_dashboard
from parallax_lab.schemas import ExperimentInput
from parallax_lab.storage import Store
from test_market_feeds import NOW, prices


@pytest.fixture
def store(tmp_path):
    store = Store(f'sqlite:///{tmp_path / "context.db"}')
    store.initialize()
    return store


def test_transient_tiingo_keeps_budgets_but_never_content_or_replay(store):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=prices())
    market = MarketService(store, network=True, token='secret', clock=lambda: NOW, persistent_tiingo=False,
                           client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    assert market.stock('SPY')['data']['close'] == 180
    with store.connection() as db:
        entries = {r['key']: json.loads(r['value']) for r in db.execute('SELECT * FROM market_state')}
    assert 'data' not in entries['cache:tiingo:SPY']
    assert entries['provider:tiingo']['attempts'] == [NOW]
    assert 'secret' not in str(entries)
    with pytest.raises(FeedError, match='storage_license_required'):
        market.replay('SPY', 60)
    assert len(calls) == 1


def test_obsolete_content_invalidation_preserves_provider_quota(store):
    market = MarketService(store)
    with market.cache.locked() as db:
        market.cache.write(db, 'cache:tiingo:SPY', {'data': 'restricted'})
        market.cache.write(db, 'provider:tiingo', {'attempts': [NOW]})
        market.cache.write(db, 'cache:boc', {'data': [1]})
    market.cache.discard_tiingo_content()
    with market.cache.locked() as db:
        assert market.cache.read(db, 'cache:tiingo:SPY') == {}
        assert market.cache.read(db, 'provider:tiingo')['attempts'] == [NOW]
        assert market.cache.read(db, 'cache:boc')['data'] == [1]


def test_public_response_empty_without_licence_and_never_shows_synthetic(store, monkeypatch):
    detail = run_experiment(ExperimentInput(bars=60, name='private name'))
    detail['metadata']['public_performance_approved'] = True
    store.save(detail)
    for setting in ('0', '1'):
        monkeypatch.setenv('PARALLAX_PUBLIC_PERFORMANCE_APPROVED', setting)
        result = public_dashboard(store)
        assert result['series'] == result['activities'] == []
        assert result['study'] is None
        assert all(set(agent) == {'id', 'name'} for agent in result['agents'])


def test_public_projection_and_benchmark_hide_settings_prices_and_quantities(store, monkeypatch):
    detail = run_experiment(ExperimentInput(bars=60, name='private strategy label'))
    detail['data_source'] = 'licensed-test-transport'
    detail['metadata']['public_performance_approved'] = True
    candles = tuple(Candle(**c) for c in detail['candles'])
    attach_benchmark(detail, MarketDataset(candles, 'licensed-test-transport', '1m', {}))
    store.save(detail)
    monkeypatch.setenv('PARALLAX_PUBLIC_PERFORMANCE_APPROVED', '1')
    result = public_dashboard(store)
    assert len(result['series']) == 4
    assert all(series['points'][0]['value'] == 100 for series in result['series'])
    assert result['series'][-1]['benchmark'] is True
    assert len(result['series'][-1]['points']) == 61
    serialized = json.dumps(result)
    for forbidden in ('private strategy label', 'initial_cash', 'strategy_name', 'quantity', 'price', 'candles', 'metadata', 'settings', 'target_allocation'):
        assert forbidden not in serialized
    assert all(set(a) == {'id', 'agent', 'action', 'symbol', 'session_date'} for a in result['activities'])
    # An immutable run not approved at creation never becomes public through an env change.
    detail['metadata']['public_performance_approved'] = False
    class NoApproval:
        def list_experiments(self): return [detail]
        def get(self, _): return detail
    assert public_dashboard(NoApproval())['series'] == []


def test_no_benchmark_interpolation():
    detail = run_experiment(ExperimentInput(bars=60))
    candle = Candle('2020-01-01T00:00:00Z', 1, 1, 1, 1, 1)
    attach_benchmark(detail, MarketDataset((candle,), 'test', '1d', {}))
    assert 'benchmark' not in detail


def test_provider_parsers_preserve_dates_and_reject_unsafe_data():
    today = date(2026, 10, 12)
    row = {'url': 'https://example.com/article', 'title': '<b>Company news</b>', 'publishedDate': '2026-10-12T13:00:00Z', 'tickers': ['aapl']}
    item = news([row], 'Tiingo', today)[0]
    assert item['symbols'] == ['AAPL'] and item['title'] == 'Company news'
    assert news([{**row, 'publishedDate': '2026-10-13T00:00:00Z'}], 'Tiingo', today) == []
    for url in ('javascript:alert(1)', 'https://user:password@example.com/', '/private'):
        with pytest.raises(ValueError): link(url)
    assert len(earnings('symbol,name,reportDate\nAAPL,Apple,2026-10-20\nUNKNOWN,Other,2026-10-20', today)) == 1
    with pytest.raises(FeedError): earnings('{"Information":"quota"}', today)
    with pytest.raises(ValueError): earnings('bad,columns\n1,2', today)
    assert releases({'release_dates': [{'date': '2026-10-20', 'release_id': 10, 'release_name': 'Release'}]}, today)[0]['date'] == '2026-10-20'
    payload = {'filings': {'recent': {'form': ['8-K'], 'filingDate': ['2026-10-09'], 'accessionNumber': ['0000320193-26-000001'], 'primaryDocument': ['report.htm']}}}
    assert '/320193/000032019326000001/report.htm' in filings(payload, 'AAPL', '0000320193', today)[0]['url']


def test_missing_credentials_do_not_consume_requests(store):
    market = MarketService(store, network=True, token='', clock=lambda: NOW,
                           client_factory=lambda: pytest.fail('No HTTP request expected'))
    result = ContextFeeds(market).overview()
    assert len(result['sources']) == 9
    assert all(source['status'] == 'key_missing' for source in result['sources'])
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM market_state').fetchone()[0] == 0


def test_news_429_honors_shared_budget_and_hides_secrets(store, monkeypatch):
    monkeypatch.setenv('MARKETAUX_API_KEY', 'must-stay-private')
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After': '3600'}, text='must-stay-private')
    market = MarketService(store, network=True, token='', clock=lambda: NOW,
                           client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    for _ in range(2):
        result = ContextFeeds(market).overview()
        assert result['sources'][1]['status'] == 'rate_limited'
        assert 'must-stay-private' not in str(result)
    assert len(calls) == 1


def test_private_feeds_cache_valid_empty_results(store, monkeypatch):
    monkeypatch.setenv('MARKETAUX_API_KEY', 'private')
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'data': []})
    market = MarketService(store, network=True, token='', clock=lambda: NOW,
                           client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    for _ in range(2):
        assert ContextFeeds(market).overview()['sources'][1]['status'] == 'ok'
    assert len(calls) == 1


def test_private_routes_and_storage_gate_fail_closed(tmp_path, monkeypatch):
    monkeypatch.delenv('PARALLAX_MARKET_SOURCE')
    monkeypatch.setenv('PARALLAX_TIINGO_STORAGE_APPROVED', '0')
    monkeypatch.setenv('PARALLAX_API_TOKEN', 'private-service-token')
    with TestClient(create_app(f'sqlite:///{tmp_path / "api.db"}', seed_demo=False)) as client:
        for path in ('public/dashboard', 'context/overview', 'catalog'):
            assert client.get('/api/v1/' + path).status_code == 401
        client.headers['Authorization'] = 'Bearer private-service-token'
        assert client.get('/api/v1/public/dashboard').json()['series'] == []
        assert len(client.get('/api/v1/context/overview').json()['sources']) == 9
        assert client.get('/api/v1/catalog').json()['replay_available'] is False
        response = client.post('/api/v1/experiments', json={'bars': 60})
        assert response.status_code == 503 and 'licence' in response.json()['detail']
        assert client.get('/api/v1/experiments').json()['experiments'] == []


@pytest.mark.parametrize('benchmark_available', [True, False])
def test_daily_experiment_benchmark_aligns_sessions_and_preserves_missing_data(tmp_path, monkeypatch, benchmark_available):
    monkeypatch.delenv('PARALLAX_MARKET_SOURCE')
    monkeypatch.setenv('PARALLAX_PUBLIC_PERFORMANCE_APPROVED', '1')
    days = [(date(2026, 7, 1) + timedelta(days=i)).isoformat() for i in range(60)]
    candles = tuple(Candle(f'{day}T00:00:00Z', 100, 103, 99, 102, 1000) for day in days)
    dataset = MarketDataset(candles, 'licensed-test-transport', '1d', {})
    def replay(symbol, bars):
        if symbol == 'SPY' and not benchmark_available:
            raise FeedError('provider_unavailable')
        return dataset
    with TestClient(create_app(f'sqlite:///{tmp_path / "api.db"}', seed_demo=False)) as client:
        monkeypatch.setattr(client.app.state.market, 'replay', replay)
        response = client.post('/api/v1/experiments', json={'bars': 60, 'symbol': 'AAPL'})
        assert response.status_code == 201
        detail = response.json()
        assert detail['metadata']['public_performance_approved'] is True
        assert ('benchmark' in detail) is benchmark_available
        result = client.get('/api/v1/public/dashboard').json()
        assert len(result['series']) == (4 if benchmark_available else 3)
        if benchmark_available:
            points = result['series'][-1]['points']
            assert points[0]['value'] == 100 and points[1]['value'] == 102
            assert [p['date'] for p in points] == [p['date'] for p in result['series'][0]['points']]


def test_malformed_source_isolated_from_other_providers(store, monkeypatch):
    monkeypatch.setenv('PARALLAX_SEC_USER_AGENT', 'Test contact@example.com')
    monkeypatch.setenv('ALPHA_VANTAGE_API_KEY', 'test-private')
    requested = []
    def handler(request):
        requested.append(request)
        if request.url.host == 'www.alphavantage.co':
            assert request.url.params['symbol'] in ('AAPL', 'MSFT', 'NVDA')
            return httpx.Response(200, text='symbol,name,reportDate\nAAPL,Apple,2026-10-20')
        return httpx.Response(200, json={'filings': {'recent': {'form': ['8-K'], 'filingDate': []}}})
    market = MarketService(store, network=True, token='', clock=lambda: NOW,
                           client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    result = ContextFeeds(market).overview()
    assert all(s['status'] == 'ok' for s in result['sources'] if s['id'].startswith('alphavantage:'))
    assert all(s['status'] != 'ok' for s in result['sources'] if s['id'].startswith('sec:'))
    assert len(requested) == 4  # First malformed SEC response activates provider-wide cooldown.
