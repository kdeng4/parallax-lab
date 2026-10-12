# Parallax Lab

**A paper-trading research workbench for controlled model and strategy experiments.**

Parallax Lab runs independent trading algorithms against the same immutable market
snapshot, records every decision and fill, and makes results comparable in one
minimal interface. The first milestone is a working local research application:
**synthetic market data, local baseline algorithms, simulated funds.**

The phased [implementation plan](docs/implementation-plan.md) maps the full
design to live data, cloud model execution, distributed workers and production
operations. [Architecture](docs/architecture.md) and the
[API contract](docs/api-contract.md) document the current boundaries.
See [validation results](docs/validation.md) for the checks executed in this environment.
See [deployment requirements](docs/deployment.md) before connecting a Vercel
frontend to a hosted API.

## What is implemented

- Model comparison with a fixed strategy; strategy comparison with a fixed model.
- Deterministic OHLCV snapshots shared by all participants, with dataset hashes.
- Momentum, mean-reversion and buy-and-hold reference algorithms.
- Versioned Markdown strategy configurations.
- Independent paper accounts, next-bar fills, fees, slippage and long-only limits.
- Equity curves, returns, drawdown, Sharpe and realized sell-fill win rates.
- Persistent experiment history, sequenced audit trails, filtering and JSON export.
- A responsive Next.js UI and a validated FastAPI HTTP API.

No live broker orders are implemented. Live feeds, cloud-model experiment
execution, user authentication, NATS workers, MLflow and Kubernetes are later
milestones. Provider adapters are infrastructure for future integration; demo
results are never attributed to cloud models.

## Develop

Requires Node.js 24 LTS (22+ supported), Python 3.12, and
[uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
bash scripts/setup.sh
python scripts/dev.py
```

The frontend listens on port **3000**, and the API on **8000**. The launcher binds
both to loopback. API documentation is served at `/docs` on the API service.
An example experiment is seeded once, so the first visit already has results.
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
Set `PARALLAX_SEED_DEMO=0` to skip the initial example. The frontend's
`API_BASE_URL` defaults to the API's loopback address. Next.js embeds rewrite
destinations at build time; set the value **before** a production build.

No API keys are required for the local research workflow. Never expose provider
keys via `NEXT_PUBLIC_*`. The `.env.example` documents optional configuration;
local shell processes require exported variables rather than automatically
loading the root `.env`.

## Validate

```bash
cd apps/api
uv run --frozen --group dev pytest --cov=parallax_lab --cov-branch --cov-report=term-missing --cov-fail-under=90
```

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
browser integration tests. See the plan for the acceptance gates required
before shared or production deployment.
