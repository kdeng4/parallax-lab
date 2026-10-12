from datetime import UTC, datetime, timedelta

import httpx
import pytest

from parallax_lab.live_feeds import LiveFeeds, snapshot
from parallax_lab.market_feeds import FeedError, MarketService
from parallax_lab.storage import Store

NOW = datetime(2026, 10, 12, 14, tzinfo=UTC)


@pytest.fixture
def factory(tmp_path):
    def build(handler):
        store = Store(f"sqlite:///{tmp_path / 'feeds.db'}")
        store.initialize()
        clock = [NOW.timestamp()]
        market = MarketService(store, network=True, token='private-test-key', clock=lambda: clock[0], persistent_tiingo=True,
                               client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)))
        feeds = LiveFeeds(market)
        feeds.test_clock = clock
        return feeds
    return build


def quote(symbol='aapl', *, as_of=NOW, price=100):
    return {'ticker': symbol, 'timestamp': as_of.isoformat(), 'tngoLast': price}


@pytest.mark.parametrize('payload', [
    {}, [quote()], [quote(), quote(), quote('spy')], [quote('wrong'), quote('spy')],
    [quote(price=0), quote('spy')], [quote(price=True), quote('spy')],
    [quote(price=float('inf')), quote('spy')], [quote(as_of=NOW + timedelta(seconds=1)), quote('spy')],
    [quote(as_of=NOW - timedelta(seconds=901)), quote('spy')],
    [{**quote(), 'timestamp': '2026-10-12T14:00:00'}, quote('spy')],
])
def test_reference_quotes_require_all_tickers_finite_prices_explicit_and_fresh_timestamps(factory, payload):
    feeds = factory(lambda _: httpx.Response(200, json=payload) if not any(isinstance(row, dict) and row.get('tngoLast') == float('inf') for row in (payload if isinstance(payload, list) else [])) else httpx.Response(200, content=b'[{"ticker":"aapl","timestamp":"2026-10-12T14:00:00Z","tngoLast":Infinity}]'))
    with pytest.raises(FeedError):
        feeds.quotes(['AAPL'])


def test_quotes_batch_cache_stale_check_and_budget_metadata(factory):
    seen = []
    def handler(request):
        seen.append(request)
        assert request.url.path == '/iex/AAPL,SPY'
        assert request.headers['authorization'] == 'Token private-test-key'
        assert 'private-test-key' not in str(request.url)
        return httpx.Response(200, json=[quote(), quote('spy', price=500)])
    feeds = factory(handler)
    assert feeds.quotes(['AAPL'])['AAPL']['price'] == 100
    assert feeds.quotes(['AAPL'])['SPY']['price'] == 500 and len(seen) == 1
    feeds.test_clock[0] += 901
    with pytest.raises(FeedError):
        feeds.quotes(['AAPL'])
    assert len(seen) == 2
    with feeds.market.cache.locked() as db:
        usage = feeds.market.cache.read(db, 'usage:tiingo:2026-10')
        assert usage['symbols'] == ['AAPL', 'SPY'] and usage['bytes'] > 0
        assert 'private-test-key' not in str(usage)


def test_closed_quote_tolerance_is_explicit(factory):
    feeds = factory(lambda _: httpx.Response(200, json=[quote(as_of=NOW - timedelta(days=2)), quote('spy', as_of=NOW - timedelta(days=2))]))
    assert feeds.quotes(['AAPL'], allow_closed=True)['AAPL']['price'] == 100


def test_news_deduplicated_future_article_excluded_and_empty_news_valid(factory):
    rows = [{'url': 'https://example.com/story', 'title': 'Observed', 'description': 'Shared input', 'tickers': ['aapl'], 'publishedDate': NOW.isoformat()},
            {'url': 'https://example.com/story', 'title': 'Duplicate', 'tickers': ['aapl'], 'publishedDate': NOW.isoformat()},
            {'url': 'https://example.com/future', 'title': 'Future', 'tickers': ['aapl'], 'publishedDate': (NOW + timedelta(hours=1)).isoformat()}]
    feeds = factory(lambda request: httpx.Response(200, json=rows))
    result = feeds.common_context(['AAPL'])
    assert len(result['news']) == 1
    assert result['news'][0]['title'] == 'Duplicate'
    assert result['news_sources'][0]['status'] == 'ok'
    assert result['events'] == []
    feeds.market.token = ''
    with pytest.raises(FeedError, match='news_unavailable'):
        feeds.common_context(['MSFT'])


