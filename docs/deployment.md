# Vercel frontend deployment

The Next.js frontend is in `apps/web`. Its requests to `/api/v1/*` are proxied
to the FastAPI service through a Next.js rewrite. A Vercel deployment needs a
reachable HTTPS API before the research workbench can load data.

Configure the Vercel project with:

| Setting | Value |
| --- | --- |
| Root Directory | `apps/web` |
| Framework | Next.js |
| Install command | `npm ci` |
| Build command | `npm run build` |
| Environment variable | `API_BASE_URL=https://<protected-api-origin>` |

Set `API_BASE_URL` for every Vercel environment being deployed. Supply only
the origin: no `/api/v1` path, credentials, or trailing path. The rewrite is
compiled during the build, so rebuild after changing this value. Vercel builds
fail if the variable is missing, non-HTTPS, or points to loopback.

Before deploying, verify that the API is available at
`https://<protected-api-origin>/api/v1/health` and that its authentication
protects experiment creation, records, and exports. The current FastAPI API is
single-user and has no authentication; it must not be exposed as a public API.
The local SQLite database is not suitable for an ephemeral hosted API.

Neon can provide hosted PostgreSQL for a future API deployment; it is not
needed for the frontend build. The current storage layer accepts SQLite URLs
only, so adding a Neon connection string by itself does not connect or deploy
the API. PostgreSQL storage, its integration tests, API hosting, and access
control are separate prerequisites for a full hosted workbench.

After deployment, check the Vercel URL and its `/api/v1/health` proxy. Open the
workbench, create a paper experiment, reload, and confirm that the experiment
and audit trail persist. A successful frontend build alone does not establish
that these workflows are working.
