# Parallax Lab deployment

The hosted application uses one Vercel project with two Services (currently a
Vercel beta): Next.js in `apps/web` and FastAPI in `apps/api`. Neon provides
PostgreSQL. Cloudflare manages the custom domain's DNS.

## Application boundary

The repository-root `vercel.json` exposes only the `web` service. The Python
service has no public route. A binding injects `BACKEND_INTERNAL_URL` into web
functions at runtime; never set this variable manually. Browser calls to
`/api/v1/*` go through a Next.js route handler, which attaches a server-only
bearer token, forwards only supported paths, and streams responses.

**Enable Vercel Authentication for All Deployments before deploying.** This
must cover production domains, preview URLs, and immutable deployment URLs.
API service authentication alone does not authenticate a visitor to the frontend.
Do not disable project protection while this remains a single-user workspace.

| Project setting | Value |
| --- | --- |
| Git repository | `kdeng4/parallax-lab` |
| Production branch | `main` |
| Root directory | repository root |
| Framework preset | Services |
| Build and install commands | defined per service in `vercel.json` |
| Node.js | 24.x |
| Function region | iad1, close to Neon aws-us-east-1 |
| Vercel Authentication | All Deployments (`deploymentType: all`) |

## Secrets and environments

Set encrypted/sensitive project environment variables. Never use `NEXT_PUBLIC_`
for these values, commit them, or print them in build/test logs.

| Variable | Purpose |
| --- | --- |
| `PARALLAX_DATABASE_URL` | Pooled PostgreSQL URL for a runtime role with SELECT/INSERT privileges only |
| `PARALLAX_API_TOKEN` | Random bearer token of at least 32 characters, shared by the two services |
| `PARALLAX_SEED_DEMO` | `0`; hosted deployments never seed, even if set to `1` |
| `PARALLAX_ACCESS_ISSUER` | Exact HTTPS Cloudflare Access team origin |
| `PARALLAX_ACCESS_AUDIENCE` | AUD tag of this application |
| `PARALLAX_EDITOR_EMAILS` | Explicit comma-separated approved editor emails; no automatic grants |

Use different database branches and tokens for production and preview. A hosted
API fails startup when its PostgreSQL URL or token is missing. Local development
still supports SQLite and `API_BASE_URL=http://127.0.0.1:8000`; set the same
`PARALLAX_API_TOKEN` in both processes when testing authenticated local access.

## Database migration

Schema changes live in `apps/api/parallax_lab/migrations`. Test them on an
isolated branch first. Apply using a **direct** owner connection, before starting
the app; the runtime role should not own tables or have schema-change rights.

```bash
cd apps/api
# Inject the direct owner connection as PARALLAX_DATABASE_URL_UNPOOLED.
uv run --frozen python -m parallax_lab.migrate
```

The migration is transactional, serialized by an advisory lock, and idempotent.
The API only checks the schema version at startup. Experiments and their events
commit in one transaction; PostgreSQL triggers reject updates/deletes, and the
runtime role additionally has no such grants.

## DNS and release verification

Add the intended subdomain to the Vercel project, use the exact CNAME target
returned by Vercel, and create a DNS-only CNAME in Cloudflare. Keep existing
records untouched. Vercel terminates HTTPS and enforces project authentication.
The proposed editor login uses Cloudflare Access. Access activation is currently
blocked pending explicit approval; DNS remains unchanged until activation.
Creating an Access application requires proxying only the Parallax subdomain,
with Full (strict) TLS to Vercel. Do not change unrelated hostnames.

Before release, run CI (including real PostgreSQL, frontend proxy tests, browser
workflows, and container builds). Then verify the protected preview: health,
creation, reload/persistence, filtered audit events, and the 1440-bar export.
Check that anonymous access cannot read or create experiments, and that no
public rewrite exposes the API service. The large export is streamed through
both FastAPI and Next.js so it does not hit the buffered response-size limit.

Once connected, Git integration deploys main to production and other branches to preview.
Database migrations remain an explicit operator action, not a side effect of
every frontend build. Verify CI before merging changes; no branch-protection
policy is assumed to exist.


## Provisioned deployment — 2026-10-12

