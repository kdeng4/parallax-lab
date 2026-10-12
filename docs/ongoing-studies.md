# Ongoing paper studies

Start a forward study with 1–10 US stock/ETF tickers, 1–3 models, 1–3 versioned
strategies and equal initial capital per pair. The server fixes the current start
time; backdated inputs, funding changes and later configuration edits are rejected.
Start during regular US market hours with a fresh quote for every selected ticker
and SPY, so the benchmark has an observable initial reference price.

Each study has a weekday window of 30–180 minutes in an IANA time zone. The window
must overlap US regular market hours. The published NYSE 2026–2028 calendar excludes weekends/holidays and clips
windows at 13:00 Eastern on announced early-close days. Unknown calendar years
fail closed pending an update; exceptional unscheduled closures need an operator
calendar update. Feed gaps produce no execution when fresh data is unavailable. No missed window
is replayed or filled at a past price. The owner can pause/resume; resuming a
partially processed window does not retry cancelled or uncertain decisions.

## Shared decisions and independent portfolios

The first eligible check prepares one immutable, hashed input: selected quotes,
news, announced events, corporate actions and prior observed study price history.
Every pair receives that exact corpus, its own paper account and its frozen
strategy. The private interface exposes the common snapshot and each validated
decision, including source timestamps, weights, confidence and safe token usage.
Price-only local controls use their observed-history warm-up and do not interpret
news. OpenAI participants receive the common articles and events.

Agents choose portfolio weights among the fixed ticker universe and cash, plus
an execution delay within the current window. They can choose no position. The
objective is to maximise ending equity, net of costs, within strategy risk limits;
it is not a promise of profit. Target exposure is proportionally capped by the
strategy. Passive exposure can drift as asset prices change. Leverage, short
selling, borrowing and outside ticker orders are rejected.

All cohort decisions must validate before any account trades. At most two cloud
calls run per scheduler invocation, sharing the existing six/minute and 24/day
rolling quota with historical research. Attempts are recorded before I/O; a
timeout or lost worker is never retried automatically. Any participant failure
skips cohort trades for that window. Quota-limited pending decisions wait only
within the remaining window. Large or simultaneous studies can miss windows
under these deliberately conservative limits.

Fills use real reference quotes newer than every cohort decision completion and
the agent's requested earliest execution time. Quotes are checked at most every
five minutes during execution. Sells precede buys; cash includes 1 bp fees and
2 bp slippage. Prices and execution timestamps are recorded separately. Orders
expire at window close. The strategy's rebalance threshold suppresses tiny orders.

## Equity and benchmark

Equity is cash plus all marked holdings plus unpaid dividend receivables. Zero
cash with valuable holdings is not bankruptcy. An account with equity at or below
USD 0.01 pauses; an all-insolvent study pauses permanently and cannot be refunded
or resumed. A new study is required for a new starting-capital comparison.

Verified splits change share quantities. Dividends become receivables at ex-date
for shares held before that date; only a verified payment date makes them
spendable cash. Missing payment dates remain explicitly unsettled. Corporate
action revisions stop unverified accounting. Agents and the one-share SPY
benchmark use the same action corpus. SPY includes dividends before costs; agent
returns include trading costs.

The chart shows `(equity / initial capital - 1) * 100`, beginning at 0%, with one
line per pair and a dashed SPY line. It records aligned valuations inside windows,
using actual UTC times. Unobserved periods are gaps between recorded observations.
Charts retain at most 1,000 aligned samples for rendering; immutable source points
remain in the database. Detail reads retain the initial point and latest 9,999
points, and the latest 200 audit events. Separate studies are never spliced together.

## Persistence and scheduling

Neon migration 003 stores mutable study payloads plus append-only input snapshots,
valuation points and audit events. Atomic study leases reject concurrent/stale
workers, including an owner pause during an in-flight model call. A failed step
discards uncommitted accounting changes. At most two studies can be active.

Cloudflare minute cron reads a tiny KV schedule. Outside windows it calls the
backend only for an hourly recovery refresh; inside windows it calls the dedicated
authenticated Vercel scheduler bridge. Owner schedule changes immediately request
a cache sync. This avoids the once-daily Vercel Hobby cron limitation and unnecessary
minute-by-minute Neon wakes. No browser tab needs to remain open.

The public projection contains agent names, eligible percentage curves and
paper buy/sell timestamps/tickers. It excludes settings, amounts, quantities, raw
prices, news and full decision text. The GitHub owner gate protects every private
read and write. Publication requires both creation-time and current verified
rights; later flag changes cannot publish an originally unapproved study.

## Current data gate

The production Tiingo storage and publication assertions remain disabled. Tiingo
Starter terms do not permit durable research inputs or derived results. A verified
entitlement covering storage, news processing, corporate actions and any intended
public display is required before a real ongoing study can start. This setup does
not purchase a subscription or fabricate replacement quotes/news.

Sources: [Tiingo IEX](https://www.tiingo.com/documentation/iex),
[splits](https://www.tiingo.com/documentation/corporate-actions/splits),
[dividends](https://www.tiingo.com/documentation/corporate-actions/dividends),
[pricing](https://www.tiingo.com/pricing),
[Cloudflare Cron](https://developers.cloudflare.com/workers/configuration/cron-triggers/),
[Vercel Hobby Cron](https://vercel.com/docs/cron-jobs/usage-and-pricing).

Calendar source: [NYSE hours and holidays](https://www.nyse.com/trade/hours-calendars), verified October 12, 2026.
