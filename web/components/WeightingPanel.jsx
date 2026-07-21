'use client';

import { useMemo, useState } from 'react';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceLine,
} from 'recharts';
import { recomputeComposite, fmt, monthLabel } from '@/lib/composite';

export default function WeightingPanel({ composite }) {
  const { dates, series } = composite;

  const defaults = useMemo(
    () => Object.fromEntries(series.map((s) => [s.series_id, s.default_weight])),
    [series]
  );
  const [weights, setWeights] = useState(defaults);

  const live = useMemo(() => recomputeComposite(series, weights), [series, weights]);
  const data = dates.map((d, i) => ({ date: d, label: monthLabel(d), v: live[i] }));
  const latest = [...data].reverse().find((r) => r.v !== null) || {};

  const total = Object.values(weights).reduce((a, b) => a + Math.max(0, b), 0) || 1;

  return (
    <div className="card">
      <h2>Experiment with weights (live)</h2>
      <p className="card-sub">Drag to re-weight the composite in your browser. Nothing is saved — persist by editing the registry sheet.</p>

      <div className="kpi">
        <span className="value mid" style={{ fontSize: 32 }}>{fmt(latest.v)}</span>
        <span className="meta">live composite<br />as of {monthLabel(latest.date)}</span>
      </div>

      <ResponsiveContainer width="100%" height={170}>
        <LineChart data={data} margin={{ top: 4, right: 10, bottom: 0, left: -20 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: 'var(--faint)', fontSize: 10 }}
                 interval="preserveStartEnd" minTickGap={30} />
          <YAxis tick={{ fill: 'var(--faint)', fontSize: 10 }} width={40} />
          <ReferenceLine y={0} stroke="var(--faint)" strokeDasharray="3 3" />
          <Tooltip contentStyle={{ background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 8 }}
                   formatter={(v) => [fmt(v), 'Live composite']} />
          <Line type="monotone" dataKey="v" stroke="var(--accent)" strokeWidth={2.2} dot={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>

      {series.map((s) => {
        const w = weights[s.series_id];
        const pct = ((Math.max(0, w) / total) * 100).toFixed(0);
        return (
          <div className="slider-row" key={s.series_id}>
            <div className="top">
              <span>{s.label} <span className="dir">{s.direction > 0 ? '↑=more stress' : '↓=safer'}</span></span>
              <span className="w">{fmt(w, 1)} · {pct}%</span>
            </div>
            <input type="range" min="0" max="5" step="0.1" value={w}
              onChange={(e) => setWeights({ ...weights, [s.series_id]: parseFloat(e.target.value) })} />
          </div>
        );
      })}

      <button className="reset-btn" onClick={() => setWeights(defaults)}>Reset to registry defaults</button>
      <p className="panel-note">
        Effective weight = raw ÷ (sum of raw weights), renormalized per month over series with data — exactly how the ETL computes the persisted score.
      </p>
    </div>
  );
}
