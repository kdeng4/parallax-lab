'use client';

import { useEffect, useState } from 'react';
import { ArrowDownUp, Check, ChevronDown, ChevronLeft, ChevronRight, CircleDot, Filter, LoaderCircle, Search, ShieldCheck } from 'lucide-react';
import { api, date, time } from '@/lib/api';
import type { AuditEvent, Detail } from '@/lib/types';

const icons: Record<string, typeof CircleDot> = { fill: ArrowDownUp, completed: Check, risk: ShieldCheck };

export function AuditTimeline({ experiment, compact = false, onViewAll }: { experiment: Detail; compact?: boolean; onViewAll?: () => void }) {
  const [type, setType] = useState('');
  const [runId, setRunId] = useState('');
  const [fromTime, setFromTime] = useState('');
  const [toTime, setToTime] = useState('');
  const [offset, setOffset] = useState(0);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const limit = compact ? 5 : 20;
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (type) query.set('type', type);
    if (runId) query.set('run_id', runId);
    if (fromTime) query.set('from_time', `${fromTime}:00Z`);
    if (toTime) query.set('to_time', `${toTime}:00Z`);
    setLoading(true); setError('');
    api<{ events: AuditEvent[]; total: number }>(`/experiments/${experiment.id}/events?${query}`).then((result) => { if (!cancelled) { setEvents(result.events); setTotal(result.total); } }).catch((reason) => { if (!cancelled) setError(reason.message); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [experiment.id, type, runId, fromTime, toTime, offset, limit, retry]);

  return <section className="card audit-card" aria-labelledby={compact ? 'recent-activity-title' : 'audit-title'}>
    <div className="card-heading"><div><div className="eyebrow">TRACEABLE BY DESIGN</div><h2 id={compact ? 'recent-activity-title' : 'audit-title'}>{compact ? 'Inside the experiment' : 'Decision timeline'}</h2></div>{compact ? <button className="text-button" onClick={onViewAll}>View full audit<ChevronRight size={15} /></button> : <span className="count-badge">{total.toLocaleString()} events</span>}</div>
    <div className="audit-filters"><Filter size={15} aria-hidden="true" /><label className="sr-only" htmlFor={`event-filter-${compact}`}>Event type</label><select id={`event-filter-${compact}`} value={type} onChange={(event) => { setType(event.target.value); setOffset(0); }}><option value="">All event types</option>{['market', 'decision', 'order', 'fill', 'risk', 'completed'].map((value) => <option key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</option>)}</select><label className="sr-only" htmlFor={`participant-filter-${compact}`}>Participant</label><select id={`participant-filter-${compact}`} value={runId} onChange={(event) => { setRunId(event.target.value); setOffset(0); }}><option value="">All participants</option>{experiment.runs.map((run) => <option key={run.id} value={run.id}>{experiment.comparison === 'models' ? run.model_name : run.strategy_name}</option>)}</select>{!compact && <><label className="date-filter">From (UTC)<input aria-label="Events from UTC" type="datetime-local" value={fromTime} onChange={(event) => { setFromTime(event.target.value); setOffset(0); }} /></label><label className="date-filter">To (UTC)<input aria-label="Events to UTC" type="datetime-local" value={toTime} onChange={(event) => { setToTime(event.target.value); setOffset(0); }} /></label></>}</div>
    {error ? <div className="inline-error" role="alert">{error}<button className="text-button" onClick={() => setRetry((value) => value + 1)}>Retry</button></div> : loading ? <div className="timeline-loading" role="status"><LoaderCircle size={18} className="spin" />Loading audit trail…</div> : events.length === 0 ? <div className="empty-state small"><Search size={24} /><h3>No matching events</h3><p>Try a different event type, participant, or time range.</p></div> : <div data-testid="audit-events" className="event-list">{events.map((event) => { const Icon = icons[event.type] ?? CircleDot; return <details className={`event-item event-${event.type}`} key={event.id}><summary><span className="event-time">{time(event.timestamp)}<small>UTC</small></span><span className="event-icon"><Icon size={15} /></span><span className="event-description"><span className="event-title">{event.model_name ?? 'Market feed'}<span className="event-type">{event.type}</span></span><span className="event-message">{event.message}</span></span><span className="event-sequence">#{event.sequence}</span><ChevronDown size={15} className="event-chevron" /></summary><div className="event-details"><div className="event-detail-meta"><span>{date(event.timestamp)} · {time(event.timestamp)} UTC</span><span>{event.strategy_name ?? 'Shared market input'}</span></div><pre>{JSON.stringify(event.details, null, 2)}</pre></div></details>; })}</div>}
    {!compact && <div className="pagination"><span>{total ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total.toLocaleString()}` : '0 events'}</span><div><button className="button secondary small" onClick={() => setOffset((value) => Math.max(0, value - limit))} disabled={offset === 0 || loading}><ChevronLeft size={15} />Previous</button><button className="button secondary small" onClick={() => setOffset((value) => value + limit)} disabled={offset + limit >= total || loading}>Next<ChevronRight size={15} /></button></div></div>}
    {compact && <div className="audit-footnote"><span className="status-dot" />Decisions, orders, and fills are recorded with their inputs and account state.</div>}
  </section>;
}
