import re
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from .model_catalog import MODELS

MODEL_IDS = ("momentum", "mean-reversion", "buy-and-hold")
STRATEGY_IDS = ("balanced", "conservative", "responsive")
SYMBOLS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA")
MAX_WATCHLIST = 10


def normalize_ticker(value):
    if not isinstance(value, str):
        raise ValueError("Ticker must be a string")
    symbol = value.strip().upper().replace(".", "-")
    if len(symbol) > 15 or not re.fullmatch(r"[A-Z][A-Z0-9]{0,9}(?:-[A-Z0-9]{1,5}){0,2}", symbol):
        raise ValueError("Use a stock or ETF ticker, such as TSLA or BRK-B")
    return symbol


Ticker = Annotated[str, BeforeValidator(normalize_ticker)]


class WatchlistInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: list[Ticker] = Field(min_length=1, max_length=MAX_WATCHLIST)

    @model_validator(mode="after")
    def unique_symbols(self):
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("Tickers must be unique after normalization")
        return self


class ExperimentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    comparison: Literal["models", "strategies"] = "models"
    model_ids: list[str] = Field(
        default_factory=lambda: list(MODEL_IDS), min_length=1, max_length=3
    )
    strategy_ids: list[Literal["balanced", "conservative", "responsive"]] = Field(
        default_factory=lambda: ["balanced"], min_length=1, max_length=3
    )
    symbol: Ticker = "SPY"
    seed: Annotated[int, Field(ge=0, le=2**32 - 1, strict=True)] = 42
    initial_cash: Annotated[float, Field(ge=100, le=100_000_000, strict=True)] = 100_000
    bars: Annotated[int, Field(ge=60, le=1440, strict=True)] = 180
    decision_checkpoints: Annotated[int, Field(ge=1, le=3, strict=True)] = 2

    @model_validator(mode="after")
    def validate_factors(self):
        if any(model not in MODELS for model in self.model_ids):
            raise ValueError("Select a known, explicitly supported model")
        if len(set(self.model_ids)) != len(self.model_ids) or len(set(self.strategy_ids)) != len(self.strategy_ids):
            raise ValueError("Participant IDs must be unique")
        if self.comparison == "models" and not (len(self.model_ids) >= 2 and len(self.strategy_ids) == 1):
            raise ValueError("Model comparison requires at least two models and exactly one strategy")
        if self.comparison == "strategies" and not (len(self.model_ids) == 1 and len(self.strategy_ids) >= 2):
            raise ValueError("Strategy comparison requires exactly one model and at least two strategies")
        if self.name is not None:
            self.name = self.name.strip()
            if not self.name:
                raise ValueError("Name cannot be blank")
        return self
