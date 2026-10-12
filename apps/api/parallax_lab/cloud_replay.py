"""Bounded cloud inference, using durable cross-worker quotas before billable I/O."""

import asyncio
import time
from datetime import UTC, datetime
from decimal import Decimal

from .engine import replay_experiment
from .market import close_time
from .market_cache import MarketCache
from .model_catalog import MAX_CLOUD_CALLS, OPENAI_LIMITS, OPENAI_MODELS, OPENAI_REPLAY_TIMEOUT, OPENAI_TIMEOUT, available_openai_models
from .providers import Candle, DecisionInput, ProviderConfig, ProviderConfigurationError, ProviderError, build_provider


class ProviderBudgetError(ProviderError):
    """A durable quota or concurrent-call lease prevents another request."""


class CloudReplay:
    def __init__(self, request, store, *, client=None):
        model_ids = set(request.model_ids) & OPENAI_MODELS.keys()
        if not model_ids <= set(available_openai_models()):
            raise ProviderConfigurationError("The selected OpenAI model is not configured on this deployment")
        expected_calls = len(model_ids) * len(request.strategy_ids) * request.decision_checkpoints
        if expected_calls > MAX_CLOUD_CALLS:
            raise ValueError(f"Select fewer checkpoints or cloud participants; at most {MAX_CLOUD_CALLS} OpenAI calls are allowed per experiment")
        if request.bars > 252:
            raise ValueError("OpenAI experiments support at most 252 observed bars")
        allowed = tuple(key.removeprefix("openai:") for key in available_openai_models())
        self.adapters = {
            key: build_provider(ProviderConfig(provider="openai", model=key.removeprefix("openai:"), allowed_models=allowed,
                                              timeout_seconds=OPENAI_TIMEOUT, max_output_tokens=1024, reasoning_effort="low"), client=client)
            for key in model_ids
        }
        self.cache = MarketCache(store)
        self.calls = 0
        self.request = request

    async def decide(self, state, candles, interval):
        now = int(time.time())
        key = "openai:decision"
        entry, lease = self.cache.claim(key, "openai", now, OPENAI_LIMITS, persistent=False)
        if lease is None:
            retry = entry.get("retry_at", entry.get("lease_until", now + 60))
            stamp = datetime.fromtimestamp(retry, UTC).isoformat()
            raise ProviderBudgetError(f"OpenAI call limit or cooldown reached. Retry after {stamp}; no experiment was saved.")
        error, retry_after = None, 0
        self.calls += 1
        try:
            allocation = float(state.account.quantity * Decimal(str(candles[-1].close)) / state.account.equity(candles[-1].close))
            snapshot = DecisionInput(
                symbol=self.request.symbol,
                candles=tuple(Candle(**{**candle.as_dict(), "timestamp": close_time(candle, interval)}) for candle in candles),
                strategy_markdown=state.strategy.markdown,
                current_allocation=allocation, max_allocation=state.strategy.config.max_allocation, interval=interval,
            )
            adapter = self.adapters[state.model_id]
            async with asyncio.timeout(OPENAI_TIMEOUT):
                decision = await adapter.decide(snapshot)
        except TimeoutError:
            error = "timeout"
            raise ProviderError("OpenAI decision timed out; no automatic retry was made and no experiment was saved.") from None
        except asyncio.CancelledError:
            error = "timeout"
            raise
        except ProviderError as failure:
            error = "rate_limited" if failure.status_code == 429 else "provider_failed"
            retry_after = failure.retry_after
            raise
        finally:
            self.cache.finish(key, "openai", lease, int(time.time()), ttl=0, error=error, retry_after=retry_after, persistent=False)
        return min(decision.target_allocation, state.strategy.config.max_allocation), decision.summary, {
            "observed_bars": len(candles), "as_of": close_time(candles[-1], interval),
            "confidence": decision.confidence, "requested_allocation": decision.target_allocation,
            **adapter.last_response_metadata,
        }

    async def run(self, *, dataset):
        try:
            async with asyncio.timeout(OPENAI_REPLAY_TIMEOUT):
                detail = await replay_experiment(self.request, dataset=dataset, cloud_decider=self.decide)
        except TimeoutError:
            raise ProviderError("OpenAI replay exceeded its time limit; no experiment was saved. Already attempted calls can still be billed.") from None
        detail["metadata"]["openai"] = {
            "calls_attempted": self.calls, "max_calls_per_experiment": MAX_CLOUD_CALLS,
            "max_calls_per_minute": OPENAI_LIMITS[0][1], "max_calls_per_day": OPENAI_LIMITS[1][1],
            "max_output_tokens_per_call": 1024, "reasoning_effort": "low", "automatic_retries": 0,
        }
        return detail
