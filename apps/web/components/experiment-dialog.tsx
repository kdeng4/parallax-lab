'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowRight, FlaskConical, LoaderCircle, ShieldCheck, X } from 'lucide-react';
import { api } from '@/lib/api';
import type { Catalog, Comparison, CreateExperiment, Detail } from '@/lib/types';

export function ExperimentDialog({ catalog, initialComparison, onClose, onCreated }: { catalog: Catalog; initialComparison: Comparison; onClose: () => void; onCreated: (detail: Detail) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [comparison, setComparison] = useState<Comparison>(initialComparison);
  const [modelIds, setModelIds] = useState(initialComparison === 'models' ? catalog.models.map((model) => model.id) : [catalog.models[0]?.id].filter(Boolean));
  const [strategyIds, setStrategyIds] = useState(initialComparison === 'strategies' ? catalog.strategies.map((strategy) => strategy.id) : [catalog.strategies[0]?.id].filter(Boolean));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { dialog.current?.showModal(); }, []);

  function changeComparison(value: Comparison) {
    setComparison(value);
    setModelIds(value === 'models' ? catalog.models.map((model) => model.id) : [catalog.models[0].id]);
    setStrategyIds(value === 'strategies' ? catalog.strategies.map((strategy) => strategy.id) : [catalog.strategies[0].id]);
  }
  function toggle(id: string, current: string[], set: (ids: string[]) => void, multiple: boolean) { set(multiple ? current.includes(id) ? current.filter((value) => value !== id) : [...current, id] : [id]); }
  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if ((comparison === 'models' ? modelIds : strategyIds).length < 2) { setError(`Select at least two ${comparison} to compare.`); return; }
    const data = new FormData(event.currentTarget);
    const name = String(data.get('name') ?? '').trim();
    const payload: CreateExperiment = { ...(name ? { name } : {}), comparison, model_ids: modelIds, strategy_ids: strategyIds, symbol: String(data.get('symbol')), seed: Number(data.get('seed')), initial_cash: Number(data.get('initial_cash')), bars: Number(data.get('bars')) };
    setBusy(true); setError('');
    try { onCreated(await api<Detail>('/experiments', { method: 'POST', body: JSON.stringify(payload) })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to run this experiment. Try again.'); setBusy(false); }
  }

  return <dialog ref={dialog} className="experiment-dialog" aria-labelledby="dialog-title" onCancel={(event) => { if (busy) event.preventDefault(); else onClose(); }} onClick={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <form onSubmit={submit}>
      <div className="dialog-heading"><div className="dialog-icon"><FlaskConical size={22} /></div><button type="button" className="icon-button" aria-label="Close new experiment" onClick={onClose} disabled={busy}><X size={20} /></button></div>
      <div className="eyebrow">A FAIR START. A CLEAR RESULT.</div><h2 id="dialog-title">New experiment</h2><p className="dialog-description">One variable changes. Every participant gets the same market, capital, and execution rules.</p>
      <label className="field-label" htmlFor="experiment-name">Experiment name <span>Optional</span></label><input id="experiment-name" name="name" placeholder="e.g. Morning momentum study" maxLength={100} autoFocus disabled={busy} />
      <fieldset className="comparison-fieldset" disabled={busy}><legend>What are you comparing?</legend><div className="comparison-options"><label className={comparison === 'models' ? 'selected' : ''}><input type="radio" name="comparison" checked={comparison === 'models'} onChange={() => changeComparison('models')} /><span><strong>Models</strong><small>Same strategy, different models</small></span></label><label className={comparison === 'strategies' ? 'selected' : ''}><input type="radio" name="comparison" checked={comparison === 'strategies'} onChange={() => changeComparison('strategies')} /><span><strong>Strategies</strong><small>Same model, different strategies</small></span></label></div></fieldset>
      <fieldset className="selection-fieldset" disabled={busy}><legend>{comparison === 'models' ? 'Models to compare' : 'Shared model'}</legend><div className="selection-options">{catalog.models.map((model) => <label key={model.id} className={modelIds.includes(model.id) ? 'selected' : ''}><input type={comparison === 'models' ? 'checkbox' : 'radio'} name="models" checked={modelIds.includes(model.id)} onChange={() => toggle(model.id, modelIds, setModelIds, comparison === 'models')} /><span>{model.name}</span></label>)}</div></fieldset>
      <fieldset className="selection-fieldset" disabled={busy}><legend>{comparison === 'strategies' ? 'Strategies to compare' : 'Shared strategy'}</legend><div className="selection-options">{catalog.strategies.map((strategy) => <label key={strategy.id} className={strategyIds.includes(strategy.id) ? 'selected' : ''}><input type={comparison === 'strategies' ? 'checkbox' : 'radio'} name="strategies" checked={strategyIds.includes(strategy.id)} onChange={() => toggle(strategy.id, strategyIds, setStrategyIds, comparison === 'strategies')} /><span>{strategy.name}</span></label>)}</div></fieldset>
      <div className="form-grid"><label>Market<select name="symbol" defaultValue="SPY" disabled={busy}>{catalog.symbols.map((symbol) => <option key={symbol}>{symbol}</option>)}</select></label><label>Starting capital (USD)<input name="initial_cash" type="number" defaultValue={100000} min={100} max={100000000} step={100} required disabled={busy} /></label><label>Replay bars<input name="bars" type="number" defaultValue={180} min={60} max={1440} step={1} required disabled={busy} /></label><label>Dataset seed<input name="seed" type="number" defaultValue={42} min={0} max={4294967295} step={1} required disabled={busy} /></label></div>
      <div className="form-notice"><ShieldCheck size={17} /><span>Paper accounts · synthetic 1-minute candles · local baseline models. No real orders or external AI calls.</span></div>
      {error && <p role="alert" className="form-error">{error}</p>}
      <div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose} disabled={busy}>Cancel</button><button type="submit" className="button primary" disabled={busy}>{busy ? <><LoaderCircle size={16} className="spin" />Running replay…</> : <>Run experiment<ArrowRight size={16} /></>}</button></div>
    </form>
  </dialog>;
}
