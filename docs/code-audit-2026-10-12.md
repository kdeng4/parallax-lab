# Code audit — 2026-10-12

Reviewed baseline: `c53ea5e4887b26f84edbb38cb0a2a98074c49248`.
Scope: API inputs and access boundaries, replay/accounting, persistence,
provider adapters, browser API calls, dependency locks, CI, and deployment.
This is a source review with reproducible checks, not a penetration test or
independent certification.

## Confirmed findings

| Severity | Finding and evidence | Resolution |
| --- | --- | --- |
| High for public hosting | Every FastAPI endpoint accepted anonymous requests, including creation and exports. The repository explicitly documented local-only use. | Require a server-only API token in hosted mode, keep the Python service private, protect all frontend URLs with Vercel Authentication, reject cross-origin writes. |
| High for serverless hosting | Store rejected all non-SQLite URLs and persisted to a local file. A Neon URL could not work, and ephemeral hosting would not retain records. | Add PostgreSQL persistence, versioned migrations, schema checks, separate environment branches, and a restricted runtime role. Preserve SQLite for local development. |
| Medium | A supported 1440-bar request produced a 5,683,065-byte pretty JSON export, exceeding the normal 4.5 MB buffered function response limit. | Stream create/detail/export responses through both server layers without Content-Length. |
| Medium | The frontend compiled a fixed API rewrite at build time, unsuitable for a private deployment-specific backend and server-side credentials. | Replace the rewrite with a bounded server-side proxy and a deployment-aware service binding. |

| Medium | The existing 390px browser test exposed horizontal overflow in the audit/methodology grid. | Allow the single-column grid and its children to shrink below their intrinsic content width. |

## Baseline evidence

- 100 backend tests passed, 94.32% branch-inclusive coverage.
- Frontend type check and Vercel-style production build passed.
- npm audit: zero reported vulnerabilities.
- Python dependency audit: 25 runtime packages, zero reported vulnerabilities
  after adding the locked psycopg driver.
- Existing tests exercise next-open execution, future-data isolation, matched
  participant inputs, account conservation, immutable audits, and rollback.
  No new defect was confirmed in those replay/accounting contracts.

## Verification of changes

Security and streaming tests, PostgreSQL integration tests, and frontend proxy
tests are checked into the repository. CI now starts a disposable PostgreSQL 17
service and includes its integration tests in the existing 90% coverage gate.
The isolated Neon test branch is separate from production and preview data.

The local workspace cannot resolve Neon database hosts, so direct local Neon
driver tests are blocked by its network. GitHub CI validates the driver against
real PostgreSQL; hosted preview checks validate the actual Neon connection.
Final CI and deployed-flow results are recorded in `docs/validation.md`.

The app remains a private, single-user, synthetic-data paper-trading workbench.
Live market feeds, paid model execution, real orders, multi-user isolation, and
distributed jobs were not enabled or represented as working.


## Follow-up: owner-only editing and sample removal

The original Vercel Authentication boundary limited page access, but did not
separate viewers with a share link from authorized experiment creators. The
follow-up adds application-scoped signed identity verification and an explicit
editor email allowlist on the server, plus a read-only UI. Missing configuration
fails closed. Cloudflare Access activation requires a separate account-level
approval; the code must not pretend editor sign-in is usable before activation.

Hosted demo seeding is now disabled unconditionally, and default local seeding is
off. A new database role and withdrawal of old-role INSERT privileges prevent old
immutable deployments from creating experiments or re-seeding deleted examples.
Only the known baseline and deployment audit records are selected for cleanup.

Regression checks cover missing configuration, anonymous and spoofed identities,
unapproved email, wrong issuer/audience, expired/future/missing-expiry tokens,
forged signatures, service/global tokens, JWKS failure, approved-owner creation,
view-only exports and a local opt-in that cannot bypass Vercel authorization.
