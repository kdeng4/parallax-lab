'use client';

import { useCallback, useEffect, useState } from 'react';
import { Activity, ArrowDownRight, ArrowRight, ArrowUpRight, BarChart3, BookOpen, Check, ChevronDown, ChevronRight, CircleHelp, Clock3, Code2, Download, FlaskConical, Layers3, LoaderCircle, Menu, Plus, RefreshCw, ShieldCheck, Sparkles, TrendingUp, X } from 'lucide-react';
import { api, date, money, percent, time } from '@/lib/api';
import type { EditorAccess } from '@/lib/editor-access';
import type { Catalog, Comparison, Detail, Experiment, Run, Section } from '@/lib/types';
import { EquityChart, RUN_COLORS } from './equity-chart';
import { ExperimentDialog } from './experiment-dialog';
import { AuditTimeline } from './audit-timeline';
import { MarketOverview } from './market-overview';

const NAV_ITEMS: { id: Section; title: string; icon: typeof BarChart3 }[] = [
  { id: 'overview', title: 'Overview', icon: BarChart3 },
  { id: 'experiments', title: 'Experiments', icon: FlaskConical },
  { id: 'strategies', title: 'Strategies', icon: Layers3 },
  { id: 'audit', title: 'Audit trail', icon: Activity },
];

