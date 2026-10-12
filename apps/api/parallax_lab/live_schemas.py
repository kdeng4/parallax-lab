"""Forward paper-study inputs and structured portfolio decisions."""

from datetime import UTC, datetime, time
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .model_catalog import MODELS
from .schemas import Ticker


class StudyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=100)
    model_ids: list[str] = Field(min_length=1, max_length=3)
    strategy_ids: list[Literal["balanced", "conservative", "responsive"]] = Field(min_length=1, max_length=3)
    symbols: list[Ticker] = Field(min_length=1, max_length=10)
    initial_cash: Annotated[float, Field(ge=100, le=100_000_000, strict=True)] = 100_000
    timezone: str = Field(default="America/Toronto", min_length=1, max_length=64)
    window_start: str = "09:45"
    window_end: str = "10:45"

    @field_validator("name")
    @classmethod
    def trimmed_name(cls, value):
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose a valid IANA time zone") from None
        return value

    @field_validator("window_start", "window_end")
    @classmethod
    def valid_clock(cls, value):
        if len(value) != 5 or value[2] != ":":
            raise ValueError("Use a 24-hour HH:MM time")
        try:
            time.fromisoformat(value)
        except ValueError:
            raise ValueError("Use a valid 24-hour HH:MM time") from None
        return value

    @model_validator(mode="after")
    def factors(self):
        for values in (self.model_ids, self.strategy_ids, self.symbols):
            if len(set(values)) != len(values):
                raise ValueError("Selections must be unique")
        if any(value not in MODELS for value in self.model_ids):
            raise ValueError("Choose a supported model")
        start, end = time.fromisoformat(self.window_start), time.fromisoformat(self.window_end)
        minutes = (end.hour - start.hour) * 60 + end.minute - start.minute
        if not 30 <= minutes <= 180:
            raise ValueError("The daily window must be 30 to 180 minutes within one local day")
        return self


class TargetWeight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)
    symbol: str = Field(min_length=1, max_length=15)
    weight: float = Field(ge=0, le=1)


class PortfolioDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)
    targets: list[TargetWeight] = Field(max_length=10)
    execute_after_minutes: int = Field(ge=0, le=180)
    summary: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def no_leverage(self):
        if len({item.symbol for item in self.targets}) != len(self.targets) or sum(item.weight for item in self.targets) > 1 + 1e-9:
            raise ValueError("Portfolio targets must be unique and long-only without leverage")
        return self


def window_at(config: dict, now: datetime):
    local = now.astimezone(ZoneInfo(config["timezone"]))
    if local.weekday() >= 5:
        return None
    start = datetime.combine(local.date(), time.fromisoformat(config["window_start"]), local.tzinfo)
    end = datetime.combine(local.date(), time.fromisoformat(config["window_end"]), local.tzinfo)
    if start <= local < end:
        return {"day": local.date().isoformat(), "start": start.astimezone(UTC), "end": end.astimezone(UTC)}
    return None
