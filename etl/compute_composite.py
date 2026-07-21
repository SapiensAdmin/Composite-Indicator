"""
compute_composite.py — the custom weighted composite indicator.

Everything here is driven by the `series_registry` sheet. Re-weighting or flipping
a direction means editing that sheet and re-running — NO code changes. Units differ
across series (days vs INR vs %), so we NEVER sum raw values: each series is
normalized first, then direction-applied, then weighted.

    composite_score(t) = Σ_active  normalized(series, t) · direction · weight_norm

`compute_composite()` is deliberately one well-commented function surface so the
math is obvious and editable. See test_composite.py for the "constant input
normalizes to ~0 and doesn't blow up" guarantee.
"""
from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd

import common as C
from build_excel import write_workbook


# --------------------------------------------------------------------------- #
# 1) Per-series monthly RAW aggregation (top-10-by-AUM, mean or AUM-weighted)
# --------------------------------------------------------------------------- #
def series_monthly_raw(data_long: pd.DataFrame, series: pd.Series) -> pd.Series:
    """
    Build the monthly raw value for one registry series across all history.

    scope 'top10_by_aum' -> rank the category's schemes by AUM each month, keep the
    top 10, then aggregate the target metric ('mean' or 'aum_weighted'). scope 'all'
    aggregates every scheme/row (used by future market/macro sources with no AUM).
    """
    src, cat, metric = series["source"], series["category"], series["metric"]
    scope = str(series.get("scope", "top10_by_aum"))
    agg = str(series.get("aggregation", "mean"))

    sub = data_long[(data_long["source"] == src) & (data_long["category"] == cat)]
    if sub.empty:
        return pd.Series(dtype=float)

    metric_rows = sub[sub["metric"] == metric]
    aum_rows = sub[sub["metric"] == "aum"]

    out: dict[dt.date, float] = {}
    for as_of, m_grp in metric_rows.groupby("as_of_date"):
        vals = m_grp[["scheme_name", "value"]].dropna()
        if vals.empty:
            continue

        # AUM map for this month (used for ranking and/or weighting).
        aum_map = (aum_rows[aum_rows["as_of_date"] == as_of]
                   .set_index("scheme_name")["value"].to_dict())

        if scope == "top10_by_aum" and aum_map:
            top = sorted(aum_map, key=aum_map.get, reverse=True)[:10]
            vals = vals[vals["scheme_name"].isin(top)]
            if vals.empty:
                continue

        if agg == "aum_weighted" and aum_map:
            w = vals["scheme_name"].map(aum_map).astype(float)
            if w.fillna(0).sum() > 0:
                out[as_of] = float(np.average(vals["value"], weights=w.fillna(0)))
                continue
        # default: simple mean
        out[as_of] = float(vals["value"].mean())

    s = pd.Series(out, dtype=float).sort_index()
    s.index = pd.to_datetime(s.index)
    return s


# --------------------------------------------------------------------------- #
# 2) Normalization (zscore / percentile / minmax; expanding or rolling window)
# --------------------------------------------------------------------------- #
def _window_indexer(n: int, i: int, norm_window: str):
    """Return the slice start for point i given an expanding or 'Nm' rolling window."""
    if norm_window and norm_window.lower() != "expanding":
        m = str(norm_window).lower().strip()
        if m.endswith("m") and m[:-1].isdigit():
            k = int(m[:-1])
            return max(0, i - k + 1)
    return 0  # expanding


def normalize_series(raw: pd.Series, normalization: str = "zscore",
                     norm_window: str = "expanding") -> pd.Series:
    """
    Normalize a raw monthly series point-by-point using only history up to that
    point (no look-ahead). Constant/degenerate windows return 0 — never inf/NaN
    from divide-by-zero.
    """
    normalization = (normalization or "zscore").lower()
    raw = raw.sort_index()
    vals = raw.values.astype(float)
    n = len(vals)
    out = np.zeros(n, dtype=float)

    for i in range(n):
        start = _window_indexer(n, i, norm_window)
        hist = vals[start:i + 1]
        hist = hist[~np.isnan(hist)]
        x = vals[i]
        if np.isnan(x) or len(hist) == 0:
            out[i] = np.nan
            continue
        if normalization == "zscore":
            mu, sd = hist.mean(), hist.std(ddof=0)
            out[i] = 0.0 if sd == 0 else (x - mu) / sd
        elif normalization == "percentile":
            # rank of x within history, mapped to [-1, 1] so it's centred like z.
            pct = (hist <= x).mean()
            out[i] = 2.0 * pct - 1.0
        elif normalization == "minmax":
            lo, hi = hist.min(), hist.max()
            out[i] = 0.0 if hi == lo else (x - lo) / (hi - lo)
        else:
            raise ValueError(f"Unknown normalization: {normalization!r}")
    return pd.Series(out, index=raw.index)


