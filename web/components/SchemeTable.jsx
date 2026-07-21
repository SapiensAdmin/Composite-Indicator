'use client';

import { useMemo, useState } from 'react';
import { fmt, monthLabel } from '@/lib/composite';

export default function SchemeTable({ table }) {
  const [cat, setCat] = useState('smallcap');
  const [sortKey, setSortKey] = useState('aum');
  const [asc, setAsc] = useState(false);

  const months = table.months || [];
  const [prevM, lastM] = months.length === 2 ? months : [months[0], months[0]];
  const rows = (table.categories?.[cat] || []).map((r) => ({
    ...r,
    prev: r[prevM] ?? null,
    last: r[lastM] ?? null,
    delta: r[lastM] != null && r[prevM] != null ? r[lastM] - r[prevM] : null,
  }));

  const sorted = useMemo(() => {
    const s = [...rows].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === 'string') return asc ? av.localeCompare(bv) : bv.localeCompare(av);
      return asc ? av - bv : bv - av;
    });
    return s;
  }, [rows, sortKey, asc]);

  const setSort = (k) => {
    if (k === sortKey) setAsc(!asc);
    else { setSortKey(k); setAsc(k === 'scheme_name'); }
  };
  const th = (k, label) => (
    <th className={k === sortKey ? 'active' : ''} onClick={() => setSort(k)}>
      {label}{k === sortKey ? (asc ? ' ▲' : ' ▼') : ''}
    </th>
  );

  return (
    <div className="card">
      <h2>Latest scheme detail — top 10 by AUM</h2>
      <p className="card-sub">Days to liquidate 50%, two most recent disclosures side by side. Click a header to sort.</p>

      <div className="tabs">
        <button className={cat === 'smallcap' ? 'active' : ''} onClick={() => setCat('smallcap')}>Small Cap</button>
        <button className={cat === 'midcap' ? 'active' : ''} onClick={() => setCat('midcap')}>Mid Cap</button>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {th('scheme_name', 'Scheme')}
              {th('aum', 'AUM (₹cr)')}
              {th('prev', monthLabel(prevM))}
              {th('last', monthLabel(lastM))}
              {th('delta', 'Δ')}
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.scheme_name}>
                <td className="scheme">
                  {r.scheme_name}<br /><span className="amc">{r.amc}</span>
                </td>
                <td>{fmt(r.aum, 0)}</td>
                <td>{fmt(r.prev, 1)}</td>
                <td>{fmt(r.last, 1)}</td>
                <td className={`delta ${r.delta > 0 ? 'up' : r.delta < 0 ? 'down' : ''}`}>
                  {r.delta == null ? '—' : (r.delta > 0 ? '+' : '') + fmt(r.delta, 1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
