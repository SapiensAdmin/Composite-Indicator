// lib/composite.js
// Live re-weighting math for the interactive panel. This MUST match the ETL's
// compute_composite() weighting step exactly:
//
//   composite(t) = Σ_present  value(series,t) · (weight / Σ weights_present)
//
// where value = normalized·direction (already baked into composite.json's
// series[].values). Weights are renormalized per-month over the series that
// actually have a value that month, so early months stay well-defined.

export function recomputeComposite(series, weights) {
  // series: [{ series_id, values: (number|null)[] }]
  // weights: { series_id: number }
  if (!series.length) return [];
  const n = series[0].values.length;
  const out = new Array(n).fill(null);

  for (let t = 0; t < n; t++) {
    let wsum = 0;
    let acc = 0;
    let present = 0;
    for (const s of series) {
      const v = s.values[t];
      if (v === null || v === undefined || Number.isNaN(v)) continue;
      const w = Math.max(0, Number(weights[s.series_id] ?? 0));
      wsum += w;
      acc += v * w;
      present += 1;
    }
    out[t] = present > 0 && wsum > 0 ? acc / wsum : null;
  }
  return out;
}

export async function loadJSON(path) {
  const res = await fetch(path, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
  return res.json();
}

export function fmt(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return Number(v).toFixed(digits);
}

export function monthLabel(iso) {
  if (!iso) return '';
  const d = new Date(iso + 'T00:00:00Z');
  return d.toLocaleDateString('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' });
}
