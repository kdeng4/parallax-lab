import math
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from parallax_lab.engine import metrics, run_experiment
from parallax_lab.main import create_app
from parallax_lab.market import Candle, MarketDataset, data_hash
from parallax_lab.market_cache import MarketCache
from parallax_lab.market_feeds import (BOC_SERIES, FeedError, MarketService, parse_boc, parse_tiingo,
                                      retry_seconds, technical_indicators)
from parallax_lab.schemas import ExperimentInput
from parallax_lab.storage import Store

NOW = int(datetime(2026, 10, 12, 18, tzinfo=UTC).timestamp())


def prices(count=80):
    """Clearly synthetic test transport payload, never imported by runtime code."""
    days = [date(2026, 5, 1) + timedelta(days=i) for i in range(150)]
    days = [day for day in days if day.weekday() < 5][:count]
    return [{"date": f"{day}T00:00:00.000Z", "open": 100 + i, "high": 102 + i,
             "low": 99 + i, "close": 101 + i, "volume": 1000 + i,
             "adjOpen": 50 + i / 2, "adjHigh": 51 + i / 2, "adjLow": 49.5 + i / 2,
             "adjClose": 50.5 + i / 2, "adjVolume": 2000 + 2 * i} for i, day in enumerate(days)]


def boc():
    return {"observations": [
        {"d": "2026-10-09", "FXUSDCAD": {"v": "1.4271"}, "FXEURCAD": {"v": "1.5978"}, "V39079": {"v": "2.25"}},
        {"d": "2026-10-08", "FXUSDCAD": {"v": "1.4240"}, "FXEURCAD": {"v": "1.5950"}, "V39079": {"v": "2.25"}},
        {"d": "2026-09-01", "V122531": {"v": "2.39"}}, {"d": "2026-08-01", "V122531": {"v": "2.27"}},
    ]}


@pytest.fixture
def store(tmp_path):
    result = Store(f"sqlite:///{tmp_path / 'market.db'}")
    result.initialize()
    return result


