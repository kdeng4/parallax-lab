'use client';

import { useEffect, useRef, useState } from 'react';
import { Pause, Play, RefreshCw } from 'lucide-react';
import { api, money, percent } from '@/lib/api';
import type { Catalog, LiveStudy, SharedInput } from '@/lib/types';
import { PercentChart } from './percent-chart';
import { LiveStudyDialog } from './live-study-dialog';

const when = (value: string) => new Date(value).toLocaleString('en-CA', { timeZone: 'UTC', hour12: false });

export function LiveStudies({ catalog, canEdit, creating, onClose }: { catalog: Catalog; canEdit: boolean; creating: boolean; onClose: () => void }) {
  const [studies, setStudies] = useState<LiveStudy[]>([]);
  const [selected, setSelected] = useState('');
  const [detail, setDetail] = useState<LiveStudy | null>(null);
  const [shared, setShared] = useState<SharedInput | null>(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const inspection = useRef<AbortController | null>(null);
  useEffect(() => () => inspection.current?.abort(), [selected]);
  useEffect(() => {
    const controller = new AbortController();
    api<{ studies: LiveStudy[] }>('/studies', { signal: controller.signal }).then(result => {
      if (controller.signal.aborted) return;
      setStudies(result.studies); setSelected(current => current || result.studies[0]?.id || '');
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Could not load ongoing studies.'); });
    return () => controller.abort();
  }, [revision]);
  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    let sequence = 0;
    const load = () => {
      const current = ++sequence;
      return api<LiveStudy>(`/studies/${selected}`, { signal: controller.signal }).then(value => { if (!controller.signal.aborted && current === sequence) { setDetail(value); setError(''); } })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Could not load this study.'); });
    };
    void load();
    const timer = setInterval(() => { if (document.visibilityState === 'visible') void load(); }, 60_000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [selected, revision]);
  const study = detail?.id === selected ? detail : null;
  async function control(action: 'pause' | 'resume' | 'check') {
    if (!study) return;
    setBusy(true); setError('');
    try { setDetail(await api<LiveStudy>(`/studies/${study.id}/${action}`, { method: 'POST', body: '{}' })); setRevision(value => value + 1); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not update this study.'); }
    finally { setBusy(false); }
  }
  async function inspect(snapshotId: string) {
    if (!study) return;
    inspection.current?.abort();
    const controller = new AbortController();
    inspection.current = controller;
    setShared(null); setError('');
    try { const result = await api<SharedInput>(`/studies/${study.id}/snapshots/${snapshotId}`, { signal: controller.signal }); if (!controller.signal.aborted) setShared(result); }
    catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Could not load the shared input.'); }
  }
  return <section className="live-studies" data-testid="live-studies" aria-labelledby="live-title">
    <div className="card live-heading"><div className="card-heading"><div><div className="eyebrow">FORWARD PAPER INVESTING</div><h2 id="live-title">Start together. Grow independently.</h2></div>
      <button className="button secondary" onClick={() => setRevision(value => value + 1)}><RefreshCw size={15} />Refresh studies</button></div>
      <p>One line per model / strategy pair, starting at 0%. Every pair gets the same daily prices and news, chooses its own tickers and timing, and keeps its own portfolio.</p>
      {!catalog.live?.available && <p className="market-notice">{catalog.live?.requirement ?? 'Live data is not configured.'}</p>}
      {!catalog.live?.scheduler_configured && <p className="market-notice">Background scheduling is awaiting setup. Owner checks can process a current window.</p>}
      <label className="live-selector">Ongoing study<select disabled={busy} value={selected} onChange={event => { setSelected(event.target.value); setShared(null); }}><option value="">Choose a study</option>{studies.map(item => <option key={item.id} value={item.id}>{item.name} · {item.status.replaceAll('_', ' ')}</option>)}</select></label>
      {error && <p role="alert" className="form-error">{error}</p>}
      {!selected && <p className="muted">No ongoing study selected. Start a study to record future decisions using verified market data.</p>}
    </div>
    {study && <><section className="card live-performance"><div className="card-heading"><div><div className="eyebrow">{study.status.replaceAll('_', ' ').toUpperCase()}</div><h2>{study.name}</h2></div>
      <div className="live-controls"><button className="button secondary" disabled={!canEdit || busy || study.status === 'paused_bankrupt'} onClick={() => void control(study.status === 'active' ? 'pause' : 'resume')}>
        {study.status === 'active' ? <Pause size={14} /> : <Play size={14} />}{study.status === 'active' ? 'Pause study' : 'Resume study'}</button>
        <button className="button secondary" disabled={!canEdit || busy || study.status !== 'active'} onClick={() => void control('check')}>Check current window</button></div></div>
      <p>Started {when(study.started_at)} UTC · weekdays {study.config.window_start}–{study.config.window_end} {study.config.timezone} · {study.config.symbols.join(', ')}</p>
      <p className="muted">{money(study.config.initial_cash)} initial capital per pair · settings fixed at start · {study.last_tick_at ? `Last background check ${when(study.last_tick_at)} UTC` : 'Waiting for the first window'}{study.round ? ` · ${study.round.stage}` : ''}</p>
      {study.last_error && <p className="form-error" role="status">{study.last_error}</p>}
      <PercentChart key={study.id} series={[
        ...study.accounts.map(account => ({ id: account.id, name: account.name, benchmark: false, points: study.points.map(point => ({ date: point.timestamp, value: point.returns[account.id] })) })),
        { id: 'benchmark', name: 'S&P 500 · SPY', benchmark: true, points: study.points.map(point => ({ date: point.timestamp, value: point.benchmark_pct })) },
      ]} />
      <p className="muted">Return = (current equity ÷ initial capital − 1) × 100. Agent returns include costs; SPY includes verified corporate actions before costs. Points are recorded inside decision windows; gaps show periods without a verified valuation.</p>
      <div className="live-account-grid">{study.accounts.map(account => <details key={account.id}><summary><span>{account.name}</span><strong>{percent(account.return_pct)}</strong><small>{account.status.replaceAll('_', ' ')}</small></summary>
        <p>Total equity {money(account.equity, 2)} · available cash {money(Number(account.book.cash), 2)}</p>
        <p>{Object.keys(account.book.holdings).length ? Object.entries(account.book.holdings).map(([symbol, quantity]) => `${symbol}: ${Number(quantity).toLocaleString('en-CA', { maximumFractionDigits: 6 })} shares`).join(' · ') : 'No positions held.'}</p>
        <p>Unsettled dividends {money(Object.values(account.book.receivables).reduce((sum, item) => sum + Number(item.amount), 0), 2)}</p>
      </details>)}</div>
    </section>
    <section className="card live-audit"><div className="card-heading"><div><div className="eyebrow">OBSERVATIONS AND ACTIONS</div><h2>Current study record</h2></div>
      {study.round?.snapshot_id && <button className="button secondary" onClick={() => void inspect(study.round!.snapshot_id!)}>Inspect shared news and prices</button>}</div>
      <ol>{study.events.map(item => <li key={item.id}><time dateTime={item.timestamp}>{when(item.timestamp)} UTC</time><strong>{item.account_id ? study.accounts.find(account => account.id === item.account_id)?.name : 'All participants'}</strong><p>{item.message}</p>
        {item.type === 'fill' && <small>{String(item.details.quantity)} shares at {money(Number(item.details.price), 2)} · fee {money(Number(item.details.fee), 2)} · source quote {when(String(item.details.quote_as_of))} UTC</small>}
        {item.type === 'decision' && <details><summary>Decision and input record</summary><pre>{JSON.stringify(item.details, null, 2)}</pre>
          {typeof item.details.shared_snapshot_id === 'string' && <button className="text-button" onClick={() => void inspect(item.details.shared_snapshot_id as string)}>Inspect this common snapshot</button>}</details>}
      </li>)}</ol>{!study.events.length && <p className="muted">The first shared observation will appear during an eligible window.</p>}
    </section></>}
    {shared && <section className="card live-shared" aria-labelledby="shared-title"><h2 id="shared-title">Exactly what every agent could see</h2><p>{when(shared.captured_at)} UTC · snapshot <code>{shared.hash}</code></p>
      <p>{shared.news_sources.map(source => `${source.name}: ${source.status}`).join(' · ')}</p>
      <ul>{Object.entries(shared.quotes).map(([symbol, quote]) => <li key={symbol}>{symbol} · {money(quote.price, 2)} · {quote.source} · {when(quote.as_of)} UTC</li>)}</ul>
      <h3>Common news corpus · {shared.news.length} articles</h3>{shared.news.length ? <ul>{shared.news.map(item => <li key={item.id}><a href={item.url} target="_blank" rel="noreferrer">{item.title}</a><p>{item.summary}</p><small>{item.provider} · {when(item.published_at)} UTC</small></li>)}</ul> : <p>The connected news provider returned no articles for this snapshot.</p>}
      <h3>Common events</h3><ul>{shared.events.map(item => <li key={item.id}><a href={item.url} target="_blank" rel="noreferrer">{item.title}</a> · {item.date}<p>{item.summary}</p></li>)}</ul>
    </section>}
    {creating && <LiveStudyDialog catalog={catalog} onClose={onClose} onCreated={value => { setStudies(current => [value, ...current]); setDetail(value); setSelected(value.id); setShared(null); onClose(); }} />}
  </section>;
}
