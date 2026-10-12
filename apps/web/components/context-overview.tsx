'use client';
import { useState } from 'react';
import { api } from '@/lib/api';

type Context = { usage: string; sources: { id: string; name: string; status: string; fetched_at: string | null; next_refresh_at: string | null;
  items: { id: string; title: string; summary: string; url: string; date: string; kind: string; provider: string; symbols: string[] }[] }[] };

export function ContextOverview() {
  const [snapshot, setSnapshot] = useState<Context | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function load() {
    setBusy(true); setError('');
    try { setSnapshot(await api<Context>('/context/overview')); }
    catch { setError('News and events could not load. Previously loaded items may be stale.'); }
    finally { setBusy(false); }
  }
  const status = (value: string) => ({ ok: 'Connected', stale: 'Stale', key_missing: 'Connection required', offline: 'Feed disabled',
    budget_exhausted: 'Request budget reached', rate_limited: 'Provider cooldown', authentication_failed: 'Check provider access' })[value] ?? 'Unavailable';
  return <section className="card context-section" data-testid="private-context"><div className="market-heading"><div><p className="eyebrow">PRIVATE RESEARCH CONTEXT</p><h2>News & upcoming events.</h2><p>Read on demand. Baseline replay decisions do not use these feeds.</p></div>
    <button className="button secondary" disabled={busy} onClick={() => void load()}>{busy ? 'Loading…' : snapshot ? 'Check context' : 'Load private context'}</button></div>
    {error && <p role="alert">{error}</p>}
    {snapshot && <div className="context-sources">{snapshot.sources.map(source => <section key={source.id}><div className="context-source-heading"><h3>{source.name}</h3><span>{status(source.status)}</span></div>
      {source.fetched_at && <p className="context-retrieved">Retrieved {new Date(source.fetched_at).toLocaleString('en-CA')} · {source.items.length} items</p>}
      {source.items.length ? <ul>{source.items.map(item => <li key={item.id}><span>{item.date} · {item.kind.replaceAll('_', ' ')}</span><a href={item.url} target="_blank" rel="noopener noreferrer">{item.title}</a><p>{item.summary}</p>{item.symbols.length > 0 && <small>{item.symbols.join(' · ')}</small>}</li>)}</ul> : <p className="context-empty">{source.status === 'ok' ? 'No matching items in this window.' : 'No data available from this source.'}</p>}
    </section>)}</div>}
  </section>;
}
