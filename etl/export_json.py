"""
export_json.py — mirror machine-readable outputs to web/public/data/*.json.

Emitted files (composite.json is written by compute_composite.py):
  data_long.json        full tidy fact table (extensibility / debugging)
  category_trend.json   top-10 avg days_to_liquidate_50pct, midcap vs smallcap, monthly
  scheme_table.json     top-10 per category with liq50 for the two most recent months
  top10_membership.json audit trail
  meta.json             coverage + provenance for the dashboard header
"""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd

import common as C

LIQ50 = "days_to_liquidate_50pct"


def _iso(d):
    return pd.to_datetime(d).date().isoformat()


def _top10_metric_by_month(data_long: pd.DataFrame, category: str, metric: str) -> dict:
    """month -> mean(metric) over the top-10-by-AUM schemes for that category."""
    sub = data_long[data_long["category"] == category]
    aum = sub[sub["metric"] == "aum"]
    mt = sub[sub["metric"] == metric]
    result = {}
    for as_of, m_grp in mt.groupby("as_of_date"):
        aum_map = (aum[aum["as_of_date"] == as_of]
                   .set_index("scheme_name")["value"].to_dict())
        vals = m_grp.set_index("scheme_name")["value"]
        if aum_map:
            top = sorted(aum_map, key=aum_map.get, reverse=True)[:10]
            vals = vals[vals.index.isin(top)]
        if len(vals):
            result[_iso(as_of)] = round(float(vals.mean()), 3)
    return result


def build_category_trend(data_long: pd.DataFrame) -> list[dict]:
    mid = _top10_metric_by_month(data_long, "midcap", LIQ50)
    small = _top10_metric_by_month(data_long, "smallcap", LIQ50)
    dates = sorted(set(mid) | set(small))
    return [{"as_of_date": d, "midcap": mid.get(d), "smallcap": small.get(d)} for d in dates]


def build_scheme_table(data_long: pd.DataFrame) -> dict:
    """Top-10 per category with liq50 for the two most recent months, side by side."""
    if data_long.empty:
        return {"months": [], "categories": {}}
    months = sorted(data_long["as_of_date"].unique())
    recent = months[-2:]
    recent_iso = [_iso(m) for m in recent]
    out = {"months": recent_iso, "categories": {}}

    for category in ("midcap", "smallcap"):
        sub = data_long[data_long["category"] == category]
        latest = recent[-1]
        aum_latest = (sub[(sub["metric"] == "aum") & (sub["as_of_date"] == latest)]
                      .set_index("scheme_name")["value"].to_dict())
        top = sorted(aum_latest, key=aum_latest.get, reverse=True)[:10]
        rows = []
        for scheme in top:
            row = {"scheme_name": scheme,
                   "amc": _amc_for(sub, scheme),
                   "aum": round(float(aum_latest.get(scheme, float("nan"))), 2)}
            liq = sub[(sub["metric"] == LIQ50) & (sub["scheme_name"] == scheme)]
            for m, m_iso in zip(recent, recent_iso):
                v = liq[liq["as_of_date"] == m]["value"]
                row[m_iso] = round(float(v.iloc[0]), 2) if len(v) else None
            rows.append(row)
        out["categories"][category] = rows
    return out


def _amc_for(sub: pd.DataFrame, scheme: str) -> str:
    s = sub[sub["scheme_name"] == scheme]["amc"]
    return str(s.iloc[0]) if len(s) else ""


def build_data_long_json(data_long: pd.DataFrame) -> list[dict]:
    if data_long.empty:
        return []
    df = data_long.copy()
    df["as_of_date"] = df["as_of_date"].map(_iso)
    return df[C.DATA_LONG_COLUMNS].to_dict(orient="records")


def build_top10_json(top10: pd.DataFrame) -> list[dict]:
    if top10.empty:
        return []
    df = top10.copy()
    df["as_of_date"] = df["as_of_date"].map(_iso)
    df["aum"] = df["aum"].round(2)
    return df[C.TOP10_COLUMNS].to_dict(orient="records")


def build_meta(data_long: pd.DataFrame, registry: pd.DataFrame) -> dict:
    months = sorted({_iso(d) for d in data_long["as_of_date"].unique()}) if not data_long.empty else []
    cats = sorted(data_long["category"].unique().tolist()) if not data_long.empty else []
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": "AMFI — Disclosure of Stress Test & Liquidity Analysis (Mid & Small Cap)",
        "source_url": C.RISK_PAGE_URL,
        "api_endpoint": f"{C.BASE_URL}{C.API_PATH}?strCatId=<17|18>&date=<01-Mon-YYYY>",
        "months_covered": months,
        "first_month": months[0] if months else None,
        "latest_month": months[-1] if months else None,
        "categories_present": cats,
        "n_active_series": int(registry["active"].apply(
            lambda v: str(v).strip().lower() in ("true", "1", "yes")).sum()) if not registry.empty else 0,
        "disclaimer": ("Monthly context / regime gauge, not a trade trigger. "
                       "AMFI data is disclosed with a lag (~15th, covering prior month-end)."),
    }


def run() -> None:
    frames = C.load_frames()
    data_long = frames[C.SHEET_DATA_LONG]
    C.WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)

    outputs = {
        "data_long.json": build_data_long_json(data_long),
        "category_trend.json": build_category_trend(data_long),
        "scheme_table.json": build_scheme_table(data_long),
        "top10_membership.json": build_top10_json(frames[C.SHEET_TOP10]),
        "meta.json": build_meta(data_long, frames[C.SHEET_REGISTRY]),
    }
    for name, payload in outputs.items():
        (C.WEB_DATA_DIR / name).write_text(json.dumps(payload, indent=2))
        size = len(payload) if isinstance(payload, list) else "obj"
        print(f"  wrote {name} ({size} records)")


if __name__ == "__main__":
    run()
