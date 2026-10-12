# Patrick API

A working local paper-trading research API built with FastAPI, Pydantic, Python
3.12, and SQLite. The deterministic replay uses synthetic one-minute OHLCV data
and three real local algorithms: momentum, mean reversion, and buy & hold.
No endpoint connects to a broker or spends provider credits.

## Run

From this directory, with Python 3.12 and uv installed:

```sh
UV_CACHE_DIR=/workspace/.cache/uv uv sync --frozen --group dev
UV_CACHE_DIR=/workspace/.cache/uv uv run uvicorn patrick.main:app --host 127.0.0.1 --port 8000
```

Outside the cloud workspace, `UV_CACHE_DIR` can be omitted. API docs are at
`http://127.0.0.1:8000/docs`. The Next.js application proxies `/api/v1/*` to this
service. Use `--host 0.0.0.0` only when container networking requires it.

`PATRICK_DATABASE_URL` defaults to `sqlite:///./.data/patrick.db` (relative to
the process working directory). An absolute path uses four slashes, e.g.
`sqlite:////tmp/patrick.db`. Only SQLite is supported in this milestone.
`PATRICK_SEED_DEMO=0` disables the first-start example. The default seed has a
stable ID, so restarting never duplicates it. A database file contains all runs
and audit records; protect it as application data and use SQLite's backup API
for a consistent backup while the service is running.

```sh
curl http://127.0.0.1:8000/api/v1/health
curl -X POST http://127.0.0.1:8000/api/v1/experiments \
  -H 'Content-Type: application/json' \
  -d '{"name":"Baseline study","comparison":"models","model_ids":["momentum","mean-reversion","buy-and-hold"],"strategy_ids":["balanced"],"symbol":"SPY","seed":42,"initial_cash":100000,"bars":180}'
```

Model comparisons require one strategy and two or three models. Strategy
comparisons require one model and two or three strategies. Inputs enforce a
single changed factor, known IDs, unique participants, 60–1,440 candles,
initial capital of $100–$100 million, and an unsigned 32-bit seed.

## Replay and accounting

- Every participant receives the same immutable dataset and only its observed
  prefix at each decision. A close decision executes at the next candle's open.
  A final close decision with an order remains explicitly unfilled.
- All trading is long only, without borrowing. Markdown strategy files contain
  validated JSON parameters for the observation window, threshold, allocation
  cap, and minimum rebalance difference. Baseline algorithms interpret those
  numeric parameters; they do not claim to understand arbitrary Markdown prose.
- Fractional quantities round down to six decimals. Decimal cash and fee-inclusive
  average-cost accounting apply 1 basis point of commission and 2 basis points of
  adverse slippage on both buys and sells. The engine caps new allocations and
  enforces available cash. Passive market drift may exceed the target between
  rebalances. There is no margin, short selling, or market liquidity simulation.
- Final equity marks open positions to the final close; it does not force
  liquidation. Returns include unrealized gains and all charged costs. Drawdown
  includes initial capital and every close. Win rate is the percentage of sell
  fills with positive realized P&L; partial exits each count once. It is 0 when
  there are no sells.
- Sharpe uses one-minute equity returns, sample standard deviation, zero
  risk-free rate, and `sqrt(252 * 390)` annualization. It is null for inadequate
  samples or variance. Annualized ratios on a short synthetic trajectory are
  illustrative, not reliable predictions of investment performance.

The synthetic timeline starts at 2026-01-05 14:30 UTC and runs continuously;
it does not model exchange calendars, overnight sessions, halts, splits,
dividends, liquidity, or quote timing. A seed produces stable prefixes for each
symbol in the recorded Python/engine version. Repeating a configuration reproduces
the same data, decisions, trades, and metrics; new experiment IDs and creation
times intentionally differ. Export JSON records candles, dataset hash, complete
strategy Markdown and hashes, model versions, configuration, execution costs,
Python version, and metric definitions.

Experiments and their events commit in one SQLite transaction. Audit rows cannot
be updated or deleted through SQL while the protective triggers remain enabled;
this is application immutability, not cryptographic tamper resistance against a
database owner. Each decision links to orders and fills. Fills include before/after
account snapshots. Events contain concise observable summaries, not hidden model
reasoning. Filtering supports run, type, inclusive UTC-aware time bounds with
microsecond precision, limit, and offset. Shared market events have a null run ID.

## Optional provider adapters

`patrick.providers` implements the OpenAI Responses API and Anthropic Messages
API with strict validated target allocations, confidence, and concise summaries.
Provider snapshots validate coherent OHLC prices, require timezone-aware candle
timestamps, normalize them to UTC, and enforce strictly increasing unique instants.
They are separately tested infrastructure, not selectable replay participants.
Creating an adapter requires an explicit allowed model ID and either an injected
secret or `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` in the server environment.
Model names and API capabilities must be selected by the operator. Keys never
belong in a strategy, export, or browser. No live provider calls were used for
validation, so real provider compatibility remains an integration check.

```python
from patrick.providers import ProviderConfig, build_provider

provider = build_provider(ProviderConfig(
    provider="openai",
    model="operator-selected-model-id",
    allowed_models=("operator-selected-model-id",),
))
# await provider.decide(frozen_observable_snapshot)
```

## Verify

```sh
UV_CACHE_DIR=/workspace/.cache/uv uv run pytest
```

Tests cover deterministic fair inputs, future-data isolation, next-open fills,
costs and average-cost P&L, cash and allocation bounds, metric definitions,
atomic persistence, append-only logs, export, restart/seed idempotency, strict API
validation, exact time filtering, and mocked provider success and failure paths.

This service is a single-user local workbench. Authentication, authorization,
live data, distributed workers, PostgreSQL, broker execution, external experiment
tracking, and production operations belong to later milestones. Keep the local
API on loopback; the production access layer must be added before shared hosting.
