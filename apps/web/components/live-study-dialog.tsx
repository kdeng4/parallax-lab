'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowRight, LoaderCircle, X } from 'lucide-react';
import { api } from '@/lib/api';
import type { Catalog, LiveStudy } from '@/lib/types';

export function LiveStudyDialog({ catalog, onClose, onCreated }: { catalog: Catalog; onClose: () => void; onCreated: (study: LiveStudy) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cloud = catalog.models.filter(model => model.provider === 'OpenAI');
  const [models, setModels] = useState((cloud.length ? cloud : catalog.models).slice(0, 3).map(model => model.id));
  const [strategies, setStrategies] = useState(['balanced']);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { dialog.current?.showModal(); }, []);
  const toggle = (id: string, values: string[], set: (next: string[]) => void) => set(values.includes(id) ? values.filter(value => value !== id) : [...values, id]);

  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!models.length || !strategies.length) { setError('Select at least one model and one strategy.'); return; }
    const data = new FormData(event.currentTarget);
    const symbols = String(data.get('symbols')).split(',').map(value => value.trim()).filter(Boolean);
    if (!symbols.length || symbols.length > 10) { setError('Choose 1 to 10 stock or ETF tickers.'); return; }
    setBusy(true); setError('');
    try {
      onCreated(await api<LiveStudy>('/studies', { method: 'POST', body: JSON.stringify({
        name: String(data.get('name')).trim(), model_ids: models, strategy_ids: strategies, symbols,
        initial_cash: Number(data.get('initial_cash')), timezone: String(data.get('timezone')).trim(),
        window_start: String(data.get('window_start')), window_end: String(data.get('window_end')),
      }) }));
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start this study.'); setBusy(false); }
  }

  return <dialog ref={dialog} className="experiment-dialog" aria-labelledby="live-dialog-title" onCancel={event => { if (busy) event.preventDefault(); else onClose(); }}
    onClick={event => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <form onSubmit={submit}><div className="dialog-heading"><span className="eyebrow">START NOW. OBSERVE WHAT FOLLOWS.</span>
      <button type="button" className="icon-button" aria-label="Close ongoing study" onClick={onClose} disabled={busy}><X size={20} /></button></div>
      <h2 id="live-dialog-title">New ongoing study</h2><p className="dialog-description">Each model / strategy pair starts with the same capital. Agents select among your tickers and cash, using a shared daily news and price snapshot.</p>
      <fieldset disabled={busy} className="live-fields"><label>Study name<input name="name" maxLength={100} placeholder="e.g. Daily research cohort" required autoFocus /></label>
        <label>Study tickers, separated by commas<input name="symbols" defaultValue={catalog.symbols.join(', ')} maxLength={169} required /></label>
        <div className="form-grid"><label>Initial capital per pair (USD)<input name="initial_cash" type="number" min={100} max={100000000} step="0.01" defaultValue={100000} required /></label>
          <label>Window time zone<input name="timezone" defaultValue="America/Toronto" list="study-zones" required /><datalist id="study-zones"><option>America/Toronto</option><option>America/New_York</option><option>America/Los_Angeles</option><option>Europe/London</option><option>UTC</option></datalist></label>
          <label>Daily window starts<input name="window_start" type="time" defaultValue="09:45" required /></label><label>Daily window ends<input name="window_end" type="time" defaultValue="10:45" required /></label></div>
      </fieldset>
      <fieldset className="selection-fieldset" disabled={busy}><legend>Models · select up to 3</legend><div className="selection-options">{catalog.models.map(model => <label key={model.id} className={models.includes(model.id) ? 'selected' : ''}>
        <input type="checkbox" aria-label={model.name} checked={models.includes(model.id)} disabled={models.length >= 3 && !models.includes(model.id)} onChange={() => toggle(model.id, models, setModels)} /><span>{model.name}<small>{model.provider}</small></span></label>)}</div></fieldset>
      <fieldset className="selection-fieldset" disabled={busy}><legend>Strategies · every selected pair gets its own portfolio</legend><div className="selection-options">{catalog.strategies.map(strategy => <label key={strategy.id} className={strategies.includes(strategy.id) ? 'selected' : ''}>
        <input type="checkbox" aria-label={strategy.name} checked={strategies.includes(strategy.id)} onChange={() => toggle(strategy.id, strategies, setStrategies)} /><span>{strategy.name}</span></label>)}</div></fieldset>
      <p className="form-notice">{models.length * strategies.length} independent portfolios. One decision per weekday window, with execution timing chosen by the agent and fresh quotes checked every 5 minutes. The window must be 30–180 minutes and overlap US regular market hours. Start during market hours; no past trades are created.</p>
      <p className="muted">All accounts aim to grow equity within fixed risk limits. Settings are locked after start. Equity includes holdings and dividends; exhausted accounts pause. OpenAI: at most {catalog.openai?.max_calls_per_day ?? 24} calls per rolling day, shared with replays. Missing data or limits can skip a window.</p>
      {!catalog.live?.available && <p className="form-error">{catalog.live?.requirement ?? 'Connect verified live data before starting.'}</p>}
      {error && <p role="alert" className="form-error">{error}</p>}
      <div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose} disabled={busy}>Cancel</button><button type="submit" className="button primary" disabled={busy || !catalog.live?.available}>
        {busy ? <><LoaderCircle size={16} className="spin" />Starting…</> : <>Start ongoing study<ArrowRight size={16} /></>}</button></div>
    </form>
  </dialog>;
}
