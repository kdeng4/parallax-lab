"""Real, attributed market inputs. Unavailable data never becomes a fixture."""

import json
import math
import os
import statistics
import time
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from .market import Candle, MarketDataset
from .market_cache import MarketCache
from .schemas import normalize_ticker
from .watchlist import Watchlist

BOC_SERIES = {
    "FXUSDCAD": ("USD / CAD", "CAD per USD", "daily", 7),
    "FXEURCAD": ("EUR / CAD", "CAD per EUR", "daily", 7),
    "V39079": ("Bank of Canada policy rate", "%", "daily", 7),
    "V122531": ("Canada 3-month Treasury bill", "%", "monthly average", 65),
}
BOC_URL = "https://www.bankofcanada.ca/valet/observations/" + ",".join(BOC_SERIES) + "/json"
TIINGO_URL = "https://api.tiingo.com/tiingo/daily"
MAX_RESPONSE_BYTES = 524_288
MAX_REPLAY_BARS = 252
TTL = 21_600  # Fetch on demand at most every six hours; never poll idle pages.


class FeedError(Exception):
    def __init__(self, code: str, retry_after=0):
        super().__init__(code)
        self.code, self.retry_after = code, retry_after


def finite(value, *, positive=False):
    if isinstance(value, bool):
        raise ValueError("Boolean is not a market value")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError("Invalid market value")
    return result


def stamp(epoch: int):
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z") if epoch else None


def retry_seconds(value: str, now: int):
    try:
        return max(0, int(value))
    except ValueError:
        try:
            return max(0, math.ceil(parsedate_to_datetime(value).timestamp() - now))
        except (ValueError, TypeError, OverflowError):
            return 0


def technical_indicators(closes: list[float]) -> dict:
    """Wilder RSI, simple moving averages, and SMA-seeded EMA MACD."""
    def ema(values, period):
        if len(values) < period:
            return []
        result = [statistics.fmean(values[:period])]
        for value in values[period:]:
            result.append(result[-1] + (value - result[-1]) * 2 / (period + 1))
        return result

    rsi = None
    if len(closes) >= 15:
        changes = [b - a for a, b in zip(closes, closes[1:])]
        gain = statistics.fmean(max(v, 0) for v in changes[:14])
        loss = statistics.fmean(max(-v, 0) for v in changes[:14])
        for value in changes[14:]:
            gain, loss = (gain * 13 + max(value, 0)) / 14, (loss * 13 + max(-value, 0)) / 14
        rsi = 50.0 if gain == loss == 0 else 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    fast, slow = ema(closes, 12), ema(closes, 26)
    macd = [a - b for a, b in zip(fast[14:], slow)]
    signal = ema(macd, 9)
    values = {"sma20": statistics.fmean(closes[-20:]) if len(closes) >= 20 else None,
              "sma50": statistics.fmean(closes[-50:]) if len(closes) >= 50 else None,
              "rsi14": rsi, "macd": macd[-1] if macd else None,
              "macd_signal": signal[-1] if signal else None}
    return {key: round(value, 6) if value is not None else None for key, value in values.items()}


def parse_tiingo(payload, today: date) -> dict:
    if not isinstance(payload, list) or not 2 <= len(payload) <= 500:
        raise ValueError("Expected a bounded daily series")
    by_date = {}
    for row in payload:
        if not isinstance(row, dict) or not isinstance(row.get("date"), str):
            raise ValueError("Invalid daily row")
        day = date.fromisoformat(row["date"][:10])
        if day >= today:
            continue  # Never use today's potentially incomplete daily bar.
        if day in by_date:
            raise ValueError("Duplicate trading session")
        adjusted = {k: finite(row["adj" + k.title()], positive=True) for k in ("open", "high", "low", "close")}
        raw = {k: finite(row[k], positive=True) for k in ("open", "high", "low", "close")}
        for prices in (adjusted, raw):
            if not prices["low"] <= min(prices["open"], prices["close"]) <= max(prices["open"], prices["close"]) <= prices["high"]:
                raise ValueError("Inconsistent OHLC")
        volume, adj_volume = finite(row["volume"]), finite(row["adjVolume"])
        if volume < 0 or adj_volume < 0 or not volume.is_integer():
            raise ValueError("Invalid volume")
        by_date[day] = {"timestamp": f"{day.isoformat()}T00:00:00Z", **adjusted, "volume": adj_volume,
                        "raw_close": raw["close"], "raw_volume": int(volume)}
    rows = [by_date[d] for d in sorted(by_date)][-MAX_REPLAY_BARS:]
    if len(rows) < 2:
        raise ValueError("Insufficient completed sessions")
    closes = [r["close"] for r in rows]
    return {"as_of": rows[-1]["timestamp"][:10], "close": rows[-1]["raw_close"],
            "adjusted_close": closes[-1], "change_pct": round((closes[-1] / closes[-2] - 1) * 100, 6),
            "volume": rows[-1]["raw_volume"], "indicators": technical_indicators(closes),
            "candles": [{k: v for k, v in row.items() if not k.startswith("raw_")} for row in rows]}


