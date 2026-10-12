'use client';

import { useState } from 'react';
import { LoaderCircle } from 'lucide-react';
import { api } from '@/lib/api';

export function WatchlistEditor({ symbols, canEdit, onSaved }: { symbols: string[]; canEdit: boolean; onSaved: (symbols: string[]) => void }) {
  const [draft, setDraft] = useState(() => symbols.join(', '));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  async function save(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError(''); setMessage('');
    try {
      const result = await api<{ symbols: string[] }>('/market/watchlist', { method: 'POST', body: JSON.stringify({ symbols: draft.split(',').map(value => value.trim()).filter(Boolean) }) });
      setDraft(result.symbols.join(', ')); onSaved(result.symbols);
      setMessage('Saved. Use Check data to fetch your updated list.');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to save your watchlist.'); }
    finally { setBusy(false); }
  }

  return <section className="card watchlist-editor" aria-labelledby="watchlist-title">
    <h2 id="watchlist-title">Your followed tickers</h2>
    <p>Add stock or ETF tickers beyond the initial list. Follow up to 10; availability depends on the data provider. Adding a ticker makes no market-data request.</p>
    <form onSubmit={save}>
      <label htmlFor="watchlist-symbols">Tickers, separated by commas</label>
      <div className="watchlist-controls"><input id="watchlist-symbols" value={draft} onChange={event => setDraft(event.target.value)} placeholder="e.g. TSLA, AMD, BRK.B" maxLength={169} required disabled={busy || !canEdit} /><button className="button secondary" type="submit" disabled={busy || !canEdit}>{busy && <LoaderCircle size={15} className="spin" />}Save tickers</button></div>
    </form>
    {message && <p role="status">{message}</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </section>;
}
