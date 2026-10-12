# Testing Parallax Lab

Run the backend gate from `apps/api`:

```bash
uv run --frozen --group dev pytest --cov=parallax_lab --cov-branch --cov-report=term-missing --cov-fail-under=90
```

Run the browser gate from `apps/web` after stopping the development launcher:

```bash
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e
```

GitHub Actions runs both gates and builds the Docker images on main pushes and
pull requests. Feature branches use the pull-request run instead of duplicating
the same checks on every push. The backend's 90% branch-inclusive coverage floor prevents large
untested changes; passing it does not prove strategy quality or live-trading
safety. Review the uncovered lines and the test behaviour when changing the
execution or accounting rules.

Published copy uses Canadian English (`en-CA`). Keep Canadian spellings such as
“behaviour” and retain established API field names. Monetary values remain in
USD because the simulated market and accounts are USD-denominated. CI runs
`scripts/check_release_language.py` to reject CJK text in release files; browser
tests verify the page language and USD display under the Canadian locale.

| Boundary | Current checks |
| --- | --- |
| Market and decision engine | Deterministic replay, shared input hash, observable data prefixes, next-open fills, end-of-data orders |
| Paper account | Cash/share conservation, fee and slippage accounting, allocation limits, randomized fill sequences |
| Persistence and audit | Append-only records, transaction rollback, concurrent independent experiments, filtered/paginated retrieval, restart persistence |
| HTTP API | Input validation, comparison design, creation, export metadata, and error responses |
| Browser | Both comparison flows, chart and audit interaction, export, mobile layout, recovery from failed requests, experiment switching |

The backend uses seeded synthetic market data and temporary SQLite databases.
Hypothesis reports failing order sequences and replay inputs so they can be
reproduced during investigation. Playwright starts its own API and Next.js
services against a temporary database. It never needs provider keys or network
market data. Its fixture creation is confined to `tests/browser_server.py` and a
temporary directory named `parallax-lab-e2e-*`; the application never seeds data.
The TypeScript gate also rejects unused local variables and parameters.

Before adding live feeds or paid models, add contract tests for normalized
timestamps, missing/out-of-order candles, identical model input snapshots,
provider refusal/timeout/rate limit, and a fixed decision deadline. Before a
distributed executor, prove retries and restarts cannot double-fill an order
and that the outbox and audit trail remain atomic. Before shared deployment,
exercise access control across users and tenants, backup restoration, and
failure recovery. These are acceptance gates for later milestones, not claims
that the current local application provides those services.
