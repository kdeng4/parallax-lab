import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest
from pydantic import ValidationError

from parallax_lab.providers import (
    Candle,
    Decision,
    DecisionInput,
    ProviderConfig,
    ProviderConfigurationError,
    ProviderError,
    ProviderOutputError,
    build_provider,
)


GOOD_DECISION = {"target_allocation": 0.6, "summary": "Trend supports exposure.", "confidence": 0.8}


def snapshot():
    return DecisionInput(
        symbol="SPY",
        strategy_markdown="# Strategy\nKeep allocations below 70%.",
        candles=(Candle(timestamp=datetime(2026, 1, 5, tzinfo=timezone.utc), open=100, high=101, low=99, close=100.5, volume=1000),),
    )


def config(provider="openai", **overrides):
    return ProviderConfig(**{
        "provider": provider,
        "model": "operator-selected-model",
        "allowed_models": ("operator-selected-model",),
        "api_key": "test-key-not-real",
        **overrides,
    })


def envelope(provider, decision=GOOD_DECISION):
    if provider == "openai":
        return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(decision)}]}]}
    return {"stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "paper_trade_decision", "input": decision}]}


def request(provider, handler):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = build_provider(config(provider), client=client)
            return await adapter.decide(snapshot())
    return asyncio.run(run())


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_structured_decision_and_identical_observable_input(provider):
    def handler(req):
        body = json.loads(req.content)
        assert body["model"] == "operator-selected-model"
        if provider == "openai":
            assert req.url == "https://api.openai.com/v1/responses"
            assert req.headers["authorization"] == "Bearer test-key-not-real"
            assert body["store"] is False
            assert body["text"]["format"]["strict"] is True
            sent_input = body["input"][1]["content"]
        else:
            assert req.url == "https://api.anthropic.com/v1/messages"
            assert req.headers["x-api-key"] == "test-key-not-real"
            assert body["tool_choice"]["disable_parallel_tool_use"] is True
            sent_input = body["messages"][0]["content"]
        assert json.loads(sent_input) == snapshot().model_dump(mode="json")
        return httpx.Response(200, json=envelope(provider))
    assert request(provider, handler) == Decision(**GOOD_DECISION)


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("bad_decision", [
    {**GOOD_DECISION, "target_allocation": 1.1},
    {**GOOD_DECISION, "target_allocation": -0.1},
    {**GOOD_DECISION, "target_allocation": "0.5"},
    {**GOOD_DECISION, "confidence": 2},
    {**GOOD_DECISION, "summary": "x" * 501},
    {**GOOD_DECISION, "hidden_reasoning": "must not be accepted"},
    {"target_allocation": 0.5},
    [GOOD_DECISION],
])
def test_invalid_decision_is_rejected(provider, bad_decision):
    with pytest.raises(ProviderOutputError, match="invalid trading decision"):
        request(provider, lambda req: httpx.Response(200, json=envelope(provider, bad_decision)))


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("status", [401, 429, 503])
def test_http_errors_are_sanitized(provider, status):
    with pytest.raises(ProviderError) as exc:
        request(provider, lambda req: httpx.Response(status, text="sensitive-provider-response"))
    assert f"HTTP {status}" in str(exc.value)
    assert "sensitive" not in str(exc.value)
    assert "test-key" not in str(exc.value)


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_transport_errors_are_sanitized(provider):
    def handler(req):
        raise httpx.ReadTimeout("secret-content", request=req)
    with pytest.raises(ProviderError, match="failed in transport") as exc:
        request(provider, handler)
    assert "secret-content" not in str(exc.value)


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("body", [[], {}, {"output": None, "content": None}])
def test_malformed_envelopes_are_rejected(provider, body):
    with pytest.raises(ProviderOutputError):
        request(provider, lambda req: httpx.Response(200, json=body))


def test_openai_refusal_and_incomplete_response():
    for body in [
        {"status": "incomplete", "output": []},
        {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "private response"}]}]},
        {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "not JSON"}]}]},
    ]:
        with pytest.raises(ProviderOutputError):
            request("openai", lambda req: httpx.Response(200, json=body))


