'use client';

import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceLine,
} from 'recharts';
import { fmt, monthLabel } from '@/lib/composite';

export default function CompositeChart({ dates, composite }) {
  const data = dates.map((d, i) => ({ d, label: monthLabel(d), v: composite[i] }));
  const latest = [...data].reverse().find((r) => r.v !== null) || {};

  const level = latest.v == null ? 'mid' : latest.v > 0.5 ? 'hi' : latest.v < -0.5 ? 'lo' : 'mid';
  const levelText = level === 'hi' ? 'Elevated stress' : level === 'lo' ? 'Subdued stress' : 'Around average';

  return (
    <div className="card">
      <h2>Composite liquidity-stress score</h2>
      <p className="card-sub">Registry-weighted, z-scored over expanding history. 0 ≈ historical average; higher ⇒ more stress.</p>

      <div className="kpi">
        <span className={`value ${level}`}>{fmt(latest.v)}</span>
        <span className="meta">
          as of {monthLabel(latest.d)}<br />
          <span className={`pill ${level}`}>{levelText}</span>
        </span>
      </div>

      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: 'var(--faint)', fontSize: 11 }}
                 interval="preserveStartEnd" minTickGap={28} />
          <YAxis tick={{ fill: 'var(--faint)', fontSize: 11 }} width={44} />
          <ReferenceLine y={0} stroke="var(--faint)" strokeDasharray="3 3" />
          <Tooltip
            contentStyle={{ background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)' }}
            labelStyle={{ color: 'var(--muted)' }}
            formatter={(v) => [fmt(v), 'Composite']} />
          <Line type="monotone" dataKey="v" stroke="var(--accent)" strokeWidth={2.4}
                dot={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
