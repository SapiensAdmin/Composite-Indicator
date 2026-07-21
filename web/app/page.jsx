'use client';

import { useEffect, useState } from 'react';
import { loadJSON, monthLabel } from '@/lib/composite';
import CompositeChart from '@/components/CompositeChart';
import CategoryTrendChart from '@/components/CategoryTrendChart';
import SchemeTable from '@/components/SchemeTable';
import WeightingPanel from '@/components/WeightingPanel';

const BASE = process.env.NEXT_PUBLIC_BASE_PATH || '';

export default function Home() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([
      loadJSON(`${BASE}/data/composite.json`),
      loadJSON(`${BASE}/data/category_trend.json`),
      loadJSON(`${BASE}/data/scheme_table.json`),
      loadJSON(`${BASE}/data/meta.json`),
    ])
      .then(([composite, trend, table, meta]) => setData({ composite, trend, table, meta }))
      .catch((e) => setError(e.message));
  }, []);

  return (
    <main className="container">
      <header className="site-header">
        <h1>AMFI Liquidity-Stress Composite</h1>
        <p className="sub">
          A custom, registry-weighted gauge built from AMFI’s monthly mid-cap &amp; small-cap
          stress-test &amp; liquidity disclosures.
        </p>
      </header>

      <div className="notice">
        <strong>Read this as a monthly context / regime gauge — not a trade trigger.</strong>{' '}
        AMFI data is disclosed with a lag (around the 15th, covering the prior month-end), so the
        composite describes the <em>backdrop</em>, not an entry or exit signal. Higher score ⇒ more
        liquidity stress / froth relative to this series’ own history.
        {data?.meta?.latest_month && (
          <> Coverage: {monthLabel(data.meta.first_month)} → {monthLabel(data.meta.latest_month)}.</>
        )}
      </div>

      {error && <div className="loading">Couldn’t load data: {error}</div>}
      {!data && !error && <div className="loading">Loading composite…</div>}

      {data && (
        <>
          <div className="grid two">
            <CompositeChart composite={data.composite} />
            <WeightingPanel composite={data.composite} />
          </div>

          <div className="section-title">Underlying category trend</div>
          <div className="grid">
            <CategoryTrendChart trend={data.trend} />
          </div>

          <div className="section-title">Scheme-level detail</div>
          <div className="grid">
            <SchemeTable table={data.table} />
          </div>

          <footer className="footer">
            Source: <a href={data.meta.source_url} target="_blank" rel="noreferrer">AMFI — {data.meta.source}</a>.{' '}
            Data domain-locked to amfiindia.com. Composite is z-scored per series over expanding history and
            weighted per the editable <code>series_registry</code> sheet.<br />
            Last refreshed: {data.meta.generated_at}. This is an analytical context tool, not investment advice.
          </footer>
        </>
      )}
    </main>
  );
}
