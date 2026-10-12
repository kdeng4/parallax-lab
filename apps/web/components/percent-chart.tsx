'use client';

import { useId, useMemo, useState } from 'react';
import { percent } from '@/lib/api';

export type PercentSeries = { id: string; name: string; benchmark: boolean; points: { date: string; value: number }[] };
const COLORS = ['#087f70', '#bc7839', '#7773a6', '#3281a5', '#ad626b', '#657a3c', '#8b70b6', '#7588c6', '#d0a163'];
const when = (value: string) => new Date(value).toLocaleString('en-CA', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC', hour12: false });

export function PercentChart({ series: source }: { series: PercentSeries[] }) {
  const id = useId();
  const series = useMemo(() => source.map(item => ({ ...item, points: item.points.length > 1000
    ? Array.from({ length: 1000 }, (_, index) => item.points[Math.round(index * (item.points.length - 1) / 999)]) : item.points })), [source]);
  const [hidden, setHidden] = useState<string[]>([]);
  const [hover, setHover] = useState<number | null>(null);
  const visible = series.filter(item => !hidden.includes(item.id));
  let low = 0, high = 0;
  for (const item of visible) for (const point of item.points) { low = Math.min(low, point.value); high = Math.max(high, point.value); }
  const padding = Math.max((high - low) * .15, .25);
  const minimum = low - padding, maximum = high + padding;
  const width = 960, height = 320, left = 70, right = 20, top = 20, bottom = 40;
  const reference = series[0]?.points ?? [];
  const count = Math.max(reference.length - 1, 0);
  const firstTime = Date.parse(reference[0]?.date ?? '1970-01-01');
  const span = Math.max(1, Date.parse(reference[count]?.date ?? '1970-01-01') - firstTime);
  const x = (date: string) => left + (Date.parse(date) - firstTime) / span * (width - left - right);
  const y = (value: number) => top + (maximum - value) / (maximum - minimum) * (height - top - bottom);
  const color = (item: PercentSeries, i: number) => item.benchmark ? '#34423d' : COLORS[i % COLORS.length];
  const paths = useMemo(() => series.map(item => item.points.map((point, j) => `${j ? 'L' : 'M'}${x(point.date).toFixed(2)},${y(point.value).toFixed(2)}`).join(' ')),
    [series, firstTime, span, maximum, minimum]);
  const active = Math.min(hover ?? count, count);
  return <div className="percent-chart" data-testid="percent-chart">
    <div className="chart-legend">{series.map((item, i) => <button key={item.id} aria-pressed={!hidden.includes(item.id)} className={hidden.includes(item.id) ? 'muted' : ''}
      onClick={() => setHidden(current => current.includes(item.id) ? current.filter(value => value !== item.id) : current.length < series.length - 1 ? [...current, item.id] : current)}>
      <i style={{ background: color(item, i) }} />{item.name}
    </button>)}</div>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Percentage return since start for each model and strategy pair, compared with SPY" className="equity-svg">
      {[0, 1, 2, 3, 4].map(i => { const value = minimum + (maximum - minimum) * i / 4; return <g key={i}>
        <line x1={left} x2={width - right} y1={y(value)} y2={y(value)} stroke="#e6ebe5" strokeDasharray="3 5" />
        <text x={left - 10} y={y(value) + 4} textAnchor="end" className="axis-label">{percent(value)}</text></g>; })}
      <line x1={left} x2={width - right} y1={y(0)} y2={y(0)} stroke="#a8b5ac" strokeDasharray="5 5" />
      {series.map((item, i) => !hidden.includes(item.id) && <g key={item.id}>
        <path d={paths[i]}
          fill="none" stroke={color(item, i)} strokeWidth="2.5" strokeDasharray={item.benchmark ? '7 5' : undefined} strokeLinejoin="round" />
        {item.points.length > 0 && <circle cx={x(item.points.at(-1)!.date)} cy={y(item.points.at(-1)!.value)} r="3" fill={color(item, i)} />}
      </g>)}
      {[0, .5, 1].map(part => { const index = Math.round(count * part); return <text key={part} x={left + part * (width - left - right)} y={height - 10} textAnchor={part === 0 ? 'start' : part === 1 ? 'end' : 'middle'} className="axis-label">{reference[index] ? when(reference[index].date) : ''}</text>; })}
      {hover !== null && reference[active] && <line x1={x(reference[active].date)} x2={x(reference[active].date)} y1={top} y2={height - bottom} stroke="#849b8d" />}
      <rect x={left} y={top} width={width - left - right} height={height - top - bottom} fill="transparent" onPointerMove={event => {
        const box = event.currentTarget.ownerSVGElement!.getBoundingClientRect();
        const stamp = firstTime + Math.max(0, Math.min(1, ((event.clientX - box.left) / box.width * width - left) / (width - left - right))) * span;
        const nearest = reference.reduce((best, point, i) => Math.abs(Date.parse(point.date) - stamp) < Math.abs(Date.parse(reference[best].date) - stamp) ? i : best, 0);
        setHover(nearest);
      }} onPointerLeave={() => setHover(null)} />
    </svg>
    <label className="sr-only" htmlFor={id}>Inspect performance time</label><input id={id} className="chart-accessible-slider" type="range" min={0} max={count} value={active} onChange={event => setHover(Number(event.target.value))}
      aria-valuetext={`${reference[active] ? when(reference[active].date) : ''} UTC. ${visible.map(item => `${item.name}: ${percent(item.points[active]?.value ?? 0)}`).join(', ')}`} />
    <div className="percent-readout" aria-live="polite"><span>{reference[active] ? when(reference[active].date) : ''} UTC</span>
      {visible.map(item => <span key={item.id}>{item.name} <strong>{percent(item.points[active]?.value ?? 0)}</strong></span>)}</div>
  </div>;
}
