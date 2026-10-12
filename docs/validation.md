# Milestone 1 validation

Validated in the cloud development environment on 2026-10-12.

| Check | Result |
| --- | --- |
| Locked setup (`bash scripts/setup.sh`) | Passed, including a clean npm reinstall |
| Engine, API, storage and mocked providers (`pytest`) | 98 passed; 94.22% branch-inclusive coverage (90% CI floor) |
| Browser integration (`npm run test:e2e`) | 10 passed |
| Release language | CJK scan passed; browser checks `en-CA` and USD formatting |
| Frontend production build | Passed |
| TypeScript check | Passed |
| API and web Docker images | Built successfully with TLS verification enabled |
| Docker Compose | Both services healthy; web-to-API proxy returns the actual experiment data |
| Persistence | Container restart retained the created experiment and all 251 audit events |
| Responsive production UI | Desktop and fully loaded 390px mobile inspected; no mobile document overflow |
| Development launcher | Both services started; SIGINT shut down the services |

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