def parse_boc(payload, today: date) -> list[dict]:
    observations = payload["observations"]
    if not isinstance(observations, list) or len(observations) > 100:
        raise ValueError("Expected bounded observations")
    if any(not isinstance(row, dict) or any(key in row and not isinstance(row[key], dict) for key in BOC_SERIES)
           for row in observations):
        raise ValueError("Invalid observation row")
    indicators = []
    for series, (label, unit, frequency, max_age) in BOC_SERIES.items():
        values = {}
        for row in observations:
            if series not in row or row[series].get("v") in (None, ""):
                continue
            day = date.fromisoformat(row["d"])
            value = finite(row[series]["v"], positive=unit != "%")
            if day > today or day in values:
                raise ValueError("Invalid observation date")
            values[day] = value
        if not values:
            indicators.append({"id": series, "label": label, "unit": unit, "frequency": frequency,
                               "value": None, "as_of": None, "change": None, "status": "unavailable"})
            continue
        days = sorted(values)
        latest = days[-1]
        indicators.append({"id": series, "label": label, "unit": unit, "frequency": frequency,
                           "value": values[latest], "as_of": latest.isoformat(),
                           "change": round(values[latest] - values[days[-2]], 6) if len(days) > 1 else None,
                           "status": "ok" if (today - latest).days <= max_age else "stale"})
    if not any(item["value"] is not None for item in indicators):
        raise ValueError("Empty provider response")
    return indicators


