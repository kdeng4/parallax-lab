import json

import httpx
import pytest
from fastapi.testclient import TestClient

from parallax_lab.context_feeds import ContextFeeds
from parallax_lab.main import create_app
from parallax_lab.market_feeds import MarketService
from parallax_lab.schemas import ExperimentInput, WatchlistInput
from parallax_lab.storage import Store
from test_market_feeds import NOW, prices


def test_owner_preferences_persist_without_provider_io_or_public_leak(tmp_path):
    url = f"sqlite:///{tmp_path / 'preferences.db'}"
    with TestClient(create_app(url)) as client:
        response = client.post('/api/v1/market/watchlist', json={'symbols': [' tsla ', 'amd', 'BRK.B']})
        assert response.status_code == 200
        assert response.json() == {'symbols': ['TSLA', 'AMD', 'BRK-B'], 'max_symbols': 10}
        assert client.get('/api/v1/catalog').json()['symbols'] == ['TSLA', 'AMD', 'BRK-B']
        assert 'TSLA' not in client.get('/api/v1/public/dashboard').text
        with client.app.state.store.connection() as db:
            rows = db.execute('SELECT * FROM market_state').fetchall()
        assert len(rows) == 1 and rows[0]['key'] == 'settings:watchlist'
    with TestClient(create_app(url)) as client:
        assert client.get('/api/v1/market/watchlist').json()['symbols'] == ['TSLA', 'AMD', 'BRK-B']


@pytest.mark.parametrize('symbols', [[], ['AAPL', 'aapl'], ['BRK.B', 'BRK-B'], ['../../secrets'],
                                    ['https://evil.example'], ['AAPL?token=secret'], [42], [''],
                                    ['ABCDEFGHIJKLMNO'], [f'A{i}' for i in range(11)]])
def test_invalid_preferences_are_rejected_atomically(tmp_path, symbols):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'invalid.db'}")) as client:
        original = client.get('/api/v1/market/watchlist').json()
        assert client.post('/api/v1/market/watchlist', json={'symbols': symbols}).status_code == 422
        assert client.get('/api/v1/market/watchlist').json() == original


def test_custom_stock_and_news_use_saved_tickers_and_existing_shared_quota(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'market.db'}")
    store.initialize()
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[] if 'news' in request.url.path else prices())
    market = MarketService(store, network=True, token='private-test-token', clock=lambda: NOW,
                           persistent_tiingo=False, client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    market.watchlist.replace(WatchlistInput(symbols=['TSLA', 'BRK.B']))
    assert market.stock('brk.b')['symbol'] == 'BRK-B'
    assert calls[-1].url.path.endswith('/BRK-B/prices')
    assert market.stock('TSLA')['status'] != 'key_missing'
    ContextFeeds(market).overview()
    assert calls[-1].url.params['tickers'] == 'TSLA,BRK-B'
    assert len(calls) == 3
    with store.connection() as db:
        rows = [dict(row) for row in db.execute('SELECT * FROM market_state').fetchall()]
    assert len(json.loads(next(row['value'] for row in rows if row['key'] == 'provider:tiingo'))['attempts']) == 3
    assert all('candles' not in row['value'] for row in rows)
    assert ExperimentInput(symbol='tsla').symbol == 'TSLA'


def test_missing_ticker_does_not_pause_other_assets_or_refetch_immediately(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'missing.db'}")
    store.initialize()
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(404) if '/UNKNOWN/' in request.url.path else httpx.Response(200, json=prices())
    market = MarketService(store, network=True, token='private-test-token', clock=lambda: NOW,
                           client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    assert market.stock('UNKNOWN')['status'] == 'not_found'
    assert market.stock('UNKNOWN')['status'] == 'not_found'
    assert market.stock('TSLA')['status'] != 'not_found'
    assert len(calls) == 2
