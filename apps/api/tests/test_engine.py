from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from parallax_lab import engine
from parallax_lab.engine import Account, decide, metrics, run_experiment
from parallax_lab.market import data_hash, generate_candles
from parallax_lab.schemas import ExperimentInput
from parallax_lab.strategy import load_strategies


def test_dataset_is_deterministic_immutable_and_prefix_stable():
    short = generate_candles("SPY", 42, 60)
    assert short == generate_candles("SPY", 42, 180)[:60]
    assert data_hash(short) == data_hash(generate_candles("SPY", 42, 60))
    assert short != generate_candles("SPY", 43, 60)
    for candle in short:
        assert 0 < candle.low <= min(candle.open, candle.close) <= max(candle.open, candle.close) <= candle.high
    with pytest.raises(FrozenInstanceError):
        short[0].close = 1


def test_fill_fee_slippage_cash_conservation_and_closed_profit():
    account = Account(Decimal("1000"))
    buy = account.fill_target(0.7, 10, 0.7)
    assert buy["side"] == "buy"
    assert buy["price"] == pytest.approx(10.002)
    assert buy["fee"] == pytest.approx(buy["quantity"] * buy["price"] * 0.0001, abs=1e-8)
    assert float(account.cash) == pytest.approx(1000 - buy["quantity"] * buy["price"] - buy["fee"], abs=1e-8)
    assert float(account.quantity * Decimal("10") / account.equity(10)) <= 0.7
    sell = account.fill_target(0, 12, 0.7)
    assert sell["price"] == pytest.approx(11.9976)
    assert sell["quantity"] == buy["quantity"]
    assert account.quantity == 0 and account.average_cost == 0
    assert sell["realized_pnl"] == pytest.approx(float(account.cash) - 1000, abs=1e-8)


def test_partial_sales_keep_fee_inclusive_average_cost():
    account = Account(Decimal("1000"))
    account.fill_target(0.7, 10, 0.7)
    basis = account.average_cost
    partial = account.fill_target(0.2, 12, 0.7)
    assert partial["side"] == "sell" and account.quantity > 0
    assert account.average_cost == basis
    expected = Decimal(str(partial["quantity"])) * (Decimal("11.9976") * Decimal("0.9999") - basis)
    assert partial["realized_pnl"] == pytest.approx(float(expected), abs=1e-8)


@pytest.mark.parametrize("target,cap", [(-0.1, 0.7), (0.8, 0.7), (1.1, 1.1)])
def test_account_rejects_short_leverage_and_risk_cap_violation(target, cap):
    with pytest.raises(ValueError):
        Account(Decimal("1000")).fill_target(target, 10, cap)


def test_flat_price_trading_loses_only_costs_without_leverage():
    account = Account(Decimal("1000"))
    account.fill_target(1, 10, 1)
    assert account.cash >= 0
    assert account.equity(10) < 1000
    account.fill_target(0, 10, 1)
    assert 999 < account.cash < 1000


def test_next_open_execution_and_last_bar_order_is_unfilled(monkeypatch):
    candles = list(generate_candles("SPY", 42, 60))
    candles[0] = replace(candles[0], open=100, close=100, high=101, low=99)
    candles[1] = replace(candles[1], open=200, close=200, high=201, low=199)
    monkeypatch.setattr(engine, "generate_candles", lambda *args: tuple(candles))
    seen = []
    def observed_only(model, strategy, history, allocation):
        seen.append(history)
        target = strategy.config.max_allocation if len(history) == 1 else allocation
        if len(history) == 60:
            target = 0
        return target, "Test observable decision", {"observed_bars": len(history)}
    monkeypatch.setattr(engine, "decide", observed_only)
    result = run_experiment(ExperimentInput(bars=60, model_ids=["momentum", "buy-and-hold"]))
    assert len(seen) == 120
    for index, prefix in enumerate(seen):
        assert prefix == tuple(candles[:index // 2 + 1])
    for run in result["runs"]:
        assert len(run["trades"]) == 1
        assert run["trades"][0]["timestamp"] == candles[1].timestamp
        assert run["trades"][0]["price"] == pytest.approx(200.04)
        assert run["position_qty"] > 0
    unfilled = [e for e in result["events"] if e["details"].get("reason") == "end_of_dataset"]
    assert len(unfilled) == 2
    for event in (e for e in result["events"] if e["type"] == "fill"):
        assert event["details"]["execution_bar_index"] == event["details"]["observed_bar_index"] + 1


def test_replay_determinism_fair_inputs_and_audit_links():
    request = ExperimentInput()
    first = run_experiment(request, "same-experiment")
    second = run_experiment(request, "same-experiment")
    first.pop("created_at")
    second.pop("created_at")
    assert first == second
    assert len(set(run["strategy_version"] for run in first["runs"])) == 1
    decisions = [event for event in first["events"] if event["type"] == "decision"]
    for run in first["runs"]:
        inputs = [event["details"]["observable_inputs"] for event in decisions if event["run_id"] == run["id"]]
        assert [item["close"] for item in inputs] == [c["close"] for c in first["candles"]]
        assert [item["observed_bars"] for item in inputs] == list(range(1, 181))
        assert run["equity"] == pytest.approx(run["cash"] + run["position_qty"] * first["candles"][-1]["close"], abs=1e-5)
        assert run["pnl"] == pytest.approx(run["equity"] - request.initial_cash)
    events = first["events"]
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    assert [e["timestamp"] for e in events] == sorted(e["timestamp"] for e in events)
    by_id = {event["id"]: event for event in events}
    for event in (e for e in events if e["type"] == "fill"):
        details = event["details"]
        assert by_id[details["decision_id"]]["sequence"] < by_id[details["order_id"]]["sequence"] < event["sequence"]
        assert details["after"]["cash"] >= 0 and details["after"]["position_qty"] >= 0


def test_future_candles_do_not_change_prior_decisions_or_fills(monkeypatch):
    original = generate_candles("SPY", 42, 60)
    request = ExperimentInput(bars=60)
    first = run_experiment(request, "fixed")
    modified = original[:30] + tuple(replace(c, open=c.open * 2, close=c.close * 2, high=c.high * 2, low=c.low * 2) for c in original[30:])
    monkeypatch.setattr(engine, "generate_candles", lambda *args: modified)
    second = run_experiment(request, "fixed")
    cutoff = original[30].timestamp
    assert [e for e in first["events"] if e["timestamp"] < cutoff] == [e for e in second["events"] if e["timestamp"] < cutoff]


def test_metrics_drawdown_closed_trade_win_rate_and_zero_variance():
    result = metrics([{"equity": x} for x in [100, 110, 88, 99]],
                     [{"side": "buy", "realized_pnl": None}, {"side": "sell", "realized_pnl": 5}, {"side": "sell", "realized_pnl": -2}], 100)
    assert result["max_drawdown_pct"] == 20
    assert result["return_pct"] == -1
    assert result["win_rate_pct"] == 50
    assert result["sharpe"] is not None
    flat = metrics([{"equity": 100}] * 3, [], 100)
    assert flat["sharpe"] is None and flat["win_rate_pct"] == 0


def test_markdown_config_versions_and_factor_comparison():
    strategies = load_strategies()
    assert len({s.version for s in strategies.values()}) == 3
    assert all(len(s.version) == 64 for s in strategies.values())
    result = run_experiment(ExperimentInput(comparison="strategies", model_ids=["momentum"], strategy_ids=list(strategies), bars=60))
    assert result["strategy_name"] == "Multiple strategies"
    assert len(result["runs"]) == 3
    assert {run["model_id"] for run in result["runs"]} == {"momentum"}