class MarketService:
    def __init__(self, store, *, network=None, token=None, clock=time.time, client_factory=None, persistent_tiingo=None):
        self.cache = MarketCache(store)
        self.watchlist = Watchlist(store)
        self.network = (os.getenv("PARALLAX_MARKET_NETWORK", "1" if os.getenv("VERCEL_ENV") == "production" else "0") == "1"
                        if network is None else network)
        self.token = os.getenv("TIINGO_API_KEY", "").strip() if token is None else token
        self.persistent_tiingo = (os.getenv('PARALLAX_TIINGO_STORAGE_APPROVED') == '1'
                                 if persistent_tiingo is None else persistent_tiingo)
        self.clock = clock
        self.client_factory = client_factory or (lambda: httpx.Client(timeout=5, follow_redirects=False))

    def fetch_json(self, url, *, params, headers=None, csv_response=False):
        reservation, reserved = None, MAX_RESPONSE_BYTES + 32_768
        parsed = urlsplit(url)
        if parsed.hostname == 'api.tiingo.com':
            path = parsed.path.split('/')
            symbols = str(params.get('tickers', '')).split(',') if params.get('tickers') else []
            if len(path) == 3 and path[1] == 'iex':
                symbols.extend(path[2].split(','))
            elif len(path) == 5 and path[1:3] in (['tiingo', 'daily'], ['tiingo', 'corporate-actions']):
                symbols.append(path[3])
            reservation, error = self.cache.reserve_tiingo_transfer(int(self.clock()), symbols, reserved)
            if error:
                raise FeedError(error, 86_400)
        deadline = time.monotonic() + 10
        with self.client_factory() as client, client.stream("GET", url, params=params, headers=headers) as response:
            if response.status_code == 429:
                raise FeedError("rate_limited", retry_seconds(response.headers.get("Retry-After", ""), int(self.clock())))
            if response.status_code in (401, 403):
                raise FeedError("authentication_failed", 21_600)
            if response.status_code == 404:
                raise FeedError("not_found")
            if response.status_code != 200:
                raise FeedError("provider_unavailable")
            parts, size = [], 0
            for part in response.iter_bytes(chunk_size=16_384):
                size += len(part)
                if size > MAX_RESPONSE_BYTES or time.monotonic() > deadline:
                    raise FeedError("invalid_response")
                parts.append(part)
            content = b"".join(parts)
            if reservation:
                # Failed reads retain the pessimistic reservation. Successful reads
                # release unused capacity, with a margin for protocol overhead.
                self.cache.finish_tiingo_transfer(reservation, reserved, size + 8192)
            return content.decode('utf-8-sig') if csv_response else json.loads(content)

    def load(self, key, provider, fetch, parse, *, limits=None, ttl=TTL, persistent=None):
        now = int(self.clock())
        if not self.network:
            return {"error": "offline"}
        if provider == "tiingo" and not self.token:
            return {"error": "key_missing"}
        limits = limits or (((60, 5), (3600, 10), (86_400, 30)) if provider == "tiingo" else ((3600, 1), (86_400, 4)))
        persistent = (provider != 'tiingo' or self.persistent_tiingo) if persistent is None else persistent
        entry, lease = self.cache.claim(key, provider, now, limits, persistent=persistent)
        if lease:
            try:
                data = parse(fetch(), datetime.fromtimestamp(now, UTC).date())
                entry = self.cache.finish(key, provider, lease, int(self.clock()), data=data,
                                          ttl=ttl if persistent else 0, persistent=persistent)
                if not persistent:
                    # Content lives only in this request, never in Neon or a process cache.
                    entry['expires_at'] = int(self.clock()) + 60
            except (FeedError, httpx.HTTPError, ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError) as error:
                entry = self.cache.finish(key, provider, lease, int(self.clock()),
                                          error=error.code if isinstance(error, FeedError) else "invalid_or_unavailable_data",
                                          retry_after=error.retry_after if isinstance(error, FeedError) else 0,
                                          persistent=persistent,
                                          provider_backoff=not (isinstance(error, FeedError) and error.code == "not_found"))
        return entry

    def stock(self, symbol):
        symbol = normalize_ticker(symbol)
        today = datetime.fromtimestamp(self.clock(), UTC).date()
        entry = self.load(f"tiingo:{symbol}", "tiingo", lambda: self.fetch_json(
            f"{TIINGO_URL}/{symbol}/prices",
            params={"startDate": (today - timedelta(days=400)).isoformat(), "endDate": (today - timedelta(days=1)).isoformat(),
                    "resampleFreq": "daily"}, headers={"Authorization": f"Token {self.token}"}), parse_tiingo)
        data = entry.get("data")
        stale = data is not None and (entry.get("expires_at", 0) <= self.clock()
                                      or (today - date.fromisoformat(data["as_of"])).days > 7 or bool(entry.get("error")))
        return {"symbol": symbol, "source": "Tiingo", "source_url": "https://www.tiingo.com/",
                "status": "stale" if stale else "ok" if data else entry.get("error", "refreshing"),
                "fetched_at": stamp(entry.get("fetched_at", 0)), "next_refresh_at": stamp(max(entry.get("expires_at", 0), entry.get("retry_at", 0))),
                "data": data}

    def overview(self):
        entry = self.load("boc", "boc", lambda: self.fetch_json(BOC_URL, params={"recent": 5}), parse_boc)
        macro = entry.get("data") or [{"id": key, "label": value[0], "unit": value[1], "frequency": value[2],
                                       "value": None, "change": None, "as_of": None, "status": entry.get("error", "refreshing")}
                                      for key, value in BOC_SERIES.items()]
        macro = [{**item, "status": "stale" if item["value"] is not None and (
            entry.get("expires_at", 0) <= self.clock() or entry.get("error") or (
                datetime.fromtimestamp(self.clock(), UTC).date() - date.fromisoformat(item["as_of"])
            ).days > BOC_SERIES[item["id"]][3]) else item["status"],
                  "source": "Bank of Canada", "source_url": "https://www.bankofcanada.ca/rates/",
                  "fetched_at": stamp(entry.get("fetched_at", 0)),
                  "next_refresh_at": stamp(max(entry.get("expires_at", 0), entry.get("retry_at", 0)))} for item in macro]
        stocks = [self.stock(symbol) for symbol in self.watchlist.get()["symbols"]]
        for stock in stocks:
            if stock["data"]:
                stock["data"] = {k: v for k, v in stock["data"].items() if k != "candles"}
        return {"as_of": stamp(int(self.clock())), "stocks": stocks, "macro": macro,
                "refresh_interval_seconds": TTL, "price_frequency": "Completed daily sessions; not intraday quotes",
                "indicator_basis": "Split- and dividend-adjusted closes. MACD 12/26/9; Wilder RSI 14; SMA 20/50.",
                "replay_ready": self.persistent_tiingo and any(s["status"] == "ok" for s in stocks)}

    def replay(self, symbol: str, bars: int):
        if bars > MAX_REPLAY_BARS:
            raise ValueError(f"Daily replays support at most {MAX_REPLAY_BARS} sessions")
        if not self.persistent_tiingo:
            raise FeedError('storage_license_required')
        result = self.stock(symbol)
        if result["status"] != "ok":
            raise FeedError(result["status"])
        data = result["data"]
        if len(data["candles"]) < bars:
            raise FeedError("insufficient_history")
        return MarketDataset(tuple(Candle(**row) for row in data["candles"][-bars:]), "tiingo", "1d",
                             {"provider": "Tiingo", "fetched_at": result["fetched_at"], "as_of": data["as_of"],
                              "adjustment": "split_and_dividend_adjusted", "source_url": "https://www.tiingo.com/",
                              "timestamp_convention": "UTC session-date labels; not intraday exchange timestamps",
                              "limitations": "Retrospectively adjusted prices, not point-in-time vintages; paper quantities are adjusted units."})
