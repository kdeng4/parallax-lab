'use client';

import { useMemo, useState } from 'react';
import { ArrowUpRight, ChartNoAxesCombined } from 'lucide-react';
import { money, percent, time } from '@/lib/api';
import type { Detail } from '@/lib/types';

export const RUN_COLORS = ['#087f70', '#7588c6', '#d0a163', '#ca7892', '#7f9e68', '#8b70b6'];

export function EquityChart({ experiment }: { experiment: Detail }) {
  const [hidden, setHidden] = useState<string[]>([]);
  const [hover, setHover] = useState<number | null>(null);
  const [window, setWindow] = useState(0);
  const runs = experiment.runs;
  const maxPoints = Math.max(...runs.map((run) => run.equity_curve.length), 1);
  const first = window ? Math.max(0, maxPoints - window) : 0;
  const visible = runs.filter((run) => !hidden.includes(run.id));
  const values = visible.flatMap((run) => run.equity_curve.slice(first).map((point) => point.equity));
  const rawMin = Math.min(...values, experiment.initial_cash);
  const rawMax = Math.max(...values, experiment.initial_cash);
  const padding = Math.max((rawMax - rawMin) * 0.15, experiment.initial_cash * 0.001);
  const minimum = rawMin - padding;
  const maximum = rawMax + padding;
  const width = 920;
  const height = 295;
  const left = 10;
  const right = 83;
  const top = 20;
  const bottom = 35;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const length = Math.max(maxPoints - first - 1, 1);
  const x = (index: number) => left + index / length * chartWidth;
  const y = (value: number) => top + (maximum - value) / (maximum - minimum) * chartHeight;
  const labels = [0, 1, 2, 3, 4].map((index) => maximum - (maximum - minimum) * index / 4);
  const reference = runs[0]?.equity_curve ?? [];
  const activeIndex = hover === null ? null : first + Math.min(hover, length);
  const best = useMemo(() => [...runs].sort((a, b) => b.return_pct - a.return_pct)[0], [runs]);
  const label = (model: string, strategy: string) => experiment.comparison === 'models' ? model : strategy;

  if (values.length === 0) return <div className="empty-state"><ChartNoAxesCombined size={28} /><h3>No equity data yet</h3><p>Run an experiment to compare account performance.</p></div>;

  return <section data-testid="equity-chart" className="card equity-card" aria-labelledby="equity-title">
    <div className="card-heading">
      <div><div className="eyebrow">PERFORMANCE OVER TIME</div><h2 id="equity-title">Every decision. One benchmark.</h2></div>
      <div className="segmented range-selector" aria-label="Chart time range">{[{ value: 60, label: 'Last 60' }, { value: 120, label: 'Last 120' }, { value: 0, label: 'All bars' }].map((item) => <button key={item.value} aria-pressed={window === item.value} className={window === item.value ? 'active' : ''} onClick={() => { setWindow(item.value); setHover(null); }}>{item.label}</button>)}</div>
    </div>
    <div className="chart-intro"><span className="chart-value">{money(best?.equity ?? experiment.initial_cash, 2)}</span><span className={`chart-return ${best && best.return_pct < 0 ? 'negative' : ''}`}><ArrowUpRight size={15} />{percent(best?.return_pct ?? 0)}</span><span className="chart-caption">Leading account · net of costs</span></div>
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} className="equity-svg" role="img" aria-label={`Net account equity over ${maxPoints - first} bars. ${runs.map((run) => `${label(run.model_name, run.strategy_name)}: ${money(run.equity, 2)}, return ${percent(run.return_pct)}`).join('. ')}`}>
        <defs><linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#087f70" stopOpacity=".09" /><stop offset="100%" stopColor="#087f70" stopOpacity="0" /></linearGradient></defs>
        {labels.map((value) => <g key={value}><line x1={left} y1={y(value)} x2={width - right} y2={y(value)} stroke="#eceeea" strokeDasharray="3 5" /><text x={width - right + 16} y={y(value) + 4} className="axis-label">{money(value)}</text></g>)}
        <line x1={left} y1={y(experiment.initial_cash)} x2={width - right} y2={y(experiment.initial_cash)} stroke="#c8cdc7" strokeDasharray="5 5" />
        {runs.map((run, index) => {
          if (hidden.includes(run.id)) return null;
          const points = run.equity_curve.slice(first);
          const path = points.map((point, i) => `${i ? 'L' : 'M'}${x(i).toFixed(2)},${y(point.equity).toFixed(2)}`).join(' ');
          return <g key={run.id}>{index === 0 && points.length > 0 && <path d={`${path} L${x(points.length - 1)},${top + chartHeight} L${left},${top + chartHeight} Z`} fill="url(#equity-fill)" />}<path d={path} fill="none" stroke={RUN_COLORS[index % RUN_COLORS.length]} strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" />{points.length > 0 && <circle cx={x(points.length - 1)} cy={y(points[points.length - 1].equity)} r="3.8" fill={RUN_COLORS[index % RUN_COLORS.length]} stroke="white" strokeWidth="2" />}</g>;
        })}
        {[0, .25, .5, .75, 1].map((part) => { const index = Math.round(length * part); const point = reference[first + index]; return <text key={part} x={x(index)} y={height - 8} textAnchor={part === 0 ? 'start' : part === 1 ? 'end' : 'middle'} className="axis-label">{point ? time(point.timestamp) : ''}</text>; })}
        {activeIndex !== null && <g><line x1={x(activeIndex - first)} x2={x(activeIndex - first)} y1={top} y2={top + chartHeight} stroke="#b8beba" />{runs.map((run, index) => !hidden.includes(run.id) && run.equity_curve[activeIndex] ? <circle key={run.id} cx={x(activeIndex - first)} cy={y(run.equity_curve[activeIndex].equity)} r="4" fill={RUN_COLORS[index % RUN_COLORS.length]} stroke="white" strokeWidth="2" /> : null)}</g>}
        <rect x={left} y={top} width={chartWidth} height={chartHeight} fill="transparent" onPointerMove={(event) => { const rect = event.currentTarget.ownerSVGElement!.getBoundingClientRect(); const position = (event.clientX - rect.left) / rect.width * width; setHover(Math.max(0, Math.min(length, Math.round((position - left) / chartWidth * length)))); }} onPointerLeave={() => setHover(null)} />
      </svg>
      {activeIndex !== null && <div className="chart-tooltip" aria-hidden="true" style={{ left: `${Math.min(70, Math.max(2, (activeIndex - first) / length * 80))}%` }}><span className="tooltip-time">{reference[activeIndex] ? time(reference[activeIndex].timestamp) : ''} UTC</span>{runs.map((run, index) => !hidden.includes(run.id) && run.equity_curve[activeIndex] ? <div key={run.id}><span><i style={{ background: RUN_COLORS[index % RUN_COLORS.length] }} />{label(run.model_name, run.strategy_name)}</span><strong>{money(run.equity_curve[activeIndex].equity, 2)}</strong></div> : null)}</div>}
    </div>
    <div className="chart-bottom"><div className="chart-legend">{runs.map((run, index) => <button key={run.id} aria-pressed={!hidden.includes(run.id)} title={`Toggle ${label(run.model_name, run.strategy_name)}`} className={hidden.includes(run.id) ? 'muted' : ''} onClick={() => setHidden((current) => current.includes(run.id) ? current.filter((id) => id !== run.id) : current.length < runs.length - 1 ? [...current, run.id] : current)}><i style={{ background: RUN_COLORS[index % RUN_COLORS.length] }} />{label(run.model_name, run.strategy_name)}</button>)}</div><span className="chart-unit">Account equity · USD · UTC</span></div>
    <label className="sr-only" htmlFor="chart-point">Inspect chart bar</label><input id="chart-point" className="chart-accessible-slider" type="range" min={0} max={length} value={hover ?? length} onChange={(event) => setHover(Number(event.target.value))} onBlur={() => setHover(null)} aria-valuetext={activeIndex !== null ? runs.map((run) => `${label(run.model_name, run.strategy_name)} ${money(run.equity_curve[activeIndex]?.equity ?? 0, 2)}`).join(', ') : 'Use arrow keys to inspect account equity at each bar'} />
  </section>;
}
