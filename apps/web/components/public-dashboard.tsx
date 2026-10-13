'use client';

import { useEffect, useState } from 'react';
import { PercentChart } from './percent-chart';
import { ArrowUpRight, ChartNoAxesCombined, LockKeyhole } from 'lucide-react';

type Series = { id: string; name: string; benchmark: boolean; points: { date: string; value: number }[] };
export type PublicSnapshot = {
  agents: { id: string; name: string }[];
  study: { id: string; recorded_at: string; mode: string } | null;
  series: Series[];
  activities: { id: string; agent: string; action: 'buy' | 'sell'; symbol: string; session_date: string }[];
};
const day = (value: string) => new Date(value).toLocaleDateString('en-CA', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
const actionTime = (value: string) => value.includes('T') ? new Date(value).toLocaleString('en-CA', { timeZone: 'UTC', hour12: false }) + ' UTC' : day(value);

function Performance({ series }: { series: Series[] }) {
  return <div data-testid="public-performance"><PercentChart series={series} /></div>;
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
        <p>Each portfolio starts at 0% return. The market benchmark appears as a dashed line.</p></div>
        {snapshot.series.length ? <Performance key={snapshot.study?.id} series={snapshot.series} /> : <div className="public-empty"><ChartNoAxesCombined size={32} /><h3>No published results yet.</h3><p>Performance lines will appear when an eligible study records verified results for publication.</p></div>}
        {snapshot.series.length > 0 && <p className="public-chart-note">Latest published comparison · {snapshot.study?.mode === 'ongoing_paper_study' ? 'ongoing paper study' : 'historical paper replay'} · agent portfolios net of costs.{snapshot.series.some(s => s.benchmark) ? ' SPY includes verified corporate actions, before costs.' : ' A matching market benchmark is not available for this run.'}</p>}</section>
      <section className="public-activity" aria-labelledby="activity-title"><div className="public-section-title"><span className="eyebrow">THE DECISION RECORD</span><h2 id="activity-title">What happened, and when.</h2><p>Recorded paper actions and their observation times. These are simulated fills, not broker orders.</p></div>
        {snapshot.activities.length ? <ol>{snapshot.activities.map(item => <li key={item.id}><time dateTime={item.session_date}>{actionTime(item.session_date)}</time><strong>{item.agent}</strong><span className={`public-action ${item.action}`}>{item.action === 'buy' ? 'Bought' : 'Sold'}</span><span>{item.symbol}</span></li>)}</ol>
          : <p className="public-activity-empty">No published activity yet.</p>}</section></>}
      <footer className="public-footer"><span>Parallax Lab · Paper research · By <a className="footer-credit" href="https://kdeng4.github.io/" target="_blank" rel="noopener noreferrer">Patrick Deng</a></span><span>Settings and source data stay in the private workspace.</span></footer>
    </main></div>;
}
