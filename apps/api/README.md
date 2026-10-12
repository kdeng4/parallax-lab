# Parallax Lab API

FastAPI serves the private paper-trading research API. Hosted deployments use
Neon PostgreSQL and a server-only bearer token. Local development uses SQLite.
The Next.js application authorizes the owner before forwarding private requests.

## Run locally

From this directory:

```bash
uv sync --frozen --group dev
uv run --frozen uvicorn parallax_lab.main:app --host 127.0.0.1 --port 8000
```

API docs are at `http://127.0.0.1:8000/docs`. Keep local services on loopback.
`PARALLAX_DATABASE_URL` defaults to `sqlite:///./.data/parallax-lab.db`.
The legacy local database path and environment name remain supported to preserve
existing research. PostgreSQL uses `postgresql://` or `postgres://` URLs; deploy
its versioned migrations separately with owner credentials.

Every application startup leaves a new workspace empty. Sample generation and
its old environment switches have been removed. Browser tests create fixtures
explicitly in a guarded temporary SQLite directory.

## Data and execution

Real replays use completed daily Tiingo sessions, identical frozen snapshots,
and local momentum, mean-reversion or buy-and-hold algorithms. Source timestamps,
hashes, strategy Markdown versions and execution assumptions are exported.
Synthetic minute data is an explicit local test mode and is ignored on Vercel.
Missing real history never falls back to synthetic observations.

A decision at close can fill only at the next open. Paper accounts are long-only,
with independent cash, allocation caps, six-decimal quantities, commissions and
adverse slippage. Sharpe uses the dataset interval and is null when variance or
observations are insufficient. A final unfilled order creates no trade.

Completed experiments and sequenced audit events commit together. Stored research
is immutable. Event queries use timezone-aware inclusive bounds and pagination.
The public projection excludes private settings, quantities, prices, news and
full audit messages, reads at most twenty candidate summaries, and skips fetching
audit logs. A separate data entitlement is required before research is published.

Tiingo Starter responses remain transient. Persistent experiments require a
licence permitting storage of source and derived data. All external feeds share
durable request budgets, leases and cooldowns; missing credentials stay explicit.
See [deployment](../../docs/deployment.md) for provider configuration and limits.

## Provider adapters

OpenAI and Anthropic decision adapters are retained for the next integration.
The experiment API does not call them yet. Model allowlists, validated outputs,
sanitized error messages and identity-only authentication are required before
activation. Provider keys never belong in request payloads, exports or browser
bundles. No broker orders are implemented.

## Validation

```bash
uv run --frozen --group dev pytest --cov=parallax_lab --cov-branch --cov-report=term-missing --cov-fail-under=90
```

Set `PARALLAX_TEST_DATABASE_URL` only to a disposable PostgreSQL database to run
its integration contract. CI provides an isolated PostgreSQL service. SQLite,
market transports and cloud-provider tests use isolated local or mocked inputs;
they do not require production credentials.

See the [API contract](../../docs/api-contract.md) and
[testing guide](../../docs/testing.md) for current endpoint and acceptance rules.