- Application: https://parallax.pdeng.pp.ua (Vercel sign-in required).
- Vercel: `patrick-db62/parallax-lab`, project `prj_WfMeBpTlMJ13F7my4nMJVaAHd8aP`.
- Neon: project `young-firefly-90966004`, PostgreSQL 17 in aws-us-east-1.
  Production branch: `br-delicate-fire-b8xk1lye`; preview branch:
  `br-super-wave-b8rx0ons`. Database: `parallax`; application role:
  `parallax_app_v2`. An isolated `audit-2026-10-12` branch retains migration checks.
- Cloudflare: DNS-only `parallax.pdeng.pp.ua` CNAME to
  `e67426bd5849fbc4.vercel-dns-017.com`, TTL 300.
- Each Vercel environment has its own sensitive database URL and API token.
  Database-owner credentials are not deployed.
- `kdeng4/parallax-lab` is now permanently connected in Vercel Git settings,
  confirmed both in the dashboard and the provider's linked-project API.
  Production branch: `main`. The initial connector installation error was
  resolved by connecting the existing GitHub integration through the dashboard.
- Editor authorization commit `6cafebf6` passed CI run `38285745642`:
  112 backend tests with 93.38% branch-inclusive coverage, 18 proxy/auth tests,
  11 browser workflows, and both container builds. The protected preview
  reports healthy PostgreSQL and read-only access while editor login is pending.

See [validation.md](validation.md) for observed checks and limitations.

## Editor authorization and empty workspaces

Vercel page access and app edit permission are separate. Every POST to the public
experiment endpoint verifies an RS256 Cloudflare Access application JWT against
the configured issuer's rotating JWKS, audience, expiry, issued-at time and
nonempty user identity. Only a verified email in `PARALLAX_EDITOR_EMAILS` may
create an experiment. Claimed email headers, service identities, global Access
tokens and Vercel share links do not grant write permission. Failed verification
or absent configuration leaves the workspace read only. GET requests retain the
existing Vercel Authentication boundary. No public edit/delete API exists.

The initial editor allowlist is the verified owner account from Vercel; its value
is kept in Vercel settings, not in this public repository. Adding another editor
requires the owner to approve that identity, update the Access application policy
and the server allowlist, then redeploy. Keep application sessions at eight hours
or less. Revocation requires updating both controls; redeploying the allowlist
blocks an otherwise valid existing token at the application boundary.

Proposed Access configuration awaiting approval:

- Organization: Parallax Lab, `pdeng-parallax.cloudflareaccess.com`.
- One self-hosted app for `parallax.pdeng.pp.ua`, eight-hour sessions.
- Allow only the owner email, authenticated by Cloudflare or one-time email PIN.
- Enable HttpOnly and binding cookies. Do not create an Everyone/bypass policy.
- Keep Vercel Authentication for All Deployments. Raw Vercel URLs still require a
  valid editor JWT to write; shared Vercel pages are view only.

**Current activation status:** Cloudflare Access is not enabled on the account.
Automatic approval review rejected organization creation as an account-level
security change requiring explicit approval. Issuer and audience must remain
unset until the actual organization and app are provisioned and verified. This
means nobody, including the owner, can create a hosted experiment yet.

New databases start empty. The seed fixture remains available only for isolated
local tests by explicitly setting `PARALLAX_SEED_DEMO=1`. `scripts/dev.py` and
localhost-only Compose opt in to local writes; Vercel ignores that opt-in.
The browser suite seeds its own temporary database and does not touch Neon.

For this security rollout, use a new runtime role with the same minimal
SELECT/INSERT grants, deploy its credentials, then revoke INSERT on experiments
and events from the old role. This also invalidates writes from old immutable
Vercel deployments. Never roll back to a deployment without the editor guard.
The operator can remove specifically identified seed/audit rows in one locked
transaction, briefly disabling only the two immutable-record triggers and
re-enabling them before commit. Do not remove actual research records or weaken
runtime privileges. Verify both environments remain empty after a cold start.


Cleanup and automatic-deployment checks completed on 2026-10-12: both production
and preview contain zero experiments and zero events. Both immutable triggers
are enabled. The old role has no INSERT privileges, and the new runtime role has
only the required SELECT/INSERT grants. Main commit `703da57d` automatically
created READY production deployment `dpl_AstMwSgdaapd4xZeJMdnaUQYKzAP` with
`source: git`; custom-domain health and empty listing both returned HTTP 200.
