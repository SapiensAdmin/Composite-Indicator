'use client';

import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceLine, Legend,
} from 'recharts';
import { fmt, monthLabel } from '@/lib/composite';

// Per-series colours: small cap warm, mid cap cool (matches the category-trend chart).
// Any future series cycles through the fallback palette.
const SERIES_COLOR = { smallcap: 'var(--smallcap)', midcap: 'var(--midcap)' };
const FALLBACK = ['#a78bfa', '#f472b6', '#84cc16', '#22d3ee'];

function colorFor(series, i) {
  const id = series.series_id.toLowerCase();
  if (id.includes('smallcap')) return SERIES_COLOR.smallcap;
  if (id.includes('midcap')) return SERIES_COLOR.midcap;
  return FALLBACK[i % FALLBACK.length];
}

function level(v) {
  if (v == null) return 'mid';
  return v > 0.5 ? 'hi' : v < -0.5 ? 'lo' : 'mid';
}
const LEVEL_TEXT = { hi: 'Elevated', lo: 'Subdued', mid: 'Around avg' };

function shortLabel(series) {
  const id = series.series_id.toLowerCase();
  if (id.includes('smallcap')) return 'Small Cap';
  if (id.includes('midcap')) return 'Mid Cap';
  return series.label;
}

// latest non-null [value, index]
function latestOf(arr) {
  for (let i = arr.length - 1; i >= 0; i--) {
    if (arr[i] != null) return [arr[i], i];
  }
  return null;
}

export default function CompositeChart({ composite }) {
  const { dates, series, composite: combined } = composite;

  const data = dates.map((d, i) => {
    const row = { d, label: monthLabel(d), composite: combined[i] };
    series.forEach((s) => { row[s.series_id] = s.values[i]; });
    return row;
  });

  const combinedLatest = latestOf(combined) || [];

  return (
    <div className="card">
      <h2>Liquidity-stress score — small cap vs mid cap</h2>
      <p className="card-sub">
        Each line is that category’s top-10 avg days-to-liquidate-50%, z-scored over expanding
        history (0 ≈ its own average; higher ⇒ more stress). The dashed line is the registry-weighted blend.
      </p>

      <div className="stat-row">
        {series.map((s, i) => {
          const li = latestOf(s.values);
          const v = li ? li[0] : null;
          const lv = level(v);
          return (
            <div className="stat" key={s.series_id}>
              <span className="stat-label" style={{ color: colorFor(s, i) }}>{shortLabel(s)}</span>
              <span className={`stat-value ${lv}`}>{fmt(v)}</span>
              <span className={`pill ${lv}`}>{LEVEL_TEXT[lv]}</span>
            </div>
          );
        })}
        <div className="stat">
          <span className="stat-label" style={{ color: 'var(--accent)' }}>Combined</span>
          <span className={`stat-value ${level(combinedLatest[0])}`}>{fmt(combinedLatest[0])}</span>
          <span className="stat-meta">as of {monthLabel(dates[combinedLatest[1]])}</span>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: 'var(--faint)', fontSize: 11 }}
                 interval="preserveStartEnd" minTickGap={28} />
          <YAxis tick={{ fill: 'var(--faint)', fontSize: 11 }} width={44} />
          <ReferenceLine y={0} stroke="var(--faint)" strokeDasharray="3 3" />
          <Tooltip
            contentStyle={{ background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)' }}
            labelStyle={{ color: 'var(--muted)' }}
            formatter={(v, key) => {
              if (key === 'composite') return [fmt(v), 'Combined'];
              const s = series.find((x) => x.series_id === key);
              return [fmt(v), s ? shortLabel(s) : key];
            }} />
          <Legend wrapperStyle={{ fontSize: 12, color: 'var(--muted)', paddingTop: 6 }} iconType="plainline" />
          {series.map((s, i) => (
            <Line key={s.series_id} type="monotone" dataKey={s.series_id} name={shortLabel(s)}
                  stroke={colorFor(s, i)} strokeWidth={2.4} dot={false} connectNulls />
          ))}
          <Line type="monotone" dataKey="composite" name="Combined"
                stroke="var(--accent)" strokeWidth={1.6} strokeDasharray="5 3"
                dot={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