def test_anthropic_requires_exactly_one_tool_decision():
    body = envelope("anthropic")
    body["content"] *= 2
    with pytest.raises(ProviderOutputError, match="exactly one"):
        request("anthropic", lambda req: httpx.Response(200, json=body))


@pytest.mark.parametrize("provider,env_name", [("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY")])
def test_credentials_reuse_environment_and_require_presence(monkeypatch, provider, env_name):
    monkeypatch.delenv(env_name, raising=False)
    with pytest.raises(ProviderConfigurationError, match=env_name):
        build_provider(config(provider, api_key=None))
    monkeypatch.setenv(env_name, "environment-test-key")
    adapter = build_provider(config(provider, api_key=None))
    assert "environment-test-key" not in repr(adapter)
    assert "test-key" not in repr(config(provider))


def test_exact_operator_model_allowlist_is_required():
    with pytest.raises(ProviderConfigurationError, match="allowlisted"):
        build_provider(config(model="unexpected-model"))
    with pytest.raises(ValidationError):
        config(allowed_models=())


def test_input_is_deeply_frozen():
    data = snapshot()
    with pytest.raises(ValidationError):
        data.symbol = "QQQ"
    with pytest.raises(ValidationError):
        data.candles[0].close = 200


@pytest.mark.parametrize("overrides", [
    {"high": 100},  # Below the observed close.
    {"low": 100.25},  # Above the observed open.
    {"high": 98, "low": 102},  # Inverted range.
    {"close": 102},
    {"open": 98},
    {"close": float("nan")},
    {"volume": float("inf")},
])
def test_provider_candle_rejects_impossible_market_observations(overrides):
    values = snapshot().candles[0].model_dump()
    with pytest.raises(ValidationError):
        Candle(**{**values, **overrides})


@pytest.mark.parametrize("timestamp", [datetime(2026, 1, 5, 9, 30), "2026-01-05T09:30:00"])
def test_provider_candle_requires_explicit_timezone(timestamp):
    values = snapshot().candles[0].model_dump()
    with pytest.raises(ValidationError, match="timezone"):
        Candle(**{**values, "timestamp": timestamp})


@pytest.mark.parametrize("timestamps", [
    ("2026-01-05T14:30:00Z", "2026-01-05T14:30:00Z"),
    ("2026-01-05T09:30:00-05:00", "2026-01-05T14:30:00Z"),
    ("2026-01-05T14:31:00Z", "2026-01-05T14:30:00Z"),
    ("2026-01-05T09:30:00-05:00", "2026-01-05T15:29:00+01:00"),
])
def test_provider_snapshot_rejects_duplicates_and_out_of_order_instants(timestamps):
    original = snapshot()
    candle_values = original.candles[0].model_dump()
    candles = tuple(Candle(**{**candle_values, "timestamp": stamp}) for stamp in timestamps)
    with pytest.raises(ValidationError, match="strictly increasing"):
        DecisionInput(symbol=original.symbol, strategy_markdown=original.strategy_markdown, candles=candles)


def test_provider_snapshot_normalizes_offsets_and_accepts_coherent_flat_bars():
    values = {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 0}
    candles = (
        Candle(timestamp="2026-01-05T09:30:00-05:00", **values),
        Candle(timestamp="2026-01-05T15:31:00+01:00", **values),
    )
    data = DecisionInput(symbol="SPY", strategy_markdown="# Flat market", candles=candles)
    assert [c.timestamp.isoformat() for c in data.candles] == ["2026-01-05T14:30:00+00:00", "2026-01-05T14:31:00+00:00"]
    assert data.model_dump(mode="json")["candles"][0]["timestamp"] == "2026-01-05T14:30:00Z"
