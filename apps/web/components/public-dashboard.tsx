'use client';

import { useEffect, useState } from 'react';
import { ArrowUpRight, ChartNoAxesCombined, LockKeyhole } from 'lucide-react';

type Series = { id: string; name: string; benchmark: boolean; points: { date: string; value: number }[] };
export type PublicSnapshot = {
  agents: { id: string; name: string }[];
  study: { id: string; recorded_at: string; mode: string } | null;
  series: Series[];
  activities: { id: string; agent: string; action: 'buy' | 'sell'; symbol: string; session_date: string }[];
};
const COLORS = ['#087f70', '#bc7839', '#7773a6', '#3281a5', '#ad626b', '#657a3c', '#34423d'];
const day = (value: string) => new Date(value).toLocaleDateString('en-CA', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });

function Performance({ series }: { series: Series[] }) {
  const [hidden, setHidden] = useState<string[]>([]);
  const [hover, setHover] = useState<number | null>(null);
  const active = series.filter(s => !hidden.includes(s.id));
  const values = active.flatMap(s => s.points.map(p => p.value));
  const low = Math.min(100, ...values), high = Math.max(100, ...values);
  const pad = Math.max((high - low) * .15, 1);
  const min = low - pad, max = high + pad;
  const width = 960, height = 340, left = 48, right = 22, top = 18, bottom = 40;
  const reference = series[0]?.points ?? [];
  const count = Math.max(reference.length - 1, 1);
  const x = (i: number) => left + i / count * (width - left - right);
  const y = (n: number) => top + (max - n) / (max - min) * (height - top - bottom);
  return <div data-testid="public-performance">
    <div className="public-legend">{series.map((s, i) => <button key={s.id} aria-pressed={!hidden.includes(s.id)}
      onClick={() => { setHover(null); setHidden(v => v.includes(s.id) ? v.filter(id => id !== s.id) : v.length < series.length - 1 ? [...v, s.id] : v); }}>
      <i style={{ background: s.benchmark ? '#34423d' : COLORS[i % COLORS.length] }} />{s.name}
    </button>)}</div>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Agent portfolio performance and market benchmark, indexed to 100" className="public-chart">
      {[0, 1, 2, 3, 4].map(i => { const v = min + (max - min) * i / 4; return <g key={i}>
        <line x1={left} x2={width - right} y1={y(v)} y2={y(v)} stroke="#e6ebe5" strokeDasharray="3 5" />
        <text x={left - 10} y={y(v) + 4} textAnchor="end">{v.toFixed(0)}</text></g>; })}
      <line x1={left} x2={width - right} y1={y(100)} y2={y(100)} stroke="#a8b5ac" strokeDasharray="5 5" />
      {series.map((s, i) => !hidden.includes(s.id) && <path key={s.id} d={s.points.map((p, j) => `${j ? 'L' : 'M'}${x(j).toFixed(2)},${y(p.value).toFixed(2)}`).join(' ')}
        fill="none" stroke={s.benchmark ? '#34423d' : COLORS[i % COLORS.length]} strokeWidth="2.5" strokeDasharray={s.benchmark ? '7 5' : undefined} strokeLinejoin="round" />)}
      {[0, .25, .5, .75, 1].map(part => { const i = Math.round(count * part); return <text key={part} x={x(i)} y={height - 12} textAnchor={part === 0 ? 'start' : part === 1 ? 'end' : 'middle'}>{reference[i] ? day(reference[i].date) : ''}</text>; })}
      {hover != null && <line x1={x(hover)} x2={x(hover)} y1={top} y2={height - bottom} stroke="#849b8d" />}
      <rect x={left} y={top} width={width - left - right} height={height - top - bottom} fill="transparent" onPointerMove={event => {
        const rect = event.currentTarget.ownerSVGElement!.getBoundingClientRect();
        const position = (event.clientX - rect.left) / rect.width * width;
        setHover(Math.max(0, Math.min(count, Math.round((position - left) / (width - left - right) * count))));
      }} onPointerLeave={() => setHover(null)} />
    </svg>
    <label className="sr-only" htmlFor="public-chart-point">Inspect performance date</label>
    <input id="public-chart-point" className="public-chart-slider" type="range" min={0} max={count} value={hover ?? count} onChange={e => setHover(Number(e.target.value))} />
    <div className="public-point" aria-live="polite"><span>{reference[hover ?? count] ? day(reference[hover ?? count].date) : ''}</span>
      {active.map(s => <span key={s.id}>{s.name} <strong>{s.points[hover ?? count]?.value.toFixed(2) ?? '—'}</strong></span>)}</div>
  </div>;
}