export function Workbench() {
  const [access, setAccess] = useState<EditorAccess>({ canEdit: false, email: null, reason: 'sign_in' });
  const canEdit = access.canEdit;
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [experiment, setExperiment] = useState<Detail | null>(null);
  const [section, setSection] = useState<Section>('overview');
  const [comparison, setComparison] = useState<Comparison>('models');
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState('');
  const [modal, setModal] = useState(false);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [refreshId, setRefreshId] = useState(0);
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [nextCatalog, result] = await Promise.all([api<Catalog>('/catalog'), api<{ experiments: Experiment[] }>('/experiments')]);
      setCatalog(nextCatalog); setExperiments(result.experiments);
      setSelectedId((current) => current || result.experiments[0]?.id || '');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not connect to the research service.'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load, refreshId]);
  useEffect(() => {
    let cancelled = false;
    fetch('/api/session', { cache: 'no-store' }).then(async response => {
      if (!response.ok) throw new Error('Session unavailable');
      const session: EditorAccess = await response.json();
      if (!cancelled) setAccess(session);
    }).catch(() => { if (!cancelled) setAccess({ canEdit: false, email: null, reason: 'sign_in' }); });
    return () => { cancelled = true; };
  }, [refreshId]);
  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    setDetailLoading(true); setError('');
    api<Detail>(`/experiments/${selectedId}`).then((detail) => { if (!cancelled) { setExperiment(detail); setComparison(detail.comparison); } }).catch((reason) => { if (!cancelled) setError(reason.message); }).finally(() => { if (!cancelled) setDetailLoading(false); });
    return () => { cancelled = true; };
  }, [selectedId, refreshId]);

  function navigate(next: Section) { setSection(next); setMobileMenu(false); setNotice(''); }
  function chooseComparison(next: Comparison) {
    setComparison(next);
    const match = experiments.find((item) => item.comparison === next);
    if (match) setSelectedId(match.id);
  }
  function created(detail: Detail) {
    setExperiments((current) => [detail, ...current]); setExperiment(detail); setSelectedId(detail.id); setComparison(detail.comparison); setSection('overview'); setModal(false);
    setNotice(`“${detail.name}” completed. ${detail.participants} paper accounts compared on identical market data.`);
  }
  const comparisonExperiments = experiments.filter((item) => item.comparison === comparison);
  const matchingExperiment = experiment?.comparison === comparison && experiment.id === selectedId ? experiment : null;
  const selectedExperiment = experiment?.id === selectedId ? experiment : null;
  const busy = loading || detailLoading;

  return <div className="workbench">
    <a href="#main-content" className="skip-link">Skip to content</a>
    {mobileMenu && <button className="sidebar-backdrop" aria-label="Close navigation" onClick={() => setMobileMenu(false)} />}
    <aside className={`sidebar ${mobileMenu ? 'open' : ''}`}>
      <a className="brand" href="/" aria-label="Parallax Lab home"><span className="brand-mark" aria-hidden="true" /><span>parallax lab<span className="brand-period">.</span></span></a>
      <div className="workspace-switch"><div className="workspace-avatar">P</div><span>Research workspace<small>Paper trading environment</small></span><span className="workspace-status" title="Research workspace" /></div>
      <div className="nav-label">WORKSPACE</div>
      <nav aria-label="Main navigation">{NAV_ITEMS.map(({ id, title, icon: Icon }) => <button key={id} className={`nav-item ${section === id ? 'active' : ''}`} aria-current={section === id ? 'page' : undefined} onClick={() => navigate(id)}><Icon size={18} strokeWidth={1.7} /><span>{title}</span>{id === 'experiments' && experiments.length > 0 && <span className="nav-count">{experiments.length}</span>}{section === id && <span className="nav-active-dot" />}</button>)}</nav>
      <div className="sidebar-research"><span className="sidebar-research-icon"><FlaskConical size={19} strokeWidth={1.5} /></span><h3>Ideas meet evidence.</h3><p>Compare fairly.<br />Learn from every decision.</p><button className="text-button" disabled={!catalog || !canEdit} onClick={() => { setModal(true); setMobileMenu(false); }}>Start an experiment<ArrowUpRight size={15} /></button></div>
      <div className="sidebar-bottom"><div className="safe-mode"><ShieldCheck size={16} /><span>Paper trading only</span><span className="status-dot" /></div><div className="user-row"><span className="user-avatar">P</span><span>Parallax Lab<small>{access.reason === 'local' ? 'Local development' : canEdit ? 'Approved editor' : 'Read only'}</small></span><span className="version-pill">v0.1</span></div></div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb"><button className="icon-button menu-toggle" aria-label="Open navigation" aria-expanded={mobileMenu} onClick={() => setMobileMenu(!mobileMenu)}><Menu size={20} /></button><span>Workspace</span><ChevronRight size={13} /><strong>{NAV_ITEMS.find((item) => item.id === section)?.title}</strong></div><div className="topbar-right">{selectedExperiment && <span className="topbar-date">{date(selectedExperiment.created_at)}</span>}<span className="environment-label"><span className="status-dot" />Paper environment</span><div className="topbar-divider" /><span className="topbar-initial">P</span></div></header>
      <main id="main-content" tabIndex={-1}>
        <div className="page-heading"><div><div className="eyebrow heading-eyebrow">THE RESEARCH WORKBENCH</div><h1>{section === 'overview' ? 'A little more signal.' : section === 'experiments' ? 'Your ideas, put to the test.' : section === 'strategies' ? 'The thinking behind the trade.' : 'Nothing lost in the details.'}</h1><p>{section === 'overview' ? 'Different approaches. Identical conditions. A clearer perspective.' : section === 'experiments' ? 'Every experiment is a reproducible record of what worked—and why.' : section === 'strategies' ? 'Versioned Markdown strategies. Explicit rules. Reproducible comparisons.' : 'Follow every observation, decision, and paper fill from start to finish.'}</p></div><button className="button primary new-experiment" onClick={() => setModal(true)} disabled={!catalog || !canEdit}><Plus size={17} />New experiment</button></div>
        <div className="mode-note"><ShieldCheck size={14} /><span>Paper trading</span><span className="note-dot">·</span><span>{catalog?.data_source === 'synthetic' ? 'Local test fixtures' : 'Real daily market data'}</span><span className="note-dot">·</span><span>Local baseline models</span></div>
        {!canEdit && <div className="mode-note" role="status"><ShieldCheck size={14} /><span>{access.reason === 'not_configured' ? 'Read only. Editor sign-in is awaiting setup.' : access.reason === 'not_approved' ? 'Read only. Your account has not been approved to create experiments.' : 'Read only. Creating experiments requires an approved editor sign-in.'}</span></div>}
        {notice && <div className="success-notice" role="status"><Check size={17} /><span>{notice}</span><button className="icon-button" onClick={() => setNotice('')} aria-label="Dismiss notification"><X size={15} /></button></div>}
        {error && <div className="error-banner" role="alert"><div><strong>We couldn’t load the research data.</strong><span>{error}</span></div><button className="button secondary" onClick={() => setRefreshId((value) => value + 1)}><RefreshCw size={15} />Try again</button></div>}
        {loading && !catalog ? <LoadingState /> : <>
          {section === 'overview' && <>
            <MarketOverview />
            <div className="comparison-bar"><div role="tablist" aria-label="Comparison dimension" className="comparison-tabs"><button id="models-tab" role="tab" aria-selected={comparison === 'models'} aria-controls="comparison-panel" className={comparison === 'models' ? 'active' : ''} onClick={() => chooseComparison('models')}><Layers3 size={16} />Model comparison</button><button id="strategies-tab" role="tab" aria-selected={comparison === 'strategies'} aria-controls="comparison-panel" className={comparison === 'strategies' ? 'active' : ''} onClick={() => chooseComparison('strategies')}><Code2 size={16} />Strategy comparison</button></div><span className="comparison-hint">One variable. A fair comparison.</span></div>
            <div id="comparison-panel" role="tabpanel" aria-busy={detailLoading} aria-labelledby={`${comparison}-tab`}>
              <div className="experiment-toolbar"><div className="experiment-picker"><FlaskConical size={17} /><label htmlFor="experiment-selector" className="sr-only">Selected experiment</label><select id="experiment-selector" value={comparisonExperiments.some((item) => item.id === selectedId) ? selectedId : ''} onChange={(event) => setSelectedId(event.target.value)}>{comparisonExperiments.length === 0 && <option value="">No {comparison} experiments yet</option>}{comparisonExperiments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><ChevronDown size={14} /></div><div className="toolbar-actions">{matchingExperiment && <span className="completed-badge"><span className="status-dot" />Completed</span>}<button className="icon-button" aria-label="Refresh experiments" title="Refresh experiments" disabled={busy} onClick={() => setRefreshId((value) => value + 1)}><RefreshCw size={16} className={busy ? 'spin' : ''} /></button>{matchingExperiment && <a className="button secondary small" href={`/api/v1/experiments/${matchingExperiment.id}/export`} download={`${matchingExperiment.id}.json`}><Download size={15} />Export</a>}</div></div>
              {detailLoading && !matchingExperiment ? <LoadingState /> : matchingExperiment ? <Overview key={matchingExperiment.id} experiment={matchingExperiment} onAudit={() => navigate('audit')} /> : <div className="card empty-state comparison-empty"><FlaskConical size={32} /><h2>A new perspective starts here.</h2><p>{comparison === 'strategies' ? 'Keep one model fixed and compare different strategy scripts on identical market data.' : 'Compare independent model decisions using one shared strategy and market dataset.'}</p><button className="button primary" disabled={!catalog || !canEdit} onClick={() => setModal(true)}><Plus size={16} />Create {comparison === 'models' ? 'model' : 'strategy'} experiment</button></div>}
            </div>
          </>}
          {section === 'experiments' && <Experiments canEdit={canEdit} experiments={experiments} onSelect={(item) => { setSelectedId(item.id); setComparison(item.comparison); navigate('overview'); }} onCreate={() => setModal(true)} />}
          {section === 'strategies' && catalog && <Strategies canEdit={canEdit} catalog={catalog} onCreate={() => { setComparison('strategies'); setModal(true); }} />}
          {section === 'audit' && (selectedId ? <><div className="audit-experiment-picker"><label htmlFor="audit-experiment">Experiment</label><select id="audit-experiment" value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>{experiments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>{selectedExperiment && <a className="button secondary small" href={`/api/v1/experiments/${selectedExperiment.id}/export`} download><Download size={15} />Export full record</a>}</div>{detailLoading ? <LoadingState /> : selectedExperiment ? <AuditTimeline key={selectedExperiment.id} experiment={selectedExperiment} /> : <div className="card empty-state"><Activity size={28} /><h2>Experiment unavailable</h2><p>Use Try again above to reload this experiment.</p></div>}</> : <div className="card empty-state"><Activity size={28} /><h2>No events yet</h2><p>Create an experiment to start its audit trail.</p></div>)}
        </>}
        <footer className="page-footer"><span><span className="footer-mark">PL.</span> Built for better questions.</span><span>Research, measured.<span className="footer-dot">·</span> No real funds at risk</span></footer>
      </main>
    </div>
    {modal && catalog && canEdit && <ExperimentDialog catalog={catalog} initialComparison={comparison} onClose={() => setModal(false)} onCreated={created} />}
  </div>;
}

function LoadingState() { return <div className="loading-state" role="status"><LoaderCircle size={23} className="spin" /><span>Preparing your research workspace…</span><div className="loading-skeleton"><div /><div /><div /></div></div>; }

function Overview({ experiment, onAudit }: { experiment: Detail; onAudit: () => void }) {
  const best = [...experiment.runs].sort((a, b) => b.return_pct - a.return_pct)[0];
  const trades = experiment.runs.reduce((count, run) => count + run.trade_count, 0);
  const label = best ? experiment.comparison === 'models' ? best.model_name : best.strategy_name : '—';
  const worstDrawdown = Math.max(...experiment.runs.map((run) => run.max_drawdown_pct), 0);
  return <>
    <div className="metrics-grid"><Metric label="LEADING RETURN" value={percent(best?.return_pct ?? 0)} detail={label} icon={TrendingUp} positive={(best?.return_pct ?? 0) >= 0} /><Metric label="STARTING CAPITAL" value={money(experiment.initial_cash)} detail="Per independent paper account" icon={Layers3} /><Metric label="MAX. DRAWDOWN" value={`${worstDrawdown.toFixed(2)}%`} detail="Largest peak-to-trough across accounts" icon={ArrowDownRight} /><Metric label="EXECUTED TRADES" value={trades.toLocaleString('en-CA')} detail={`${experiment.participants} participants · ${experiment.bars} market bars`} icon={Activity} /></div>
    <EquityChart experiment={experiment} />
    <div className="experiment-context"><div><span className="context-symbol">{experiment.symbol}</span><span>{experiment.data_source === 'synthetic' ? 'Synthetic 1m fixture' : 'Tiingo adjusted daily candles'}</span></div><span className="context-divider" /><div><span className="context-label">{experiment.comparison === 'models' ? 'Strategy' : 'Model'}</span><strong>{experiment.comparison === 'models' ? experiment.strategy_name : experiment.runs[0]?.model_name}</strong></div><span className="context-divider" /><div><span className="context-label">Execution</span><strong>Next-bar open</strong></div><div className="context-seed"><span className="context-label">{experiment.seed == null ? 'As of' : 'Seed'}</span><strong>{experiment.seed ?? experiment.metadata?.dataset.as_of ?? '—'}</strong><span className="context-lock"><ShieldCheck size={13} />Matched inputs</span></div></div>
    <PerformanceTable experiment={experiment} />
    <div className="bottom-grid"><AuditTimeline experiment={experiment} compact onViewAll={onAudit} /><section className="methodology-card"><span className="methodology-icon"><ShieldCheck size={22} strokeWidth={1.5} /></span><div className="eyebrow">CONFIDENCE IN THE COMPARISON</div><h2>Same starting line.<br /> Independent decisions.</h2><p>Each participant sees the same candles and starts with the same capital. Only your chosen variable changes.</p><ul><li><Check size={14} />Shared dataset, verified by hash</li><li><Check size={14} />Long-only, unleveraged paper accounts</li><li><Check size={14} />Fees & slippage included in every fill</li><li><Check size={14} />Every decision leaves an audit trail</li></ul><details className="methodology-details"><summary>View execution assumptions<ChevronDown size={14} /></summary><p>Signals at a bar’s close execute at the next bar’s open. Fee: {experiment.costs.fee_bps} bps. Slippage: {experiment.costs.slippage_bps} bps. No real orders or cloud inference is used. {experiment.metadata?.dataset.limitations}</p><p>Sharpe uses {experiment.interval === '1d' ? 'daily equity returns and 252 sessions per year' : '1-minute equity returns and 252 × 390 market minutes per year'}. Historical replay statistics do not predict future performance. Win rate is profitable sell fills divided by all sell fills; each partial exit counts once, and open positions are excluded.</p><code>Dataset {experiment.data_hash}</code></details></section></div>
  </>;
}

function Metric({ label, value, detail, icon: Icon, positive }: { label: string; value: string; detail: string; icon: typeof TrendingUp; positive?: boolean }) { return <section className="metric-card"><div className="metric-top"><span>{label}</span><Icon size={16} strokeWidth={1.5} /></div><div className={`metric-value ${positive === true ? 'positive' : positive === false ? 'negative' : ''}`}>{value}</div><div className="metric-detail">{positive !== undefined && <span className={`tiny-dot ${positive ? '' : 'loss'}`} />}{detail}</div></section>; }

function PerformanceTable({ experiment }: { experiment: Detail }) {
  const [expanded, setExpanded] = useState('');
  const sorted = [...experiment.runs].sort((a, b) => b.return_pct - a.return_pct);
  return <section className="card performance-card"><div className="card-heading"><div><div className="eyebrow">THE NUMBERS, SIDE BY SIDE</div><h2>Participant performance</h2></div><span className="subtle-label">Ranked by net return</span></div><div className="table-scroll"><table data-testid="performance-table" className="performance-table"><thead><tr><th scope="col">{experiment.comparison === 'models' ? 'Model' : 'Strategy'}</th><th scope="col">Net equity</th><th scope="col">Return</th><th scope="col">Max drawdown</th><th scope="col"><span title={`Annualized from ${experiment.interval === '1d' ? 'daily returns, 252 sessions' : '1-minute returns, 252 × 390 minutes'} per year; zero risk-free rate. Historical samples are not predictive.`}>Sharpe <CircleHelp size={12} /></span></th><th scope="col"><span title="Profitable sell fills / all sell fills. Partial exits each count once; open positions are excluded.">Win rate <CircleHelp size={12} /></span></th><th scope="col">Trades</th><th scope="col"><span className="sr-only">Account details</span></th></tr></thead><tbody>{sorted.map((run, rank) => <PerformanceRow key={run.id} run={run} rank={rank} color={RUN_COLORS[experiment.runs.indexOf(run) % RUN_COLORS.length]} comparison={experiment.comparison} expanded={expanded === run.id} onExpand={() => setExpanded((current) => current === run.id ? '' : run.id)} />)}</tbody></table></div><div className="table-note"><span><ShieldCheck size={13} />All returns include execution costs.</span><span>Click a participant to inspect its paper account.</span></div></section>;
}

function PerformanceRow({ run, rank, color, comparison, expanded, onExpand }: { run: Run; rank: number; color: string; comparison: Comparison; expanded: boolean; onExpand: () => void }) {
  const label = comparison === 'models' ? run.model_name : run.strategy_name;
  return <><tr className={expanded ? 'expanded' : ''}><td><button className="participant-button" onClick={onExpand} aria-expanded={expanded} aria-label={`Inspect ${label} account`}><span className="participant-rank">{String(rank + 1).padStart(2, '0')}</span><span className="participant-color" style={{ background: color }} /><span className="participant-name">{label}<small>{comparison === 'models' ? run.provider : run.model_name}</small></span>{rank === 0 && <span className="leader-badge">Leading</span>}</button></td><td className="equity-cell">{money(run.equity, 2)}</td><td><span className={`return-badge ${run.return_pct < 0 ? 'loss' : ''}`}>{percent(run.return_pct)}</span></td><td>{run.max_drawdown_pct.toFixed(2)}%</td><td>{run.sharpe === null ? <span title="Insufficient return variance or observations">—</span> : run.sharpe.toFixed(2)}</td><td>{run.win_rate_pct.toFixed(1)}%</td><td>{run.trade_count}</td><td><button className="icon-button" onClick={onExpand} aria-label={`${expanded ? 'Collapse' : 'Expand'} ${label}`} aria-expanded={expanded}><ChevronDown size={15} className={expanded ? 'rotate' : ''} /></button></td></tr>{expanded && <tr className="account-details-row"><td colSpan={8}><div className="account-stats"><div><span>Available cash</span><strong>{money(run.cash, 2)}</strong></div><div><span>Position quantity</span><strong>{run.position_qty.toLocaleString('en-CA', { maximumFractionDigits: 4 })}</strong></div><div><span>Net P&L</span><strong className={run.pnl >= 0 ? 'positive' : 'negative'}>{money(run.pnl, 2)}</strong></div><div><span>Strategy version</span><code title={run.strategy_version}>{run.strategy_version.slice(0, 16)}…</code></div></div>{run.trades.length > 0 ? <div className="trade-preview"><strong>Recent fills</strong>{run.trades.slice(-5).reverse().map((trade) => <div key={trade.id}><time>{time(trade.timestamp)} UTC</time><span className={`trade-side ${trade.side}`}>{trade.side}</span><span>{trade.quantity.toLocaleString('en-CA', { maximumFractionDigits: 4 })} units @ {money(trade.price, 2)}</span><span className="trade-fee">Fee {money(trade.fee, 2)}</span></div>)}</div> : <p className="muted">This participant did not execute any trades.</p>}</td></tr>}</>;
}

function Experiments({ canEdit, experiments, onSelect, onCreate }: { canEdit: boolean; experiments: Experiment[]; onSelect: (experiment: Experiment) => void; onCreate: () => void }) {
  const [filter, setFilter] = useState('all');
  const visible = experiments.filter((item) => filter === 'all' || item.comparison === filter);
  return <section className="card history-card"><div className="card-heading"><div><div className="eyebrow">REPRODUCIBLE RESEARCH</div><h2>Experiment library <span className="heading-count">{experiments.length}</span></h2></div><label className="history-filter"><span className="sr-only">Filter experiments</span><select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All comparisons</option><option value="models">Models</option><option value="strategies">Strategies</option></select></label></div>{visible.length === 0 ? <div className="empty-state"><FlaskConical size={28} /><h3>No experiments here yet</h3><p>Put your next hypothesis to the test.</p><button className="button primary" onClick={onCreate} disabled={!canEdit}><Plus size={15} />Create experiment</button></div> : <div className="experiment-list">{visible.map((item) => <button className="experiment-list-item" key={item.id} onClick={() => onSelect(item)}><span className="experiment-list-icon">{item.comparison === 'models' ? <Layers3 size={20} /> : <Code2 size={20} />}</span><span className="experiment-list-name"><strong>{item.name}</strong><span>{item.comparison === 'models' ? 'Model comparison' : 'Strategy comparison'}<i />{item.symbol}<i />{item.participants} participants</span></span><span className="experiment-list-date">{date(item.created_at)}<small>{item.bars} {item.data_source === 'synthetic' ? `bars · seed ${item.seed}` : 'daily sessions · Tiingo'}</small></span><span className={`experiment-list-return ${item.best_return_pct < 0 ? 'negative' : 'positive'}`}>{percent(item.best_return_pct)}<small>Leading return</small></span><span className="completed-badge"><span className="status-dot" />Completed</span><ChevronRight size={17} /></button>)}</div>}<div className="table-note"><span><ShieldCheck size={13} />All experiments use paper capital and preserve the exact input dataset and its source.</span></div></section>;
}

function Strategies({ canEdit, catalog, onCreate }: { canEdit: boolean; catalog: Catalog; onCreate: () => void }) {
  const [selected, setSelected] = useState(catalog.strategies[0]?.id ?? '');
  const strategy = catalog.strategies.find((item) => item.id === selected);
  return <><div className="strategy-layout"><section className="strategy-list" aria-label="Strategy scripts">{catalog.strategies.map((item, index) => <button key={item.id} onClick={() => setSelected(item.id)} className={`strategy-item ${selected === item.id ? 'selected' : ''}`} aria-pressed={selected === item.id}><span className="strategy-number">0{index + 1}</span><span><strong>{item.name}</strong><small>{item.description}</small><span className="strategy-file"><Code2 size={12} />{item.id}.md</span></span><ChevronRight size={16} /></button>)}<div className="strategy-tip"><BookOpen size={19} /><p>Strategy files describe the rules each participant follows. Content hashes preserve the exact version behind every run.</p></div></section>{strategy && <section className="card strategy-editor"><div className="editor-toolbar"><span><Code2 size={16} />{strategy.id}.md</span><span className="readonly-badge">Read only</span></div><div className="markdown-preview"><div className="eyebrow">STRATEGY DEFINITION</div><h2>{strategy.name}</h2><p>{strategy.description}</p><pre>{strategy.markdown}</pre></div><div className="editor-footer"><span title={strategy.version}><ShieldCheck size={13} />SHA-256 {strategy.version.slice(0, 16)}…</span><button className="text-button" onClick={onCreate} disabled={!canEdit}>Compare strategies<ArrowRight size={14} /></button></div></section>}</div><section className="provider-note"><div><Sparkles size={20} /><h3>A common interface. Room to grow.</h3><p>The workbench runs actual local algorithms today. OpenAI and Anthropic adapters are available for the next integration stage; cloud experiments are not enabled.</p></div><span className="readonly-badge">Cloud inference is not enabled</span></section></>;
}
