# Market data audit and implementation — 2026-10-12

Scope: current `main`, the supplied provider comparison, live provider documentation,
and the existing Vercel/Neon configuration. This is a code and integration audit,
not a certification of provider data or investment results.

## Findings and fixes

| Severity | Evidence | Resolution |
| --- | --- | --- |
| High | `run_experiment` always generated random OHLCV. No real feed or credential existed. | Hosted requests now require a verified Tiingo dataset. Missing, stale, malformed or insufficient history returns 503; synthetic fallback is prohibited. Fixtures require an explicit non-hosted test setting. |
| High | Candle-close times and Sharpe annualization were hard-coded to minutes. | Daily snapshots use normalized session-date labels and 252 periods/year. Exports preserve interval, adjustment basis, retrieval time, observation date, exact candles and hash. |
| High | An in-memory cache would reset on serverless starts and multiply upstream calls across workers. | Schema 2 adds a separate bounded mutable cache. PostgreSQL transaction advisory locks atomically reserve refresh leases and rolling provider quotas before network I/O. Quotas count failed calls. |
| Medium | Raw daily prices can turn splits/dividends into misleading signals. | Replay and technical indicators use Tiingo adjusted OHLCV. Displayed latest closes and volumes retain their raw values and labels. Adjustment and retrospective-data limitations are explicit. |
| Medium | The supplied report mixes outdated quotas and production restrictions. | Verified primary documentation before selecting feeds. Alpha Vantage is 25 requests/day, not 500. NewsAPI's free plan prohibits staging/production, including internal deployments. Neither is enabled. |
| Medium | Old README/API text still promised seeded examples. | Current documentation now states empty workspaces, real data by default, and explicit test-only fixtures. |

## Selected sources and limits

| Feed | Data | App request budget | Cache / entitlement |
| --- | --- | --- | --- |
| Bank of Canada Valet | USD/CAD, EUR/CAD, policy target, monthly average 3-month Treasury bill rate | 1/hour and 4/rolling 24 hours; one combined request | Six hours; no key. Source dates and daily/monthly frequencies retained. |
| Tiingo EOD | SPY, QQQ, AAPL, MSFT, NVDA; completed daily history | 5/minute, 10/hour, 20/rolling 24 hours across all symbols | Six hours; server-only `TIINGO_API_KEY`; individual personal-use entitlement. |

Tiingo's published Starter limits are 50/hour, 1,000/day, 500 unique symbols/month
and 1 GB/month. Only five fixed symbols are supported. Each response is capped at
512 KiB, so the configured maximum successful-response budget is about 310 MiB
over 31 days. Other applications using the same token consume the same provider
allowance; reserve this token for Parallax Lab. Preview and local external fetches
are disabled by default, so they do not duplicate production usage.

The app uses on-demand refreshes, not scheduled polling. Database state survives
restarts. Cache transactions end before HTTP requests begin; no connection is
held waiting on a provider. No API key is sent to browsers, stored in snapshots,
placed in URLs or included in returned error text. Provider 429 Retry-After
seconds/HTTP dates and exponential cooldowns are persisted. There are no immediate
retries. A failed refresh retains the last successful values with a stale label;
stale histories cannot start new experiments. The UI ages its freshness labels
without making background HTTP requests.

The existing `parallax-lab` Neon project (`young-firefly-90966004`) is on
`free_v3`; a second project is unnecessary. The mutable `market_state` table is
separate from immutable experiments/events. The runtime role needs SELECT,
INSERT and UPDATE on this table only. It still cannot mutate completed research.

## Research semantics

SMA 20/50, Wilder RSI 14 and SMA-seeded EMA MACD 12/26/9 are calculated locally,
without additional provider requests. Warm-up gaps remain null. A flat RSI window
is defined as 50. The displayed 1-day return uses adjusted closes. Currency/rate
changes compare the prior available observation; rate changes are percentage
points, not relative percentages. Monthly observations identify the month, not
an exact publication timestamp.

Daily replays support 60–252 completed sessions. Provider history is requested
through the preceding UTC date, conservatively excluding today's incomplete
session. The daily event timeline uses 00:00:00/23:59:59 UTC as normalized date
labels, not actual exchange opening/closing times. Orders still fill at the next
observed session's open. No missing sessions are interpolated. Adjusted histories
are retrospective and may be revised; exports freeze the exact snapshot, but
cannot claim point-in-time data vintages or actual broker execution prices.

## Activation and verification

Bank of Canada requires no secret. Tiingo is configured by adding a sensitive
`TIINGO_API_KEY` to the Vercel project's **Production** environment, then
redeploying. Do not paste keys into chat, commit them, or prefix them with
`NEXT_PUBLIC_`. Keep this individual feed private to its licensed owner; obtain
appropriate provider permission before sharing its data with other people.

The deployment currently has no Tiingo token. Its stock rows intentionally show
connection-required states. A production equity response and replay cannot be
verified until a real credential is provided. Editor authentication remains a
separate deployment prerequisite; this change does not relax that guard.

Automated checks cover indicator math, daily causality/annualization, malformed
and non-finite data, duplicate observations, incomplete sessions, shared cache
restart/concurrency, rolling quotas, failed-request accounting, Retry-After,
stale-data retention, token privacy, proxy restrictions and browser empty/stale
states. CI includes real PostgreSQL concurrency and migration checks.

Validation on code commit `57fd695a760698b4d0c32c408322afbb0c97e59c`:
[GitHub Actions run 38290424421](https://github.com/kdeng4/parallax-lab/actions/runs/38290424421)
passed 148 backend tests (94.79% branch-inclusive coverage), 19 authorization/proxy
tests and 13 browser workflows, plus the production frontend and both container
builds. The protected preview returned the real-data catalog and correctly kept
external feeds disabled. Schema 2 was applied to audit, preview and production;
runtime cache permissions and unchanged research immutability were read back.
A live Bank of Canada adapter check returned four valid published series. The
preview catalog review also caught and corrected a leftover minute-specific
description in the twelve-bar baseline strategy.

## Primary references checked

- [Tiingo pricing and individual-use restriction](https://www.tiingo.com/pricing)
- [Tiingo daily prices, adjustment fields and publication timing](https://www.tiingo.com/documentation/end-of-day)
- [Bank of Canada Valet guide: keyless access, caching and backoff](https://www.bankofcanada.ca/valet-api-how-to/)
- [Bank of Canada attribution, acceptable use and indicative FX](https://www.bankofcanada.ca/terms/)
- [Alpha Vantage current quota and paid intraday access](https://www.alphavantage.co/support/)
- [NewsAPI production restriction](https://newsapi.org/pricing)
- [FRED API key requirements](https://fred.stlouisfed.org/docs/api/api_key.html)

Yahoo scraping, broker account access, paid feeds, news aggregation and order
placement are not introduced by this implementation.
