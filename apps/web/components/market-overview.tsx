'use client';

import { useCallback, useEffect, useState } from 'react';
import { ExternalLink, LoaderCircle, RefreshCw } from 'lucide-react';
import { api, money, percent } from '@/lib/api';
import type { MarketOverview as Snapshot } from '@/lib/types';

function statusLabel(status: string) {
  if (status === 'ok') return 'Latest published';
  if (status === 'stale') return 'Stale';
  if (status === 'key_missing') return 'Connection required';
  if (status === 'offline') return 'Feed disabled';
  if (status === 'refreshing') return 'Updating';
  if (['rate_limited', 'budget_exhausted'].includes(status)) return 'Refresh paused';
  return 'Unavailable';
}
function number(value: number | null | undefined, digits = 2) {
  return value == null ? '—' : value.toLocaleString('en-CA', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function checked(value: string | null) {
  return value ? new Date(value).toLocaleString('en-CA', { timeZone: 'America/Toronto', dateStyle: 'medium', timeStyle: 'short' }) + ' ET' : 'Not yet fetched';
}

export function MarketOverview() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [now, setNow] = useState(() => Date.now());
  const stale = (item: { next_refresh_at: string | null; status: string }) => Boolean(error) || (item.status === 'ok' && item.next_refresh_at != null && Date.parse(item.next_refresh_at) <= now);
  const load = useCallback(async (signal?: AbortSignal) => {
    setBusy(true); setError('');
    try {
      const result = await api<Snapshot>('/market/overview', { signal });
      if (!signal?.aborted) setSnapshot(result);
    } catch {
      if (!signal?.aborted) setError('Market data is temporarily unavailable.');
    } finally { if (!signal?.aborted) setBusy(false); }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  useEffect(() => {
    // Age the display locally; this timer never makes a provider/API request.
    const timer = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);

  return <section className="market-section" aria-labelledby="market-title" data-testid="market-overview" aria-busy={busy}>
    <div className="market-heading"><div><div className="eyebrow">PUBLISHED MARKET DATA</div><h2 id="market-title">The market, in context.</h2><p>Source dates stay visible. Daily observations, with no simulated prices.</p></div><button className="button secondary small" disabled={busy} onClick={() => void load()}><RefreshCw size={14} className={busy ? 'spin' : ''} />Check data</button></div>
    {error && <p role="alert" className="market-notice">{error}{snapshot ? ' Previously loaded values may be stale.' : ''}</p>}
    {!snapshot && busy && <p className="market-loading" role="status"><LoaderCircle size={16} className="spin" />Loading published observations…</p>}
    {snapshot && <>
      <div className="market-macro-grid">{snapshot.macro.map(item => <article className="metric-card market-macro" key={item.id}>
        <div className="metric-top"><span>{item.label}</span></div>
        <div className="market-value">{number(item.value, item.unit === '%' ? 2 : 4)}{item.value != null && item.unit === '%' ? <small>%</small> : null}</div>
        <span className={`market-status ${stale(item) || item.status !== 'ok' ? 'pending' : ''}`}>{statusLabel(stale(item) ? 'stale' : item.status)}</span>
        <div className="metric-detail">{item.frequency === 'monthly average' ? 'Monthly average · ' : 'Daily · '}{item.as_of ?? 'No observation'}</div>
        <div className="metric-detail">{item.unit !== '%' ? item.unit : 'Annual rate'}{item.change != null && <span> · {item.change >= 0 ? '+' : ''}{number(item.change, item.unit === '%' ? 2 : 4)} {item.unit === '%' ? 'pp' : ''} vs prior observation</span>}</div>
        <details className="market-provenance"><summary>Source & freshness</summary><a href={item.source_url} target="_blank" rel="noreferrer">{item.source}<ExternalLink size={11} /></a><p>Retrieved {checked(item.fetched_at)}</p><p>Next check after {checked(item.next_refresh_at)}</p></details>
      </article>)}</div>
      <section className="card market-stocks"><div className="card-heading"><div><div className="eyebrow">EQUITIES & TECHNICAL INDICATORS</div><h3>US market watchlist</h3></div><span className="subtle-label">End of day · USD</span></div>
        {snapshot.stocks.some(stock => stock.status === 'key_missing') && <p className="market-notice">Stock prices and indicators are awaiting a Tiingo connection. Missing values stay empty.</p>}
        <div className="table-scroll"><table className="performance-table market-table"><caption className="sr-only">Published stock closes and indicators calculated from adjusted daily closes</caption><thead><tr><th scope="col">Symbol / date</th><th scope="col">Close</th><th scope="col" title="Return calculated from split- and dividend-adjusted closes">Adjusted 1d return</th><th scope="col">SMA 20 / 50</th><th scope="col">RSI 14</th><th scope="col">MACD / signal</th></tr></thead><tbody>{snapshot.stocks.map(stock => <tr key={stock.symbol}>
          <th scope="row"><strong>{stock.symbol}</strong><small>{stock.data?.as_of ?? 'No observation'}</small><span className={`market-status ${stale(stock) || stock.status !== 'ok' ? 'pending' : ''}`}>{statusLabel(stale(stock) ? 'stale' : stock.status)}</span></th>
          <td>{stock.data ? money(stock.data.close, 2) : '—'}<small>{stock.data ? `${stock.data.volume.toLocaleString('en-CA')} shares` : 'Volume unavailable'}</small></td>
          <td className={stock.data ? stock.data.change_pct >= 0 ? 'positive' : 'negative' : ''}>{stock.data ? percent(stock.data.change_pct) : '—'}</td>
          <td>{number(stock.data?.indicators.sma20)}<small>{number(stock.data?.indicators.sma50)}</small></td><td>{number(stock.data?.indicators.rsi14)}</td>
          <td>{number(stock.data?.indicators.macd)}<small>{number(stock.data?.indicators.macd_signal)}</small></td>
        </tr>)}</tbody></table></div>
        <div className="market-footnote"><a href="https://www.tiingo.com/" target="_blank" rel="noreferrer">Source: Tiingo<ExternalLink size={11} /></a><span>{snapshot.price_frequency}. Indicators use adjusted closes; shown closes and volumes are unadjusted.</span></div>
        <details className="market-method"><summary>Calculation & refresh details</summary><p>{snapshot.indicator_basis} RSI uses Wilder smoothing; EMA starts with the simple average. An em dash means insufficient or unavailable data.</p><p>Data is checked on demand at most every six hours. Reopening or refreshing this page shares the same cache. Older cached values are labelled stale while the provider recovers.</p>{snapshot.stocks.map(stock => <p key={stock.symbol}>{stock.symbol}: retrieved {checked(stock.fetched_at)}; next check after {checked(stock.next_refresh_at)}.</p>)}</details>
      </section>
      <p className="market-attribution">Currency and rate data: Bank of Canada. Changes calculated by Parallax Lab. FX values are indicative daily averages. Monthly rate dates identify the observation month.</p>
    </>}
  </section>;
}
