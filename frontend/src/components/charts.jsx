// Dependency-free SVG charts.
import { useState } from 'react';
import { inrShort } from '../lib/format.js';

const niceMax = (v) => {
  if (v <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * pow).find((m) => m >= v);
};

/** Grouped bar chart. series = [{ key, label, color }] */
export function BarChart({ data, series, xKey, height = 240, format = inrShort }) {
  const [hover, setHover] = useState(null);
  const W = 640, H = height, pad = { l: 56, r: 12, t: 12, b: 28 };
  const max = niceMax(Math.max(1, ...data.flatMap((d) => series.map((s) => d[s.key] || 0))));
  const innerW = W - pad.l - pad.r, innerH = H - pad.t - pad.b;
  const band = innerW / Math.max(1, data.length);
  const barW = Math.min(26, (band * 0.7) / series.length);
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Bar chart">
        {ticks.map((t) => {
          const y = pad.t + innerH * (1 - t);
          return (
            <g key={t}>
              <line x1={pad.l} x2={W - pad.r} y1={y} y2={y} stroke="#e2e8f0" strokeDasharray={t ? '3 4' : ''} />
              <text x={pad.l - 8} y={y + 4} textAnchor="end" fontSize="11" fill="#94a3b8">{format(max * t)}</text>
            </g>
          );
        })}
        {data.map((d, i) => {
          const x0 = pad.l + band * i + (band - barW * series.length - 4 * (series.length - 1)) / 2;
          return (
            <g key={d[xKey]} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={pad.l + band * i} y={pad.t} width={band} height={innerH} fill={hover === i ? '#f1f5f9' : 'transparent'} />
              {series.map((s, j) => {
                const h = ((d[s.key] || 0) / max) * innerH;
                return <rect key={s.key} x={x0 + j * (barW + 4)} y={pad.t + innerH - h} width={barW} height={Math.max(h, 0)} rx="4" fill={s.color} />;
              })}
              <text x={pad.l + band * i + band / 2} y={H - 8} textAnchor="middle" fontSize="11" fill="#64748b">{d[xKey]}</text>
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600">
        {series.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
            {s.label}
            {hover !== null && <b className="num text-slate-900">{format(data[hover][s.key] || 0)}</b>}
          </span>
        ))}
        {hover !== null && <span className="text-slate-400">· {data[hover][xKey]}</span>}
      </div>
    </div>
  );
}

/** Horizontal bars - funnels, rankings. items = [{ label, value, sub }] */
export function HBars({ items, color = '#6366f1', format = inrShort }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <ul className="space-y-3">
      {items.map((item) => (
        <li key={item.label}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
            <span className="truncate text-slate-700">{item.label}</span>
            <span className="num shrink-0 font-semibold text-slate-900">
              {format(item.value)}{item.sub && <span className="ml-1.5 text-xs font-normal text-slate-400">{item.sub}</span>}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full transition-all duration-500" style={{ width: `${Math.max(2, (item.value / max) * 100)}%`, background: item.color || color }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Donut. slices = [{ label, value, color }] */
export function Donut({ slices, size = 150, centerLabel, centerValue }) {
  const total = slices.reduce((a, s) => a + s.value, 0);
  const r = 54, c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div className="flex items-center gap-5">
      <svg width={size} height={size} viewBox="0 0 140 140" role="img" aria-label={centerLabel || 'Donut chart'}>
        <circle cx="70" cy="70" r={r} fill="none" stroke="#f1f5f9" strokeWidth="16" />
        {total > 0 && slices.map((s) => {
          const len = (s.value / total) * c;
          const el = <circle key={s.label} cx="70" cy="70" r={r} fill="none" stroke={s.color} strokeWidth="16" strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset} transform="rotate(-90 70 70)" />;
          offset += len;
          return el;
        })}
        <text x="70" y="66" textAnchor="middle" fontSize="20" fontWeight="700" fill="#0f172a">{centerValue}</text>
        <text x="70" y="84" textAnchor="middle" fontSize="10" fill="#94a3b8">{centerLabel}</text>
      </svg>
      <ul className="space-y-1.5 text-sm">
        {slices.map((s) => (
          <li key={s.label} className="flex items-center gap-2 text-slate-600">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: s.color }} />
            {s.label} <b className="num text-slate-900">{s.value}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Semi-circular risk gauge, 0-100 with policy thresholds. */
export function RiskGauge({ score = 0, level = 'low', manager = 25, finance = 55 }) {
  const colors = { low: '#10b981', medium: '#f59e0b', high: '#f43f5e' };
  const r = 70, cx = 90, cy = 88, len = Math.PI * r;
  const point = (v) => {
    const a = Math.PI * (1 - v / 100);
    return [cx + r * Math.cos(a), cy - r * Math.sin(a)];
  };
  const tick = (v) => {
    const a = Math.PI * (1 - v / 100);
    return { x1: cx + (r - 11) * Math.cos(a), y1: cy - (r - 11) * Math.sin(a), x2: cx + (r + 11) * Math.cos(a), y2: cy - (r + 11) * Math.sin(a) };
  };
  const [sx, sy] = point(0), [ex, ey] = point(100);
  const arc = `M ${sx} ${sy} A ${r} ${r} 0 0 1 ${ex} ${ey}`;
  return (
    <svg viewBox="0 0 180 104" className="mx-auto w-full max-w-[220px]" role="img" aria-label={`Risk score ${Math.round(score)} of 100, ${level}`}>
      <path d={arc} fill="none" stroke="#e2e8f0" strokeWidth="14" strokeLinecap="round" />
      <path d={arc} fill="none" stroke={colors[level]} strokeWidth="14" strokeLinecap="round" strokeDasharray={`${(Math.min(100, score) / 100) * len} ${len}`} style={{ transition: 'stroke-dasharray .4s ease' }} />
      {[manager, finance].map((v) => <line key={v} {...tick(v)} stroke="#475569" strokeWidth="1.5" />)}
      <text x={cx} y={cy - 12} textAnchor="middle" fontSize="30" fontWeight="800" fill="#0f172a">{Math.round(score)}</text>
      <text x={cx} y={cy + 6} textAnchor="middle" fontSize="10" fill="#64748b" style={{ textTransform: 'uppercase', letterSpacing: 1 }}>{level} risk</text>
    </svg>
  );
}
