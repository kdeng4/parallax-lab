# Parallax Lab

**A paper-trading research workbench for controlled model and strategy experiments.**

Parallax Lab runs independent trading algorithms against the same immutable market
snapshot, records every decision and fill, and makes results comparable in one
minimal interface: **real published market data, local baseline algorithms,
simulated funds.** Bank of Canada currency/rate indicators are keyless. Tiingo
daily stock history requires a free personal API token; missing data stays empty.
See the [market-data audit and setup](docs/market-data-audit-2026-10-12.md).

The phased [implementation plan](docs/implementation-plan.md) maps the full
design to live data, cloud model execution, distributed workers and production
operations. [Architecture](docs/architecture.md) and the
[API contract](docs/api-contract.md) document the current boundaries.
See [validation results](docs/validation.md) for the checks executed in this environment.
See [deployment requirements](docs/deployment.md) before connecting a Vercel
frontend to a hosted API.

## Public dashboard and owner workspace

The homepage exposes agent names and eligible published performance/activity only.
All market/news data, settings and experiments live under `/workspace`, protected
by the owner's GitHub identity through Neon Auth, matched by immutable user ID. See
[deployment setup](docs/deployment.md) for OAuth and provider credentials.

The public chart compares indexed agent portfolios with matched SPY sessions.
It stays empty until real research with suitable publication rights exists.
Tiingo Starter data is transient and cannot be saved in immutable research;
persistent replays and public curves require verified data entitlements.
News/event adapters are implemented, but current baseline algorithms do not use
news or run continuously. Missing credentials produce explicit connection states.

## What is implemented

- Model comparison with a fixed strategy; strategy comparison with a fixed model.
- Deterministic OHLCV snapshots shared by all participants, with dataset hashes.
- Daily stock indicators (SMA, RSI, MACD) and attributed currency/rate data.
- Persistent cross-worker request budgets and provider cooldowns in Neon.
- Momentum, mean-reversion and buy-and-hold reference algorithms.
- Versioned Markdown strategy configurations.
- Independent paper accounts, next-bar fills, fees, slippage and long-only limits.
- Equity curves, returns, drawdown, Sharpe and realized sell-fill win rates.
- Persistent experiment history, sequenced audit trails, filtering and JSON export.
- A responsive Next.js UI and a validated FastAPI HTTP API.

No live broker orders are implemented. Intraday streaming, cloud-model experiment
execution, multi-user accounts, NATS workers, MLflow and Kubernetes are later
milestones. Replay participants remain local algorithms, never labelled as cloud models.

## Develop

Requires Node.js 24 LTS (22+ supported), Python 3.12, and
[uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
bash scripts/setup.sh
python scripts/dev.py
```

The frontend listens on port **3000**, and the API on **8000**. The launcher binds
both to loopback. API documentation is served at `/docs` on the API service.
New workspaces start empty. Hosted deployments never seed sample experiments.
Stop both services with Ctrl+C.

Alternatively, use two terminals:

```bash
cd apps/api
uv run --frozen uvicorn parallax_lab.main:app --host 127.0.0.1 --port 8000 --reload
```

```bash
cd apps/web
npm run dev -- --hostname 127.0.0.1 --port 3000
```

New installations store data in `apps/api/.data/parallax-lab.db`, which is ignored
by Git. Existing local databases are retained when the new database is absent.
Back up the file with SQLite's backup mechanism when retaining research work. Set
`PARALLAX_DATABASE_URL` before starting the API to use another local database.
For isolated fixture testing only, export `PARALLAX_MARKET_SOURCE=synthetic`.
Application startup never creates sample experiments. Playwright uses an explicit
test fixture in its temporary database, outside the application startup path. The frontend's
`API_BASE_URL` defaults to the API's loopback address for local development.
The server-side API proxy reads this at runtime. Hosted deployments use a private
Vercel service binding instead; see [deployment](docs/deployment.md).

Hosted storage supports PostgreSQL on Neon, with versioned migrations and
atomic, immutable experiment records. Vercel Authentication protects previews and
immutable deployment URLs. The production homepage is public; the owner's GitHub
identity guards private research, and a server-only token protects the Python API.

For real local data export `PARALLAX_MARKET_NETWORK=1` and `TIINGO_API_KEY`.
Never expose provider
keys via `NEXT_PUBLIC_*`. The `.env.example` documents optional configuration;
local shell processes require exported variables rather than automatically
loading the root `.env`.

## Validate

```bash
cd apps/api
uv run --frozen --group dev pytest --cov=parallax_lab --cov-branch --cov-report=term-missing --cov-fail-under=90
```

For the full coverage gate, set `PARALLAX_TEST_DATABASE_URL` to a disposable
PostgreSQL database. CI supplies its own PostgreSQL service. Without that
variable, PostgreSQL integration tests skip; run `uv run --frozen pytest` for
local SQLite checks only.

```bash
cd apps/web
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e
```

Stop the development launcher before running browser tests: Next.js development
processes share a build-directory lock. The tests start isolated services and a
temporary database. To use an
existing Chromium installation, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`.
Validation covers actual account behaviour and both comparison workflows.
The same backend coverage gate runs in CI. See [testing](docs/testing.md) for
the test boundaries and the acceptance gates for upcoming integrations.

## Containers

```bash
docker compose up --build -d
docker compose ps
docker compose down
```

The Compose configuration starts the app and API, retains SQLite in the
`paper-data` volume, and publishes ports on loopback. It is a local development
deployment, with no external authentication. Do not expose it publicly before
implementing the access controls in the roadmap. `docker compose down -v`
deletes the persisted experimental data.

For build environments with a custom trusted certificate authority, both
Dockerfiles accept a BuildKit secret named `build_ca` containing its PEM bundle.
Supply standard proxy build arguments and the environment’s supported DNS mapping
when required. Certificate verification remains enabled; no credentials or CA
secrets are copied into the final application image.

## Research assumptions

Decisions at candle close execute at the following candle's open. Transaction
costs apply to every fill; no shorting or leverage. These execution assumptions
do not simulate liquidity, order queues, corporate actions or broker behaviour.
Short synthetic runs are useful for validating software, not selecting a model
for real money. Read the API documentation for metric conventions.

Dependency versions are locked in `apps/web/package-lock.json` and
`apps/api/uv.lock`. GitHub Actions runs engine/API checks, frontend build and
browser integration tests. The prepared default-branch rules require pull requests
and these checks; see [repository safeguards](docs/repository-safeguards.md) for
their application status. See the plan for the acceptance gates required
before shared or production deployment.