def service(store, handler, **kwargs):
    return MarketService(store, network=True, token="private-test-token", clock=lambda: NOW,
                         client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def test_indicator_math_and_warmup():
    assert all(v is None for v in technical_indicators([100]).values())
    flat = technical_indicators([100] * 60)
    assert flat == {"sma20": 100, "sma50": 100, "rsi14": 50, "macd": 0, "macd_signal": 0}
    ascending = technical_indicators(list(range(1, 81)))
    assert ascending == {"sma20": 70.5, "sma50": 55.5, "rsi14": 100, "macd": 7, "macd_signal": 7}
    assert technical_indicators(list(range(80, 0, -1)))["rsi14"] == 0
    mixed = [100]
    for delta in [1] * 9 + [-1] * 5:
        mixed.append(mixed[-1] + delta)
    assert technical_indicators(mixed)["rsi14"] == pytest.approx(100 * 9 / 14, abs=1e-6)


def test_prices_are_sorted_adjusted_and_incomplete_sessions_excluded():
    rows = prices()
    rows.append({**rows[-1], "date": "2026-10-12T00:00:00Z"})
    data = parse_tiingo(list(reversed(rows)), date(2026, 10, 12))
    assert len(data["candles"]) == 80
    assert data["candles"][0]["open"] == 50
    assert data["close"] == 180 and data["adjusted_close"] == 90
    assert data["volume"] == 1079
    assert data["change_pct"] == pytest.approx((90 / 89.5 - 1) * 100, abs=1e-6)
    assert data["as_of"] == rows[-2]["date"][:10]


@pytest.mark.parametrize("change", [
    {"close": 0}, {"adjClose": float("nan")}, {"adjOpen": True}, {"volume": -1},
    {"volume": 1.5}, {"adjVolume": -1}, {"high": 1}, {"adjLow": 200}, {"date": "bad"},
])
def test_invalid_prices_rejected(change):
    rows = prices()
    rows[0].update(change)
    with pytest.raises((ValueError, TypeError)):
        parse_tiingo(rows, date(2026, 10, 12))


@pytest.mark.parametrize("rows", [[], {}, [{}] * 501, prices(2) * 2])
def test_incomplete_duplicate_and_unbounded_series_rejected(rows):
    with pytest.raises(ValueError):
        parse_tiingo(rows, date(2026, 10, 12))


def test_macro_frequency_missing_values_and_staleness():
    items = parse_boc(boc(), date(2026, 10, 12))
    assert items[0]["change"] == .0031
    assert items[3]["frequency"] == "monthly average" and items[3]["status"] == "ok"
    assert items[3]["change"] == .12
    assert all(item["status"] == "stale" for item in parse_boc(boc(), date(2027, 1, 1)))
    partial = {"observations": [{"d": "2026-10-09", "FXUSDCAD": {"v": "1.42"}}]}
    assert parse_boc(partial, date(2026, 10, 12))[1]["value"] is None
    for invalid in ({"observations": []}, {"observations": [{}] * 101},
                    {"observations": boc()["observations"] * 2}):
        with pytest.raises(ValueError):
            parse_boc(invalid, date(2026, 10, 12))


def test_shared_cache_prevents_refetch_after_reload_and_restart(store):
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.host == "api.tiingo.com":
            assert request.headers["Authorization"] == "Token private-test-token"
            assert "token" not in str(request.url)
            assert request.url.params["endDate"] == "2026-10-11"
            return httpx.Response(200, json=prices())
        return httpx.Response(200, json=boc())
    first = service(store, handler).overview()
    second = service(Store(f"sqlite:///{store.path}"), handler).overview()
    assert first == second and len(calls) == 6
    assert len(first["macro"]) == 4 and len(first["stocks"]) == 5
    assert "candles" not in first["stocks"][0]["data"]
    assert "private-test-token" not in str(first)


def test_concurrent_leases_and_rolling_budgets(store):
    cache = MarketCache(store)
    with ThreadPoolExecutor(max_workers=12) as executor:
        claims = list(executor.map(lambda _: cache.claim("same", "p", NOW, ((60, 2),)), range(12)))
    assert sum(token is not None for _, token in claims) == 1
    assert cache.claim("other", "p", NOW, ((60, 2),))[1]
    entry, token = cache.claim("third", "p", NOW + 1, ((60, 2),))
    assert token is None and entry["error"] == "budget_exhausted" and entry["retry_at"] == NOW + 60
    assert cache.claim("third", "p", NOW + 60, ((60, 2),))[1]


def test_late_worker_cannot_overwrite_a_new_lease(store):
    cache = MarketCache(store)
    _, old = cache.claim("late", "p", NOW, ((86_400, 20),))
    _, new = cache.claim("late", "p", NOW + 121, ((86_400, 20),))
    cache.finish("late", "p", new, NOW + 122, data={"value": 2})
    assert cache.finish("late", "p", old, NOW + 123, data={"value": 1})["data"] == {"value": 2}


@pytest.mark.parametrize("status,expected", [(429, "rate_limited"), (401, "authentication_failed"), (403, "authentication_failed"), (500, "provider_unavailable")])
def test_provider_errors_persist_cooldown_without_retries(store, status, expected):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "7200"}, text="secret details must not appear")
    market = service(store, handler)
    one, two = market.stock("AAPL"), market.stock("MSFT")
    assert one["status"] == two["status"] == expected and len(calls) == 1
    assert "secret details" not in str(one)
    if status == 429:
        assert one["next_refresh_at"] == "2026-10-12T20:00:00Z"
    assert retry_seconds("Mon, 12 Oct 2026 20:00:00 GMT", NOW) == 7200
    assert retry_seconds("bad-date", NOW) == 0


def test_bad_payload_and_timeout_never_replace_good_cached_data(store):
    market = service(store, lambda _: httpx.Response(200, json=prices()))
    good = market.stock("SPY")
    assert good["data"]
    def timeout(_):
        raise httpx.ReadTimeout("upstream secret")
    failing = service(store, timeout)
    failing.clock = lambda: NOW + 21_601
    result = failing.stock("SPY")
    assert result["data"] == good["data"] and result["status"] == "stale"
    with pytest.raises(FeedError, match="stale"):
        failing.replay("SPY", 60)