export function PublicDashboard() {
  const [snapshot, setSnapshot] = useState<PublicSnapshot | null>(null);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setError(false);
    fetch('/api/public/dashboard', { signal: controller.signal, cache: 'no-store' }).then(async r => {
      if (!r.ok) throw new Error(); const data = await r.json(); if (!controller.signal.aborted) setSnapshot(data);
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [revision]);
  return <div className="public-shell"><a href="#public-main" className="skip-link">Skip to content</a>
    <header className="public-header"><a href="/" className="brand" aria-label="Parallax Lab home"><span className="brand-mark" /><span>parallax lab<span className="brand-period">.</span></span></a>
      <a href="/workspace" className="button secondary"><LockKeyhole size={14} />Owner workspace</a></header>
    <main id="public-main" className="public-main"><div className="public-intro"><p className="eyebrow">AN OPEN NOTEBOOK OF PAPER INVESTING</p>
      <h1>Different minds.<br /><em>One market.</em></h1><p>Follow the agents, their decisions and how their portfolios compare with the market.</p></div>
      {error && <div className="public-error" role="alert">The dashboard could not load. <button className="text-button" onClick={() => setRevision(v => v + 1)}>Try again</button></div>}
      {!snapshot && !error && <p role="status">Loading the research dashboard…</p>}
      {snapshot && <><section className="public-agents" aria-labelledby="agents-title"><div className="public-section-title"><span className="eyebrow">THE PARTICIPANTS</span><h2 id="agents-title">Meet the agents.</h2></div>
        <div className="public-agent-list">{snapshot.agents.map((agent, i) => <article key={agent.id}><span className="public-agent-number">{String(i + 1).padStart(2, '0')}</span><h3>{agent.name}</h3><ArrowUpRight size={18} /></article>)}</div></section>
      <section className="public-performance card" aria-labelledby="performance-title"><div className="public-section-title"><span className="eyebrow">PORTFOLIO PERFORMANCE</span><h2 id="performance-title">Together, on one chart.</h2>
        <p>Each portfolio starts at 100. The market benchmark appears as a dashed line.</p></div>
        {snapshot.series.length ? <Performance key={snapshot.study?.id} series={snapshot.series} /> : <div className="public-empty"><ChartNoAxesCombined size={32} /><h3>No published results yet.</h3><p>Performance lines will appear after an eligible experiment is completed and published.</p></div>}
        {snapshot.series.length > 0 && <p className="public-chart-note">Latest published comparison · historical paper replay · agent portfolios net of costs.{snapshot.series.some(s => s.benchmark) ? ' SPY is an adjusted buy-and-hold benchmark before costs.' : ' A matching market benchmark is not available for this run.'}</p>}</section>
      <section className="public-activity" aria-labelledby="activity-title"><div className="public-section-title"><span className="eyebrow">THE DECISION RECORD</span><h2 id="activity-title">What happened, and when.</h2><p>Historical replay session dates. These are paper actions, not live broker orders.</p></div>
        {snapshot.activities.length ? <ol>{snapshot.activities.map(item => <li key={item.id}><time dateTime={item.session_date}>{day(item.session_date)}</time><strong>{item.agent}</strong><span className={`public-action ${item.action}`}>{item.action === 'buy' ? 'Bought' : 'Sold'}</span><span>{item.symbol}</span></li>)}</ol>
          : <p className="public-activity-empty">No published activity yet.</p>}</section></>}
      <footer className="public-footer"><span>Parallax Lab · Paper research</span><span>Settings and source data stay in the private workspace.</span></footer>
    </main></div>;
}
