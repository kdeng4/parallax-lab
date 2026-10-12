"""Deterministic long-only replay with next-open execution and auditable accounts."""

import math
import statistics
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from uuid import NAMESPACE_URL, uuid4, uuid5

from . import ENGINE_VERSION
from .market import Candle, close_time, data_hash, generate_candles
from .schemas import ExperimentInput
from .strategy import Strategy, load_strategies

FEE_BPS = 1.0
SLIPPAGE_BPS = 2.0
MINUTES_PER_YEAR = 252 * 390
D = Decimal
PRECISION = D("0.000001")

MODELS = {
    "momentum": {"id": "momentum", "name": "Momentum", "provider": "Local baseline", "description": "Follows observed price momentum over the strategy window."},
    "mean-reversion": {"id": "mean-reversion", "name": "Mean reversion", "provider": "Local baseline", "description": "Buys observed weakness relative to the trailing mean."},
    "buy-and-hold": {"id": "buy-and-hold", "name": "Buy & hold", "provider": "Local baseline", "description": "Maintains the strategy allocation as a passive control."},
}


def number(value: Decimal | float, digits: int = 6) -> float:
    return round(float(value), digits)


@dataclass
class Account:
    cash: Decimal
    quantity: Decimal = D(0)
    average_cost: Decimal = D(0)

    def equity(self, price: float | Decimal) -> Decimal:
        return self.cash + self.quantity * D(str(price))

    def snapshot(self) -> dict:
        return {"cash": number(self.cash), "position_qty": number(self.quantity), "average_cost": number(self.average_cost)}

    def fill_target(self, target: float, opening: float, cap: float) -> dict | None:
        """Solve an allocation target under cash, position, fee and slippage limits.

        Decimal accounting tracks fractional shares and fee-inclusive average cost.
        The desired position is priced with buy-side costs, a conservative cap.
        Existing passive price drift may exceed a target until this next-open fill.
        """
        if not (0 <= target <= cap <= 1):
            raise ValueError("Allocation must respect the long-only risk cap")
        mark = D(str(opening))
        if mark <= 0:
            raise ValueError("Opening price must be positive")
        fee_rate, slip_rate = D(str(FEE_BPS)) / 10_000, D(str(SLIPPAGE_BPS)) / 10_000
        buy_price = mark * (1 + slip_rate)
        desired = (D(str(target)) * self.equity(mark) / (buy_price * (1 + fee_rate))).quantize(PRECISION, rounding=ROUND_DOWN)
        delta = desired - self.quantity
        if abs(delta) < PRECISION:
            return None
        before = self.snapshot()
        if delta > 0:
            side, price = "buy", buy_price
            affordable = (self.cash / (price * (1 + fee_rate))).quantize(PRECISION, rounding=ROUND_DOWN)
            quantity = min(delta, affordable)
            if quantity <= 0:
                return None
            fee = quantity * price * fee_rate
            cost = quantity * price + fee
            self.average_cost = (self.average_cost * self.quantity + cost) / (self.quantity + quantity)
            self.cash -= cost
            self.quantity += quantity
            realized = None
        else:
            side, price = "sell", mark * (1 - slip_rate)
            quantity = min(-delta, self.quantity)
            fee = quantity * price * fee_rate
            proceeds = quantity * price - fee
            realized = proceeds - self.average_cost * quantity
            self.cash += proceeds
            self.quantity -= quantity
            if self.quantity == 0:
                self.average_cost = D(0)
        assert self.cash >= 0 and self.quantity >= 0
        return {"side": side, "quantity": number(quantity), "price": number(price, 8), "fee": number(fee, 8),
                "realized_pnl": number(realized, 8) if realized is not None else None,
                "before": before, "after": self.snapshot()}


