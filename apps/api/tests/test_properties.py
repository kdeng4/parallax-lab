"""Invariants that must hold across varied paper orders and replay inputs."""

import math
from decimal import Decimal

from hypothesis import given, settings, strategies as st

from parallax_lab.engine import Account, FEE_BPS, SLIPPAGE_BPS, run_experiment
from parallax_lab.schemas import ExperimentInput


D = Decimal
FEE_RATE = D(str(FEE_BPS)) / 10_000
SLIPPAGE_RATE = D(str(SLIPPAGE_BPS)) / 10_000
REPORTED_PRECISION = D("0.000000011")
LEDGER_PRECISION = D("0.00000000000000000001")


def ledger_tolerance(value: Decimal) -> Decimal:
    """Allow Decimal's finite 28-digit division precision at large notionals."""
    return max(LEDGER_PRECISION, abs(value) * D("1e-26"))


@settings(max_examples=80, deadline=None)
@given(
    initial_cents=st.integers(min_value=10_000, max_value=1_000_000),
    orders=st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=1_000),
            st.integers(min_value=1, max_value=100_000),
            st.integers(min_value=1, max_value=1_000),
        ),
        min_size=1,
        max_size=15,
    ),
)
def test_varied_orders_conserve_cash_position_and_fee_inclusive_basis(initial_cents, orders):
    account = Account(D(initial_cents) / 100)

    for target_parts, opening_cents, cap_parts in orders:
        target = min(target_parts, cap_parts) / 1_000
        cap = cap_parts / 1_000
        opening = D(opening_cents) / 100
        before_cash = account.cash
        before_quantity = account.quantity
        before_basis = account.average_cost
        before_equity = account.equity(opening)

        fill = account.fill_target(target, opening, cap)
        assert account.cash >= 0
        assert account.quantity >= 0
        assert account.quantity.as_tuple().exponent >= -6
        if fill is None:
            assert (account.cash, account.quantity, account.average_cost) == (
                before_cash, before_quantity, before_basis
            )
            continue

        side = fill["side"]
        quantity = abs(account.quantity - before_quantity)
        assert quantity > 0
        reported_quantity_tolerance = max(D("0.000001"), D(str(math.ulp(float(quantity)))))
        assert abs(D(str(fill["quantity"])) - quantity) <= reported_quantity_tolerance
        execution_price = opening * (1 + SLIPPAGE_RATE if side == "buy" else 1 - SLIPPAGE_RATE)
        fee = quantity * execution_price * FEE_RATE
        assert abs(D(str(fill["price"])) - execution_price) <= REPORTED_PRECISION
        assert abs(D(str(fill["fee"])) - fee) <= REPORTED_PRECISION

        if side == "buy":
            assert account.quantity == before_quantity + quantity
            expected_cash = before_cash - quantity * execution_price - fee
            assert abs(account.cash - expected_cash) <= ledger_tolerance(expected_cash)
            total_basis = before_basis * before_quantity + quantity * execution_price + fee
            assert abs(account.average_cost * account.quantity - total_basis) <= ledger_tolerance(total_basis)
            assert fill["realized_pnl"] is None
        else:
            assert account.quantity == before_quantity - quantity
            expected_cash = before_cash + quantity * execution_price - fee
            assert abs(account.cash - expected_cash) <= ledger_tolerance(expected_cash)
            assert account.average_cost == (before_basis if account.quantity else 0)
            realized = quantity * (execution_price - before_basis) - fee
            # The public JSON number is a float; at large notionals its ULP
            # can exceed the requested eight decimal places.
            reported_tolerance = max(REPORTED_PRECISION, D(str(math.ulp(float(realized)))))
            assert abs(D(str(fill["realized_pnl"])) - realized) <= reported_tolerance

        # A fill at the same market mark cannot create equity: spread and fees are costs.
        expected_equity = before_equity - quantity * opening * SLIPPAGE_RATE - fee
        assert abs(account.equity(opening) - expected_equity) <= ledger_tolerance(expected_equity)
        marked_allocation = account.quantity * opening / account.equity(opening)
        assert marked_allocation <= D(str(cap)) + D("0.000000001")
        assert fill["before"]["cash"] == round(float(before_cash), 6)
        assert fill["after"] == account.snapshot()
        if account.quantity == 0:
            assert account.average_cost == 0


@settings(max_examples=15, deadline=None)
@given(
    seed=st.integers(min_value=0, max_value=2**32 - 1),
    bars=st.integers(min_value=60, max_value=120),
    symbol=st.sampled_from(["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]),
)
def test_replay_fills_link_to_prior_decisions_and_next_market_open(seed, bars, symbol):
    request = ExperimentInput(seed=seed, bars=bars, symbol=symbol)
    result = run_experiment(request, f"invariant-{seed}-{bars}-{symbol}")
    candles = result["candles"]
    events = {event["id"]: event for event in result["events"]}

    for run in result["runs"]:
        fills = [event for event in result["events"] if event["type"] == "fill" and event["run_id"] == run["id"]]
        assert len(fills) == len(run["trades"])
        prior_account = {"cash": request.initial_cash, "position_qty": 0.0, "average_cost": 0.0}
        for fill, trade in zip(fills, run["trades"]):
            details = fill["details"]
            decision = events[details["decision_id"]]
            order = events[details["order_id"]]
            observed_index = details["observed_bar_index"]
            execution_index = details["execution_bar_index"]
            assert execution_index == observed_index + 1
            assert fill["timestamp"] == trade["timestamp"] == candles[execution_index]["timestamp"]
            assert decision["sequence"] < order["sequence"] < fill["sequence"]
            assert decision["run_id"] == order["run_id"] == fill["run_id"]
            assert decision["details"]["bar_index"] == order["details"]["bar_index"] == observed_index
            assert decision["details"]["target_allocation"] == order["details"]["target_allocation"]
            assert details["before"] == prior_account
            expected_price = candles[execution_index]["open"] * (
                1 + float(SLIPPAGE_RATE) if trade["side"] == "buy" else 1 - float(SLIPPAGE_RATE)
            )
            assert abs(trade["price"] - expected_price) < 0.00000002
            prior_account = details["after"]
        assert run["cash"] == prior_account["cash"]
        assert run["position_qty"] == prior_account["position_qty"]
