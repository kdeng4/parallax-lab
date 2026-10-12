# Parallax Lab · Validation history

## Owner authorization, Git connection and cleanup — 2026-10-12

These results supersede the deployment audit's seed and Git-link status below.

- GitHub `kdeng4/parallax-lab` is permanently connected to Vercel. Dashboard
  confirmation and the linked-project API agree. Pushing main commit `703da57d`
  automatically produced production deployment `dpl_AstMwSgdaapd4xZeJMdnaUQYKzAP`,
  source `git`, state READY, on the custom domain.
- Security code commit `6cafebf6`: CI run
  [38285745642](https://github.com/kdeng4/parallax-lab/actions/runs/38285745642)
  passed: 112 backend tests, 93.38% branch-inclusive coverage, 18 signed-token
  authorization/proxy tests, 11 browser workflows, and both container builds.
  Main documentation commit `703da57d` also passed CI run `38286719974`.
- Both production and preview now have zero experiments and zero audit events.
  Only the known baseline and deployment-audit records were deleted. SQL
  readback confirmed both immutable-record triggers are enabled after cleanup.
- Both deployments now use `parallax_app_v2`, with minimal SELECT/INSERT grants.
  INSERT privileges were revoked from `parallax_runtime` on both branches;
  SQL confirmed that old role cannot create experiments or audit events.
- Hosted seeding is unconditionally disabled, and local seeding defaults off.
  The isolated audit branch was already empty. CI seed fixtures remain isolated.
- Protected preview and custom-domain production HTTP checks return PostgreSQL
  health and `{ "experiments": [] }`. `/api/session` returns `canEdit: false`,
  reason `not_configured`, with private/no-store caching while activation awaits
  approval. Unknown identities cannot obtain editor permission from page access.
- Editor allowlist contains only the verified Vercel owner account. No passwords,
  identity assertions, owner database credentials or runtime tokens are public.
- Cloudflare Access is not yet provisioned. Automatic approval review blocked
  creating the proposed organization as an account-level security change needing
  explicit approval. Until activation, the hosted app is read only for everyone,
  including the owner. Owner sign-in/creation has therefore **not** been verified
  on the live app. Cryptographic authorization behavior is covered by CI using
  generated test keys; those keys are never deployed.
- Dashboard login and Git connection were completed in the authenticated browser.
  Opening the hosted preview then hit a browser credential-protection error, so
  live HTTP checks used the Vercel connector. No live browser workflow success is
  claimed. The Git connection screenshot is retained as operational evidence.

## Deployment audit — 2026-10-12

The results below supersede the original local-only hosting assumptions.

- Local backend: 105 passed; 4 PostgreSQL integration tests deferred to CI
  because this workspace cannot resolve Neon database hosts.
- Server-side proxy tests: 4 passed, including credentials, rejected writes,
  missing hosted configuration, and a streamed response over 5 MB.
- Browser integration: all 10 workflows passed after fixing mobile overflow.
- TypeScript and production frontend build: passed.
- Dependency audits: no reported npm vulnerabilities; no reported Python
  vulnerabilities across 25 runtime packages.
- GitHub CI [run 38280754812](https://github.com/kdeng4/parallax-lab/actions/runs/38280754812):
  all three jobs passed for commit `973ae58c331534b3a86c57d53139866a80476635`.
  Backend: 109 passed, 93.26% branch-inclusive coverage; PostgreSQL 17 integration
  tests included. Frontend/proxy/browser checks and both container builds passed.
- Protected Vercel preview: PostgreSQL health, rejected cross-origin writes,
  invalid input, a 1440-bar experiment, independent reload, filtered events, and
  exact JSON export all passed. Export: 5,683,118 bytes, streamed without
  Content-Length, with no-store and attachment headers.
- Neon SQL readback: the preview experiment contains 5,999 events. Production
  contains only its baseline example; preview test records did not reach it.
  The runtime role has SELECT/INSERT, no UPDATE/DELETE, and no superuser,
  role-creation, database-creation, or row-security-bypass privileges.
- Production health and persisted listing passed. Custom domain
  `https://parallax.pdeng.pp.ua` returns the same PostgreSQL health response
  with authorized access. Anonymous API access redirects to Vercel sign-in.
- Cloudflare CNAME and Vercel domain checks: verified, no DNS conflicts,
  `misconfigured: false`. Vercel Authentication is enabled for all deployments.
- A fresh preview and production deployment both built successfully from the
  exact audited GitHub main commit. Production deployment:
  `dpl_2EfyWxdjaJjGEm8EHzr5sSt69spM`; it retained the baseline created by the
  earlier deployment, confirming storage survives a release.
- Automatic Git deployments are not connected. Vercel can list the repository
  and build from it, but both project-link attempts report that the GitHub
  integration must be installed. Finish the connection in the project's Git
  settings; do not assume push-to-deploy works until a push is observed.
- Hosted browser automation reached Vercel sign-in, so it is not counted as a
  successful hosted UI check. The initial automation was blocked by automatic
  review over third-party telemetry; a retry with external requests blocked
  remained at sign-in. Local and GitHub CI browser suites passed. Protected
  hosted HTTP workflows were verified separately, as listed above.

## Original milestone 1 validation (historical)

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

## Ongoing studies validation — October 12, 2026

The forward-study audit added model/strategy portfolio pairs, one common daily
news/price corpus, current-time starts, immutable settings, execution delays and
percentage returns against SPY. It also corrected cash-only insolvency, partial
accounting on failed inputs, stale-worker writes, interrupted call retries,
cohort execution timing and exchange holiday/early-close handling. Obsolete
cloud-inference-disabled copy was removed.

Local checks passed: 246 backend tests (6 PostgreSQL tests require CI), 92.79%
branch-aware backend coverage, 33 owner/machine authorization tests, 8 scheduler
tests, TypeScript checks and production builds. The scheduler bundle is under
5 KiB and minute requests compare UTC intervals without timezone formatting.

Migration 003 was applied on isolated Neon branch
`audit-forward-studies-2026-10-12`. Transactional study/snapshot/point/event writes
and rollback were verified through Neon; an attempted snapshot update triggered
the immutable-record guard and rolled back. Runtime privileges allow mutable
account updates but forbid snapshot updates. All test records were rolled back.
Direct Postgres tests cannot run in this workspace because database DNS/TCP is
unavailable; the GitHub CI PostgreSQL service runs the full driver tests.

Database connection traceback output exposed a runtime credential during an
unsuccessful direct-connection check. Production and preview passwords were
rotated, Vercel Secrets updated, the production app redeployed and its public
projection rechecked successfully. The exposed role on the isolated audit branch
was disabled; temporary connection files and unused provisioning roles were
removed. Application runtime privileges remain restricted.

The production data storage/publication assertions remain disabled. No real
ongoing study has been started with unverified data entitlements, and no example
portfolio or source article is seeded into the deployed workspace. Actual owner
OAuth callback verification still needs the owner's browser session.