def decide(model_id: str, strategy: Strategy, observed: tuple[Candle, ...], current_allocation: float) -> tuple[float, str, dict]:
    """Only the immutable prefix ending at the current close is accessible."""
    config = strategy.config
    observable = {"observed_bars": len(observed), "as_of": close_time(observed[-1]), "close": observed[-1].close,
                  "lookback": config.lookback, "threshold": config.threshold}
    if model_id == "buy-and-hold":
        return config.max_allocation, "Maintain the configured passive allocation.", observable
    if len(observed) <= config.lookback:
        return 0.0, "Collecting the required observation window.", observable
    trailing = observed[-config.lookback:]
    if model_id == "momentum":
        signal = observed[-1].close / observed[-config.lookback - 1].close - 1
        observable["trailing_return"] = signal
        target = config.max_allocation if signal > config.threshold else 0 if signal < -config.threshold else current_allocation
        summary = "Follow the observed trailing return; keep exposure inside the strategy limit."
    elif model_id == "mean-reversion":
        mean = statistics.fmean(c.close for c in trailing)
        signal = observed[-1].close / mean - 1
        observable.update({"trailing_mean": mean, "deviation": signal})
        target = config.max_allocation if signal < -config.threshold else 0 if signal > config.threshold else current_allocation
        summary = "Compare the observed close with its trailing mean."
    else:
        raise ValueError(f"Unknown local model: {model_id}")
    return min(target, config.max_allocation), summary, observable


@dataclass
class RunState:
    id: str
    model_id: str
    strategy: Strategy
    account: Account
    curve: list[dict] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    pending: dict | None = None


def metrics(curve: list[dict], trades: list[dict], initial_cash: float) -> dict:
    equities = [p["equity"] for p in curve]
    peak, drawdown = equities[0], 0.0
    for equity in equities:
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
    returns = [b / a - 1 for a, b in zip(equities, equities[1:])]
    stdev = statistics.stdev(returns) if len(returns) >= 2 else 0
    sharpe = statistics.fmean(returns) / stdev * math.sqrt(MINUTES_PER_YEAR) if stdev > 1e-12 else None
    sales = [t["realized_pnl"] for t in trades if t["side"] == "sell"]
    return {"return_pct": number((equities[-1] / initial_cash - 1) * 100),
            "equity": number(equities[-1]), "pnl": number(equities[-1] - initial_cash),
            "max_drawdown_pct": number(drawdown * 100), "sharpe": number(sharpe) if sharpe is not None else None,
            "win_rate_pct": number(sum(p > 0 for p in sales) / len(sales) * 100) if sales else 0.0,
            "trade_count": len(trades)}