# --------------------------------------------------------------------------- #
# 3) The composite
# --------------------------------------------------------------------------- #
def compute_composite(data_long: pd.DataFrame, registry: pd.DataFrame):
    """
    Returns (composite_df, series_meta).

    composite_df: index=as_of_date, one column per active series (values are
      normalized · direction — i.e. 'direction-applied'), plus 'composite_score'.
    series_meta: list of dicts describing each active series for the dashboard's
      live-reweighting panel (default weight, direction, label, per-date values).

    Weights are normalized to sum to 1 across the active series that actually have
    a value in a given month, so early months (where one category may lag) still
    produce a well-defined score.
    """
    if isinstance(registry, pd.DataFrame) and not registry.empty:
        active = registry[registry["active"].apply(_truthy)].copy()
    else:
        active = pd.DataFrame(columns=C.REGISTRY_COLUMNS)

    contributions: dict[str, pd.Series] = {}  # normalized * direction
    weights: dict[str, float] = {}
    series_meta = []

    for _, series in active.iterrows():
        sid = str(series["series_id"])
        raw = series_monthly_raw(data_long, series)
        norm = normalize_series(raw, series.get("normalization", "zscore"),
                                str(series.get("norm_window", "expanding")))
        direction = float(series.get("direction", 1) or 1)
        contrib = norm * direction
        contributions[sid] = contrib
        weights[sid] = float(series.get("weight", 1) or 0)
        series_meta.append(dict(
            series_id=sid, label=str(series.get("label", sid)),
            direction=int(direction), weight=weights[sid],
            normalization=str(series.get("normalization", "zscore")),
            raw=raw, contribution=contrib))

    if not contributions:
        return (pd.DataFrame(columns=["composite_score"]), series_meta)

    contrib_df = pd.DataFrame(contributions).sort_index()

    # Weighted sum with per-month renormalization over present series.
    w = pd.Series(weights, dtype=float)
    scores = []
    for _, row in contrib_df.iterrows():
        present = row.dropna().index
        if len(present) == 0:
            scores.append(np.nan)
            continue
        wp = w[present]
        wsum = wp.sum()
        if wsum == 0:
            scores.append(np.nan)
            continue
        scores.append(float((row[present] * (wp / wsum)).sum()))

    out = contrib_df.copy()
    out["composite_score"] = scores
    out.index.name = "as_of_date"
    return out, series_meta


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "y", "t")
    return bool(v)


# --------------------------------------------------------------------------- #
# 4) Persist: Sheet C + composite.json
# --------------------------------------------------------------------------- #
def composite_to_sheet(composite_df: pd.DataFrame) -> pd.DataFrame:
    if composite_df.empty:
        return pd.DataFrame(columns=["as_of_date", "composite_score"])
    df = composite_df.reset_index()
    df["as_of_date"] = pd.to_datetime(df["as_of_date"]).dt.date
    # round for readability; keep composite_score last
    num_cols = [c for c in df.columns if c != "as_of_date"]
    df[num_cols] = df[num_cols].round(4)
    cols = ["as_of_date"] + [c for c in num_cols if c != "composite_score"] + ["composite_score"]
    return df[cols]


def build_composite_json(composite_df: pd.DataFrame, series_meta: list) -> dict:
    """Everything the dashboard needs, including pre-normalized series for live re-weighting."""
    if composite_df.empty:
        return {"generated_at": _now(), "dates": [], "series": [], "composite": [], "latest": None}
    dates = [pd.to_datetime(d).date().isoformat() for d in composite_df.index]
    series_out = []
    for meta in series_meta:
        contrib = meta["contribution"].reindex(composite_df.index)
        raw = meta["raw"].reindex(composite_df.index)
        series_out.append(dict(
            series_id=meta["series_id"], label=meta["label"],
            direction=meta["direction"], default_weight=meta["weight"],
            normalization=meta["normalization"],
            # 'values' are normalized·direction — the browser multiplies by weight.
            values=[_num(v) for v in contrib.values],
            raw=[_num(v) for v in raw.values],
        ))
    comp = [_num(v) for v in composite_df["composite_score"].values]
    latest = None
    for d, v in zip(reversed(dates), reversed(comp)):
        if v is not None:
            latest = {"as_of_date": d, "value": v}
            break
    return {"generated_at": _now(), "dates": dates, "series": series_out,
            "composite": comp, "latest": latest}


def _num(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 6)


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def run() -> dict:
    frames = C.load_frames()
    composite_df, series_meta = compute_composite(
        frames[C.SHEET_DATA_LONG], frames[C.SHEET_REGISTRY])
    frames[C.SHEET_COMPOSITE] = composite_to_sheet(composite_df)
    write_workbook(frames)

    C.WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_composite_json(composite_df, series_meta)
    (C.WEB_DATA_DIR / "composite.json").write_text(json.dumps(payload, indent=2))
    n = len(payload["dates"])
    latest = payload["latest"]
    print(f"Composite computed over {n} months; "
          f"latest {latest['as_of_date'] if latest else 'n/a'} = "
          f"{latest['value'] if latest else 'n/a'}")
    return frames


if __name__ == "__main__":
    run()
