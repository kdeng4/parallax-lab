# Parallax Lab · API contract

All endpoints live below `/api/v1` on the FastAPI service. The Next.js app
proxies `/api/v1/*` to `API_BASE_URL` (default `http://127.0.0.1:8000`).
Amounts and prices are JSON numbers in USD. Timestamps use UTC ISO 8601.
Returns, drawdown and win rate are percentages (e.g. `2.5` means 2.5%).
Hosted replay requires real Tiingo adjusted daily candles. Synthetic data is an explicit local test fixture only. Stock prices are end-of-day, not intraday quotes.

## GET /health
`{"status":"ok","mode":"paper","storage":"sqlite"}`

## GET /catalog
`{"models":[{"id":"momentum","name":"Momentum","provider":"Local baseline","description":"..."}],"strategies":[{"id":"balanced","name":"Balanced momentum","description":"...","markdown":"...","version":"sha256..."}],"symbols":["SPY","QQQ","AAPL","MSFT","NVDA"],"data_source":"tiingo","interval":"1d","max_bars":252,"replay_available":false}`

Required baseline model IDs: `momentum`, `mean-reversion`, `buy-and-hold`.
Required strategy IDs: `balanced`, `conservative`, `responsive`.
When configured, the catalogue includes `openai:gpt-6-luna`, `openai:gpt-6.1-sol`
and `openai:gpt-6-astra`, plus private `openai` call-limit metadata. Provider IDs
are server-allowlisted; request credentials are never accepted. Catalogue symbols
come from the saved owner watchlist, rather than a closed five-symbol enum.

## GET /market/overview
Returns `stocks`, `macro`, server `as_of`, refresh cadence and indicator methodology. Each series includes its provider, observation date, retrieval time, next refresh eligibility and status. Missing values are null; stale values are explicitly labelled. Stocks follow the saved watchlist. No arbitrary URL or force-refresh parameter is supported. See [market-data audit](market-data-audit-2026-10-12.md) for rate budgets and calculation conventions. Responses are private/no-store. Starter Tiingo content remains transient; only entitled content may use the durable cache.

## GET /market/watchlist
Returns `{ "symbols": ["SPY", "TSLA"], "max_symbols": 10 }`.

## POST /market/watchlist
Input `{ "symbols": ["tsla", "AMD", "BRK.B"] }`. Saves normalized ticker preferences
only and returns the saved list. One to ten unique stock/ETF symbols are allowed;
syntax is validated and periods become provider dashes. Provider coverage is checked
by the next real data request, not invented from the symbol format. This write uses
the same owner authentication, CSRF protection and body limit as experiment creation.
Saving does not fetch market data or reset provider quotas.

## GET /experiments
`{"experiments":[ExperimentSummary]}` newest first.

## POST /experiments
Input: `{"name":"Optional user label","comparison":"models","model_ids":["momentum","mean-reversion","buy-and-hold"],"strategy_ids":["balanced"],"symbol":"SPY","initial_cash":100000,"bars":180}`.
`comparison` is `models` (one strategy, 2+ models) or `strategies` (one model, 2+ strategies).
Validate IDs, maximum participants, bounds, duplicate IDs, and a single varied factor.
Bounds: daily bars 60–252 (local fixtures 60–1440), local fixture seed 0–4294967295, cash 100–100000000 USD, name 1–100 trimmed characters (omit or null for automatic name).
Runs a bounded replay synchronously, persists atomically, returns
ExperimentDetail with HTTP 201. Uses the shared market cache; if needed, reserves quota and fetches a completed daily snapshot. Missing/stale/insufficient history returns 503 and creates no experiment.

Cloud input adds `decision_checkpoints` (1–3, default 2). The product of cloud
participants, strategies and checkpoints must not exceed six requests. All
participants share the checkpoint schedule after warm-up; daily equity is still
marked every bar. Cloud requests reserve durable quotas before I/O, perform no
automatic retries, and have a 60-second inference deadline. Quota/cooldown rejection
returns 429; provider failure returns 503 without saving a partial experiment.
Attempted calls may still be billed. Export metadata records checkpoint indices,
actual response model IDs and token usage; historical LLM replay is not prospective.

ExperimentSummary: `{"id":"uuid","name":"Morning momentum study","comparison":"models","symbol":"SPY","status":"completed","created_at":"...","data_source":"tiingo","seed":null,"bars":180,"initial_cash":100000,"participants":3,"best_return_pct":1.2}`.

## GET /experiments/{id}
ExperimentDetail = ExperimentSummary plus:
`{"strategy_name":"Balanced momentum","data_hash":"sha256...","costs":{"fee_bps":1.0,"slippage_bps":2.0},"runs":[Run],"candles":[{"timestamp":"...","open":500,"high":501,"low":499,"close":500.5,"volume":10000}],"events":[Event]}`.
`strategy_name` is the shared strategy name for model comparison or `Multiple strategies`.

Run: `{"id":"uuid","model_id":"momentum","model_name":"Momentum","provider":"Local baseline","strategy_id":"balanced","strategy_name":"Balanced momentum","strategy_version":"sha256...","return_pct":1.2,"equity":101200,"pnl":1200,"max_drawdown_pct":0.5,"sharpe":1.2,"win_rate_pct":60,"trade_count":8,"cash":80000,"position_qty":42,"equity_curve":[{"timestamp":"...","equity":100000}],"trades":[Trade]}`.
Sharpe may be null if insufficient variance/samples; document annualization and sell-fill win rate (each partial exit counts once). Long only, no leverage. Signals observed on bar close execute at NEXT bar open, with fees and slippage. Last-bar unfillable decisions remain unfilled and auditable.

Trade: `{"id":"uuid","timestamp":"...","side":"buy","quantity":10,"price":500.1,"fee":0.5,"realized_pnl":null}`.

Event: `{"id":"uuid","sequence":1,"timestamp":"...","type":"decision","run_id":"uuid","model_name":"Momentum","strategy_name":"Balanced momentum","message":"...","details":{}}`.
Types: `market`, `decision`, `order`, `fill`, `risk`, `completed`.
Record compact decision summaries and observable inputs, NOT hidden chain-of-thought.
Include before/after cash/positions in fills and link decision to order/fill via details.

## GET /experiments/{id}/events
Query: optional `run_id`, `type`, `from_time`, `to_time`, `limit` (1..2000, default 200), `offset` (>=0).
`{"events":[Event],"total":123,"limit":200,"offset":0}`.

## GET /experiments/{id}/export
Download full reproducibility JSON (detail). Include engine version, dataset hash,
strategy versions/contents, model configuration and cost assumptions in export metadata.

## Initial experience
Workspaces start empty. Hosted seeding is prohibited. Isolated local tests can explicitly enable fixtures and seeding. Local baselines are never represented as OpenAI or Anthropic models.

Errors use FastAPI `detail`. Unknown resources return 404; invalid inputs return 422.
Hosted deployments require private service authentication and verified approved-editor identity for writes. Streaming feeds, distributed execution and real-money trading are not implemented.