def run_experiment(request: ExperimentInput, experiment_id: str | None = None) -> dict:
    experiment_id = experiment_id or str(uuid4())
    strategies = load_strategies()
    candles = generate_candles(request.symbol, request.seed, request.bars)
    events: list[dict] = []

    def identifier(key: str) -> str:
        # Historical UUID namespace is part of the replay identity; keep it stable.
        return str(uuid5(NAMESPACE_URL, f"patrick:{experiment_id}:{key}"))

    states = [RunState(identifier(f"run:{model}:{strategy}"), model, strategies[strategy], Account(D(str(request.initial_cash))))
              for model in request.model_ids for strategy in request.strategy_ids]

    def emit(timestamp: str, event_type: str, state: RunState | None, message: str, details: dict) -> str:
        event_id = identifier(f"event:{len(events)}")
        events.append({"id": event_id, "sequence": 0, "timestamp": timestamp, "type": event_type,
                       "run_id": state.id if state else None, "model_name": MODELS[state.model_id]["name"] if state else "Market data",
                       "strategy_name": state.strategy.name if state else "Shared input", "message": message, "details": details})
        return event_id

    for state in states:
        state.curve.append({"timestamp": candles[0].timestamp, "equity": request.initial_cash})
    for index, candle in enumerate(candles):
        # Orders created at the preceding close are the only executable orders.
        for state in states:
            if state.pending is not None:
                pending = state.pending
                filled = state.account.fill_target(pending["target_allocation"], candle.open, state.strategy.config.max_allocation)
                if filled:
                    trade = {"id": identifier(f"trade:{state.id}:{len(state.trades)}"), "timestamp": candle.timestamp,
                             **{k: v for k, v in filled.items() if k not in ("before", "after")}}
                    state.trades.append(trade)
                    emit(candle.timestamp, "fill", state, f"Paper {trade['side']}: {trade['quantity']:.6f} shares at ${trade['price']:.4f}.",
                         {**filled, "trade_id": trade["id"], "decision_id": pending["decision_id"], "order_id": pending["order_id"],
                          "observed_bar_index": pending["bar_index"], "execution_bar_index": index})
                else:
                    emit(candle.timestamp, "risk", state, "Order had no executable quantity after account limits.", pending)
                state.pending = None
        emit(close_time(candle), "market", None, f"{request.symbol} synthetic one-minute candle closed.",
             {"bar_index": index, "symbol": request.symbol, "source": "synthetic", "candle": candle.as_dict()})
        for state in states:
            equity = state.account.equity(candle.close)
            allocation = float(state.account.quantity * D(str(candle.close)) / equity)
            target, summary, observable = decide(state.model_id, state.strategy, candles[:index + 1], allocation)
            decision_id = emit(close_time(candle), "decision", state, summary,
                               {"target_allocation": target, "current_allocation": allocation, "observable_inputs": observable,
                                "model_id": state.model_id, "strategy_version": state.strategy.version, "bar_index": index})
            if abs(target - allocation) >= state.strategy.config.rebalance_threshold:
                order_details = {"target_allocation": target, "decision_id": decision_id, "bar_index": index,
                                 "execution_rule": "next_bar_open", "max_allocation": state.strategy.config.max_allocation}
                order_id = emit(close_time(candle), "order", state, f"Queue paper allocation target of {target * 100:.0f}% for the next open.", order_details)
                state.pending = {**order_details, "order_id": order_id}
            state.curve.append({"timestamp": close_time(candle), "equity": number(equity)})

    runs = []
    for state in states:
        if state.pending:
            emit(close_time(candles[-1]), "risk", state, "Last-bar order left unfilled: no next market open is available.",
                 {**state.pending, "status": "unfilled", "reason": "end_of_dataset"})
        run_metrics = metrics(state.curve, state.trades, request.initial_cash)
        runs.append({"id": state.id, "model_id": state.model_id, "model_name": MODELS[state.model_id]["name"],
                     "provider": MODELS[state.model_id]["provider"], "strategy_id": state.strategy.id,
                     "strategy_name": state.strategy.name, "strategy_version": state.strategy.version,
                     **run_metrics, "cash": number(state.account.cash), "position_qty": number(state.account.quantity),
                     "equity_curve": state.curve, "trades": state.trades})
        emit(close_time(candles[-1]), "completed", state, f"Replay completed with {len(state.trades)} paper fills.",
             {**run_metrics, "final_account": state.account.snapshot(), "mark_price": candles[-1].close})
    events.sort(key=lambda event: event["timestamp"])
    for sequence, event in enumerate(events, 1):
        event["sequence"] = sequence
    return {"id": experiment_id, "name": request.name or f"{request.symbol} · {'model' if request.comparison == 'models' else 'strategy'} comparison",
            "comparison": request.comparison, "symbol": request.symbol, "status": "completed", "created_at": datetime.now(UTC).isoformat(),
            "data_source": "synthetic", "seed": request.seed, "bars": request.bars, "initial_cash": request.initial_cash,
            "participants": len(runs), "best_return_pct": max(r["return_pct"] for r in runs),
            "strategy_name": strategies[request.strategy_ids[0]].name if len(request.strategy_ids) == 1 else "Multiple strategies",
            "data_hash": data_hash(candles), "costs": {"fee_bps": FEE_BPS, "slippage_bps": SLIPPAGE_BPS},
            "runs": runs, "candles": [c.as_dict() for c in candles], "events": events,
            "metadata": {"engine_version": ENGINE_VERSION, "python_version": sys.version.split()[0], "request": request.model_dump(), "dataset": {"source": "synthetic", "generator": "parallax-lab-v1", "hash": data_hash(candles)},
                         "strategies": [strategies[s].model_dump() for s in request.strategy_ids],
                         "models": [{**MODELS[m], "implementation_version": ENGINE_VERSION} for m in request.model_ids],
                         "execution": {"signal": "bar_close", "fill": "next_bar_open", "position_mode": "long_only", "leverage": 1,
                                       "fee_bps": FEE_BPS, "slippage_bps": SLIPPAGE_BPS, "fractional_share_precision": 6,
                                       "final_position": "marked_to_last_close_not_liquidated"},
                         "metrics": {"sharpe": "sample standard deviation of one-minute equity returns; zero risk-free rate; sqrt(252*390) annualization; illustrative on short synthetic paths",
                                     "win_rate": "percentage of sell fills with positive fee-inclusive realized P&L; partial exits each count once; 0 when no sells",
                                     "drawdown": "peak-to-trough equity decline including initial capital; marked at every candle close"}}}
