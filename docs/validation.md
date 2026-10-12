# Parallax Lab · Milestone 1 validation

Validated in the cloud development environment on 2026-10-12.

| Check | Result |
| --- | --- |
| Locked setup (`bash scripts/setup.sh`) | Passed, including a clean npm reinstall |
| Engine, API, storage and mocked providers (`pytest`) | 100 passed; 94.32% branch-inclusive coverage (90% CI floor) |
| Browser integration (`npm run test:e2e`) | 10 passed |
| Release language | CJK scan passed; browser checks `en-CA` and USD formatting |
| Frontend production build | Passed |
| Vercel-style frontend build | Passed with an HTTPS API origin; missing or loopback origin rejected |
| TypeScript check | Passed |
| API and web Docker images | Built before the rename; the renamed build was blocked by container DNS while downloading a locked Python dependency |
| Docker Compose | Configuration passes; both services and the web-to-API proxy were validated before the rename |
| Persistence | A pre-rename container restart retained an experiment and all 251 audit events; current tests verify legacy SQLite file selection |
| Responsive production UI | Desktop and fully loaded 390px mobile inspected; no mobile document overflow |
| Development launcher | Both services started; SIGINT shut down the services |

The renamed frontend passed its browser suite, TypeScript check, and Vercel-style
production build. The browser suite checks the Parallax Lab page title and home
link. The renamed API passed its coverage gate. The Docker rebuild requires a
host with working container DNS before it can be marked as validated again.

The backend suite covers randomized account and replay invariants, account
conservation, fees, slippage, allocation limits, future-data isolation,
next-open execution, deterministic replays, fair comparison validation,
concurrent experiment saves, atomic rollback, audit immutability, seed
idempotency, export metadata, microsecond time filters, provider
refusals/errors, and validated provider inputs.

Browser scenarios cover seeded results, both experiment types, invalid form
recovery, optional names, keyboard dismissal, chart controls, account
inspection, audit filtering across experiment switches, real JSON downloads,
a fully loaded mobile layout, connection recovery, and preventing stale
results when an experiment selection fails. Tests use an isolated temporary
database and a system Chromium browser. The 90-second per-test limit allows
for development-proxy latency on this cloud host.

The published implementation plan and interface copy use Canadian English.
The page declares `en-CA`; dates, times, quantities, and USD amounts use that
locale. CI rejects CJK text in release files, and browser tests verify the
page language and USD display.

Runtime checks use actual local algorithms and synthetic market data. No live
market feed, paid model endpoint, broker, external authentication system, hosted
CI run, or published/new-task environment was validated. The provider adapters
were checked with mocked transports. Shared hosting and distributed execution
remain in the implementation roadmap.

The environment configuration draft contains tested installation and startup
instructions. Publishing that configuration is a separate product action.

A Vercel CLI temporary deployment was attempted from `apps/web`, but no hosted
deployment was created. The CLI had no authenticated account in this workspace,
and the login request failed through the workspace network. Neon was not
connected: the current API accepts SQLite URLs only and no Neon project
connector is available in this task.
