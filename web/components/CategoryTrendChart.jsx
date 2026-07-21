'use client';

import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip,
} from 'recharts';
import { fmt, monthLabel } from '@/lib/composite';

export default function CategoryTrendChart({ trend }) {
  const data = trend.map((r) => ({ ...r, label: monthLabel(r.as_of_date) }));

  return (
    <div className="card">
      <h2>Category stress trend</h2>
      <p className="card-sub">Top-10-by-AUM average days to liquidate 50% of the portfolio (higher ⇒ slower to exit).</p>

      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: 'var(--faint)', fontSize: 11 }}
                 interval="preserveStartEnd" minTickGap={28} />
          <YAxis tick={{ fill: 'var(--faint)', fontSize: 11 }} width={44}
                 label={{ value: 'days', angle: -90, position: 'insideLeft', fill: 'var(--faint)', fontSize: 11, dy: 20 }} />
          <Tooltip
            contentStyle={{ background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 8 }}
            labelStyle={{ color: 'var(--muted)' }}
            formatter={(v, n) => [fmt(v, 1) + ' days', n === 'smallcap' ? 'Small Cap' : 'Mid Cap']} />
          <Line type="monotone" dataKey="smallcap" stroke="var(--smallcap)" strokeWidth={2.2} dot={false} connectNulls />
          <Line type="monotone" dataKey="midcap" stroke="var(--midcap)" strokeWidth={2.2} dot={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>

      <div className="legend">
        <span><i style={{ background: 'var(--smallcap)' }} /> Small Cap (top 10)</span>
        <span><i style={{ background: 'var(--midcap)' }} /> Mid Cap (top 10)</span>
      </div>
    </div>
  );
}
