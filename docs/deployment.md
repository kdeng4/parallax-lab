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
| `PARALLAX_SEED_DEMO` | `1` seeds one deterministic baseline example; `0` disables seeding |

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
R2 and Cloudflare Access are not required for this architecture.

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
  `parallax_runtime`. An isolated `audit-2026-10-12` branch retains migration checks.
- Cloudflare: DNS-only `parallax.pdeng.pp.ua` CNAME to
  `e67426bd5849fbc4.vercel-dns-017.com`, TTL 300.
- Each Vercel environment has its own sensitive database URL and API token.
  Database-owner credentials are not deployed.
- Preview and production builds from audited GitHub main commit `973ae58c`
  succeeded through the Vercel API. The persistent repository link still fails
  with Vercel's GitHub-integration installation error. Automatic Git deployments
  require completing the repository connection in
  https://vercel.com/patrick-db62/parallax-lab/settings/git.

See [validation.md](validation.md) for observed checks and limitations.
