"""Synthetic OHLCV fixture generator. No external market data is implied."""

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True, slots=True)
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int | float

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MarketDataset:
    candles: tuple[Candle, ...]
    source: str
    interval: str
    provenance: dict

    def __post_init__(self):
        if self.interval not in ("1m", "1d") or not self.candles:
            raise ValueError("A dataset needs candles and a supported interval")
        previous = None
        for candle in self.candles:
            instant = datetime.fromisoformat(candle.timestamp.replace("Z", "+00:00"))
            if instant.tzinfo is None or (previous is not None and instant <= previous):
                raise ValueError("Candle timestamps must increase and include a timezone")
            previous = instant
            prices = (candle.open, candle.high, candle.low, candle.close)
            if not all(math.isfinite(v) and v > 0 for v in prices) or not (
                candle.low <= min(candle.open, candle.close) <= max(candle.open, candle.close) <= candle.high
            ) or not math.isfinite(candle.volume) or candle.volume < 0:
                raise ValueError("Invalid OHLCV candle")


def generate_candles(symbol: str, seed: int, bars: int) -> tuple[Candle, ...]:
    rng_seed = int.from_bytes(hashlib.sha256(f"{symbol}:{seed}".encode()).digest()[:8])
    rng = random.Random(rng_seed)
    previous = {"SPY": 585, "QQQ": 515, "AAPL": 235, "MSFT": 425, "NVDA": 140}[symbol]
    start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    result = []
    for index in range(bars):
        opening = previous * (1 + rng.gauss(0, 0.00018))
        drift = 0.00008 + 0.00038 * math.sin(index / 21)
        closing = opening * math.exp(drift + rng.gauss(0, 0.00095))
        wick = abs(rng.gauss(0.00045, 0.0002))
        result.append(Candle(
            timestamp=(start + timedelta(minutes=index)).isoformat().replace("+00:00", "Z"),
            open=round(opening, 6), high=round(max(opening, closing) * (1 + wick), 6),
            low=round(min(opening, closing) * (1 - wick), 6), close=round(closing, 6),
            volume=rng.randint(15_000, 250_000),
        ))
        previous = closing
    return tuple(result)


def data_hash(candles: tuple[Candle, ...]) -> str:
    payload = json.dumps([c.as_dict() for c in candles], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def close_time(candle: Candle, interval: str = "1m") -> str:
    # Daily timestamps are normalized session-date labels, not exchange times.
    seconds = 86_399 if interval == "1d" else 59
    return (datetime.fromisoformat(candle.timestamp.replace("Z", "+00:00")) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