@pytest.mark.parametrize("response", [httpx.Response(200, text="bad json"), httpx.Response(200, content=b"x" * 524_289), httpx.Response(200, json={"detail": "error"})])
def test_invalid_response_returns_unavailable(store, response):
    result = service(store, lambda _: response).stock("SPY")
    assert result["data"] is None and result["status"] != "ok"


def test_absent_key_offline_unknown_symbol_and_bar_bounds(store):
    no_key = MarketService(store, network=True, token="")
    assert no_key.stock("SPY")["status"] == "key_missing"
    assert MarketService(store, network=False).overview()["macro"][0]["value"] is None
    with pytest.raises(ValueError):
        no_key.stock("../../private")
    with pytest.raises(ValueError, match="252"):
        no_key.replay("SPY", 253)
    short = service(store, lambda _: httpx.Response(200, json=prices(2)))
    with pytest.raises(FeedError):
        short.replay("SPY", 60)


def test_daily_replay_provenance_causality_and_correct_annualization(store):
    # A snapshot close to the fixed clock is required for a usable replay.
    rows = prices(100)
    market = service(store, lambda _: httpx.Response(200, json=rows))
    market.clock = lambda: int((datetime.fromisoformat(rows[-1]["date"].replace("Z", "+00:00")) + timedelta(days=1)).timestamp())
    dataset = market.replay("SPY", 60)
    detail = run_experiment(ExperimentInput(bars=60), dataset=dataset)
    assert detail["data_source"] == "tiingo" and detail["seed"] is None and detail["interval"] == "1d"
    assert detail["data_hash"] == data_hash(dataset.candles)
    assert detail["metadata"]["dataset"]["adjustment"] == "split_and_dividend_adjusted"
    assert "seed" not in detail["metadata"]["request"]
    assert detail["metadata"]["metrics"]["periods_per_year"] == 252
    for event in detail["events"]:
        if event["type"] == "fill":
            assert event["details"]["execution_bar_index"] == event["details"]["observed_bar_index"] + 1
        if event["type"] == "decision":
            assert event["timestamp"].endswith("23:59:59Z")
    curve = [{"equity": value} for value in (100, 102, 101, 104)]
    assert metrics(curve, [], 100)["sharpe"] / metrics(curve, [], 100, 252)["sharpe"] == pytest.approx(math.sqrt(390), rel=1e-6)
    with pytest.raises(ValueError, match="length"):
        run_experiment(ExperimentInput(bars=61), dataset=dataset)


def test_real_api_never_falls_back_to_synthetic(store, monkeypatch):
    monkeypatch.delenv("PARALLAX_MARKET_SOURCE")
    with TestClient(create_app(f"sqlite:///{store.path}", seed_demo=False)) as client:
        catalog = client.get("/api/v1/catalog").json()
        assert catalog["data_source"] == "tiingo" and catalog["max_bars"] == 252
        assert client.post("/api/v1/experiments", json={"bars": 60}).status_code == 503
        assert client.post("/api/v1/experiments", json={"bars": 300}).status_code == 422
        assert client.get("/api/v1/experiments").json() == {"experiments": []}
        assert all(s["data"] is None for s in client.get("/api/v1/market/overview").json()["stocks"])


@pytest.mark.parametrize("candles,interval", [([], "1d"), ([Candle("2026-01-01", 1, 1, 1, 1, 1)], "1d"),
    ([Candle("2026-01-01T00:00:00Z", 1, 1, 1, 1, 1)] * 2, "1d"),
    ([Candle("2026-01-01T00:00:00Z", 1, 0, 1, 1, 1)], "1d"),
    ([Candle("2026-01-01T00:00:00Z", 1, 1, 1, 1, 1)], "bad")])
def test_invalid_snapshot_cannot_enter_engine(candles, interval):
    with pytest.raises(ValueError):
        MarketDataset(tuple(candles), "tiingo", interval, {})