def test_empty_verified_news_corpus_and_source_readiness(factory):
    feeds = factory(lambda _: httpx.Response(200, json=[]))
    assert feeds.common_context(['AAPL'])['news'] == []
    assert feeds.readiness() is None
    feeds.market.persistent_tiingo = False
    assert 'licence' in feeds.readiness()
    feeds.market.persistent_tiingo = True
    feeds.market.network = False
    assert 'feeds' in feeds.readiness()


def test_verified_actions_and_window_corpus_bounded_shared_hash(factory):
    def handler(request):
        symbol = request.url.path.split('/')[3] if 'corporate-actions' in request.url.path else 'aapl'
        if request.url.path.endswith('/splits'):
            assert request.url.params['startExDate'] == '2026-10-11'
            return httpx.Response(200, json=[{'ticker': symbol, 'exDate': '2026-10-12', 'splitStatus': 'a', 'splitFactor': 2},
                {'ticker': symbol, 'exDate': '2026-10-12', 'splitStatus': 'c', 'splitFactor': 5},
                {'ticker': symbol, 'exDate': '2026-10-13', 'splitStatus': 'a', 'splitFactor': 3}])
        if request.url.path.endswith('/distributions'):
            return httpx.Response(200, json=[{'ticker': symbol, 'exDate': '2026-10-12', 'distribution': 1.5, 'paymentDate': '2026-10-16'},
                {'ticker': symbol, 'exDate': '2026-10-12', 'distribution': 2, 'paymentDate': None, 'distributionFrequency': 'c'}])
        if request.url.path == '/tiingo/news':
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[quote(), quote('spy', price=500)])
    feeds = factory(handler)
    actions = feeds.actions(['AAPL'], '2026-10-11')
    assert len(actions) == 4
    assert len([item for item in actions if item['kind'] == 'dividend']) == 2
    assert all(item['payment_date'] == '2026-10-16' for item in actions if item['kind'] == 'dividend')
    assert feeds.actions(['AAPL'], '2026-10-12') == []
    feeds.test_clock[0] += 61
    result = feeds.window_snapshot(['AAPL'], '2026-10-11')
    assert set(result['quotes']) == {'AAPL', 'SPY'} and result['news'] == []
    copy = snapshot('shared_window_input', datetime.fromisoformat(result['captured_at']),
                    **{key: value for key, value in result.items() if key not in ['id', 'kind', 'hash', 'captured_at']})
    assert copy['id'] != result['id'] and copy['hash'] == result['hash']


@pytest.mark.parametrize('kind,payload', [
    ('splits', {}), ('splits', [{'exDate': '2026-10-12', 'ticker': 'MSFT', 'splitStatus': 'a', 'splitFactor': 2}]),
    ('splits', [{'exDate': '2026-10-12', 'splitStatus': 'unknown', 'splitFactor': 2}]),
    ('splits', [{'exDate': '2026-10-12', 'splitStatus': 'a', 'splitFactor': 0}]),
    ('distributions', [{'exDate': '2026-10-12', 'distribution': -1}]),
    ('distributions', [{'exDate': '2026-10-12', 'distribution': 1, 'paymentDate': 'wrong'}]),
])
def test_missing_or_invalid_corporate_actions_fail_closed(factory, kind, payload):
    feeds = factory(lambda request: httpx.Response(200, json=payload if request.url.path.endswith('/' + kind) else []))
    with pytest.raises(FeedError, match='corporate_actions_unavailable'):
        feeds.actions(['AAPL'], '2026-10-11')


def test_monthly_guard_counts_unique_symbols_and_reserves_bytes_before_io(factory):
    seen = []
    feeds = factory(lambda request: seen.append(request) or httpx.Response(200, json=[]))
    cache = feeds.market.cache
    with cache.locked() as db:
        cache.write(db, 'usage:tiingo:2026-10', {'symbols': [], 'bytes': 800_000_000})
    with pytest.raises(FeedError, match='monthly_bandwidth_limit'):
        feeds.market.fetch_json('https://api.tiingo.com/iex/AAPL,SPY', params={})
    assert seen == []
    with cache.locked() as db:
        cache.write(db, 'usage:tiingo:2026-10', {'symbols': [f'T{i}' for i in range(500)], 'bytes': 0})
    with pytest.raises(FeedError, match='monthly_symbol_limit'):
        feeds.market.fetch_json('https://api.tiingo.com/tiingo/news', params={'tickers': 'AAPL'})
    assert seen == []
    feeds.test_clock[0] = datetime(2026, 11, 1, tzinfo=UTC).timestamp()
    feeds.market.fetch_json('https://api.tiingo.com/iex/AAPL', params={})
    assert len(seen) == 1
