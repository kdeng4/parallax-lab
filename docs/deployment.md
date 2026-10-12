# Parallax Lab deployment

The repo deploys as two Vercel Services: Next.js in `apps/web` and private FastAPI
in `apps/api`. Cloudflare remains DNS-only. Neon supplies PostgreSQL and managed
Google identity. No Cloudflare Access organization or account-wide policy is needed.

## Public and private boundary

- `/` and `/api/public/dashboard` expose only agent names and an explicitly
  approved result projection. No settings, cash amounts, quantities, raw prices,
  news, credentials, private experiment names or full audit messages appear.
- `/workspace` requires an approved Google identity on the server. Its redirect
  is only a convenience; **every** `/api/v1/*` read/write also checks authorization.
- `/auth/sign-in`, `/api/auth/*` and static assets must remain reachable publicly.
- The private Python service is not routed to the internet. The Next service
  binding supplies `BACKEND_INTERNAL_URL`; never set it manually. A distinct
  `PARALLAX_API_TOKEN` per environment authenticates server-to-server requests.
- Keep Vercel protection on previews and immutable deployment URLs using
  `prod_deployment_urls_and_all_previews`. Change from `all` only after the new
  application guards pass verification. Never choose `null` or expose old builds.

## Google authentication

Neon Auth is enabled on production branch `br-delicate-fire-b8xk1lye` in project
`young-firefly-90966004`, database `parallax`. Its trusted app origin is
`https://parallax.pdeng.pp.ua`.

1. Create a Google OAuth **Web application** with basic identity scopes only.
2. Register this exact authorized redirect URI:
   `https://ep-dark-feather-b8xljhdp.neonauth.c-14.us-east-1.aws.neon.tech/parallax/auth/callback/google`
3. In Neon Auth, replace shared development Google credentials with that custom
   OAuth client ID and secret. Disable unused email/password registration.
4. Set `NEON_AUTH_BASE_URL` to the branch auth URL, and a sensitive random
   `NEON_AUTH_COOKIE_SECRET` of at least 32 characters in Vercel Production.
5. Keep `NEON_AUTH_GOOGLE_READY=0` until custom Google configuration is ready;
   then set it to `1` and redeploy. The shared development provider is not a
   verified production configuration.
6. `PARALLAX_EDITOR_EMAILS` contains only the owner's approved Google email.
   Optional `PARALLAX_VIEWER_EMAILS` grants private read access, never editing.
   Both require a verified email, unexpired managed session and linked Google
   identity. Account registration alone grants no app permissions.

The SDK handles OAuth state, session cookies and its callback verifier. The
Next proxy applies SDK middleware only to `/workspace`, never public assets.
Session and private API responses use no-store caching. Test owner sign-in,
reload, sign-out, an unapproved Google identity and direct API requests before
calling Google activation complete. Production OAuth still requires owner credentials.

## Private data integrations

| Source | Credential | App request budget | Content cache |
| --- | --- | --- | --- |
| Tiingo EOD + News | `TIINGO_API_KEY` | Shared 5/min, 10/hour, 30/rolling day | Starter: request memory only |
| Marketaux news | `MARKETAUX_API_KEY` | 4/hour, 24/rolling day | One hour |
| Alpha Vantage earnings calendar | `ALPHA_VANTAGE_API_KEY` | Shared 3/hour, 6/rolling day | One day per company |
| FRED releases | `FRED_API_KEY` | 2/hour, 8/rolling day | Six hours |
| SEC EDGAR submissions | `PARALLAX_SEC_USER_AGENT` identifying the app and contact | 3/min, 6/hour, 12/rolling day | One day |
| Bank of Canada | None | 1/hour, 4/rolling day | Six hours |

All sources share cross-worker leases and durable request counters. Failures
count, Retry-After is respected, and secrets/provider error bodies are never
returned. No public request fetches market data. News context loads manually in
the private workspace. Provider credentials are not available in previews by
default; `PARALLAX_MARKET_NETWORK=0` prevents preview traffic.

Context is informational: baseline algorithms do not consume news. Earnings
cover the current company watchlist (AAPL, MSFT, NVDA); ETF filings are not
misrepresented as operating-company events. Missing keys and empty calendars
remain distinct states. No sample stories or invented observations are used.

## Tiingo storage and publication rights

The October 6 terms prohibit Starter/Trial durable storage of source data **and
its derived results**. The earlier durable stock-cache implementation was
incorrect for that tier. The app now invalidates legacy Tiingo content caches
when storage approval is absent, retains only request/lease metadata, and keeps
successful Starter responses in request memory. They cannot start a persistent
experiment. Provider backup history is subject to Neon's configured retention.

`PARALLAX_TIINGO_STORAGE_APPROVED=1` asserts that a suitable active entitlement
has been verified; it does not obtain permission. Leave it `0` on Starter.

`PARALLAX_PUBLIC_PERFORMANCE_APPROVED=1` separately asserts appropriate public
rights covering **all plotted portfolios and the SPY benchmark**. A single
security rebased to 100 is explicitly not a licensing workaround. Only new
experiments created with that approval can enter the public projection; synthetic
fixtures and previously unapproved records never publish automatically.

Public curves compare participants from the latest eligible experiment, all
starting at 100, with matched SPY session dates. SPY uses adjusted buy-and-hold
returns before costs; agents include trading costs. Missing benchmarks stay
missing. Unrelated runs are not joined into a fictitious continuous portfolio.
Activity shows buy/sell and historical session date, not simulated execution
prices, account quantities, strategy details or purported live trade times.

## Storage, CI and rollout

Existing schema 2 and runtime role `parallax_app_v2` are reused; no migration is
needed. Experiments/events remain immutable and runtime permissions unchanged.
The mutable `market_state` stores provider caches and budgets only.

CI covers PostgreSQL, backend coverage, proxy authorization, browser flows and
both container builds. Verify the protected candidate, advance `main`, then
expose only production aliases through Standard Protection. Confirm anonymous
public access succeeds while private reads, writes, exports and old immutable
URLs remain protected. Production stays empty until the owner creates real,
properly licensed research; browser fixtures use a temporary local database.
