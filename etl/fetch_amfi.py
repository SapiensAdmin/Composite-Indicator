"""
fetch_amfi.py — domain-locked AMFI fetcher (API-first, deterministic).

Resolved during recon (see README §Data source):
  GET https://www.amfiindia.com/api/risk-parameter-data-revised?strCatId={17|18}&date=01-Mon-YYYY
    strCatId 17 = Mid Cap, 18 = Small Cap
    date     first-of-month, e.g. 01-Jun-2026
  -> JSON array, one object per scheme (nested groups: stressTest / concentration /
     volatility / valuation). Unpublished months return HTTP 404 -> skipped cleanly.

The month list is enumerated dynamically from the risk-parameters page's embedded
RSC payload, so we never hardcode history. Everything goes through the domain guard.

Idempotent: rows are upserted on (as_of_date, source, category, scheme_name, metric),
so re-running never duplicates and missing months are purely additive.

A Playwright fallback (`--engine playwright`) is included for resilience, but the
JSON API is the default and has covered all history to date.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

import httpx
import pandas as pd

import common as C
from build_excel import write_workbook

SOURCE = "AMFI"

# How each nested API field maps into a long-table metric + unit.
# (metric_name, unit, extractor). Extractors are defensive: missing -> None.
def _g(d, *path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


METRIC_MAP = [
    ("days_to_liquidate_25pct", "days",   lambda r: _g(r, "stressTest", "StressTest_portfolio_25")),
    ("days_to_liquidate_50pct", "days",   lambda r: _g(r, "stressTest", "StressTest_portfolio_50")),
    ("aum",                     "inr_cr", lambda r: r.get("AUM")),
    ("portfolio_turnover",      "ratio",  lambda r: _g(r, "valuation", "Valuation_PortfolioTurnoverRatio")),
    ("std_dev_portfolio",       "pct",    lambda r: _g(r, "volatility", "Volatility_PortfolioASD")),
    ("std_dev_benchmark",       "pct",    lambda r: _g(r, "volatility", "Volatility_BenchmarkASD")),
    ("beta",                    "ratio",  lambda r: _g(r, "volatility", "Volatility_PortfolioBeta")),
    ("trailing_pe_12m",         "ratio",  lambda r: _g(r, "valuation", "Valuation_PortfolioTrailing12mPE")),
    ("benchmark_trailing_pe_12m",     "ratio", lambda r: _g(r, "valuation", "BenchMark", "Valuation_BenchmarkTrailing12mPE")),
    ("benchmark_trailing_pe_12m_1ya", "ratio", lambda r: _g(r, "valuation", "BenchMark", "Valuation_BenchmarkTrailing12mPE_1YA")),
    ("benchmark_trailing_pe_12m_2ya", "ratio", lambda r: _g(r, "valuation", "BenchMark", "Valuation_BenchmarkTrailing12mPE_2YA")),
    ("largecap_pct",            "pct",    lambda r: _g(r, "concentration", "AssetSide", "AssetSide_LargeCap")),
    ("midcap_pct",              "pct",    lambda r: _g(r, "concentration", "AssetSide", "AssetSide_MidCap")),
    ("smallcap_pct",            "pct",    lambda r: _g(r, "concentration", "AssetSide", "AssetSide_SmallCap")),
    ("cash_pct",                "pct",    lambda r: _g(r, "concentration", "AssetSide", "AssetSide_Cash")),
    ("top10_investor_pct",      "pct",    lambda r: _g(r, "concentration", "LiabilitySide")),
]


def _amc_from_mf_name(mf_name: str) -> str:
    """'Quant Mutual Fund' -> 'Quant'. Keep it simple + reversible."""
    name = (mf_name or "").strip()
    return re.sub(r"\s+Mutual Fund$", "", name, flags=re.IGNORECASE).strip() or name


# --------------------------------------------------------------------------- #
# Month enumeration (dynamic, from the page — never hardcoded)
# --------------------------------------------------------------------------- #
def enumerate_months(client: httpx.Client) -> list[str]:
    """
    Return month labels ('June 2026', ...) newest-first, parsed from the
    risk-parameters page's embedded data. Falls back to a rendered-text scan.
    """
    resp = C.guarded_get(client, C.RISK_PAGE_URL)
    resp.raise_for_status()
    html = resp.text

    # The page ships the dropdown as an escaped JS array: ["June 2026","May 2026",...]
    array_match = re.search(
        r'\[(?:[^\[\]]*?(?:January|February|March|April|May|June|July|August|'
        r'September|October|November|December)\s+20\d\d[^\[\]]*?)\]', html)
    labels: list[str] = []
    if array_match:
        labels = re.findall(
            r'(January|February|March|April|May|June|July|August|September|'
            r'October|November|December)\s+(20\d\d)', array_match.group(0))
        labels = [f"{m} {y}" for m, y in labels]

    if not labels:  # defensive fallback: scan whole page
        found = re.findall(
            r'(January|February|March|April|May|June|July|August|September|'
            r'October|November|December)\s+(20\d\d)', html)
        labels = [f"{m} {y}" for m, y in dict.fromkeys(found)]

    if not labels:
        raise RuntimeError("Could not enumerate any months from the AMFI page.")

    # De-dupe, sort newest-first by actual date.
    uniq = list(dict.fromkeys(labels))
    uniq.sort(key=lambda lab: C.month_label_to_month_end(lab), reverse=True)
    return uniq


# --------------------------------------------------------------------------- #
# Per month x category fetch
# --------------------------------------------------------------------------- #
def fetch_month_category(client: httpx.Client, month_label: str, category: str):
    """Return the raw JSON list for one month x category, or None if unpublished."""
    catid = C.CATEGORY_TO_CATID[category]
    api_date = C.month_label_to_api_date(month_label)
    url = f"{C.BASE_URL}{C.API_PATH}?strCatId={catid}&date={api_date}"
    resp = C.guarded_get(client, url)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    try:
        data = resp.json()
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or not data:
        return None
    return data


def records_to_long_rows(records: list, month_label: str, category: str) -> list[dict]:
    """Flatten one month x category API response into long rows."""
    as_of = C.month_label_to_month_end(month_label)
    rows: list[dict] = []
    for rec in records:
        scheme = (rec.get("SchemeName") or "").strip()
        if not scheme:
            continue
        amc = _amc_from_mf_name(rec.get("MF_Name", ""))
        for metric, unit, extract in METRIC_MAP:
            val = extract(rec)
            if val is None or (isinstance(val, str) and not val.strip()):
                continue
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue
            rows.append(dict(
                as_of_date=as_of, source=SOURCE, category=category,
                amc=amc, scheme_name=scheme, metric=metric,
                value=val, unit=unit))
    return rows


def upsert_data_long(existing: pd.DataFrame, new_rows: list[dict]) -> pd.DataFrame:
    """Append new rows and drop duplicates on the natural key (new wins)."""
    if not new_rows:
        return existing
    new_df = pd.DataFrame(new_rows, columns=C.DATA_LONG_COLUMNS)
    combined = pd.concat([existing, new_df], ignore_index=True)
    # Keep the LAST occurrence so a re-fetch overwrites an older value for the same key.
    combined = combined.drop_duplicates(subset=C.DATA_LONG_KEY, keep="last")
    return combined.reset_index(drop=True)


def rebuild_top10_membership(data_long: pd.DataFrame) -> pd.DataFrame:
    """
    Audit trail: for each (month, category with AUM) record the top-10-by-AUM set.
    Recomputed wholesale from data_long every run so it always matches the facts.
    """
    if data_long.empty:
        return pd.DataFrame(columns=C.TOP10_COLUMNS)
    aum = data_long[data_long["metric"] == "aum"].copy()
    if aum.empty:
        return pd.DataFrame(columns=C.TOP10_COLUMNS)
    out = []
    for (as_of, category), grp in aum.groupby(["as_of_date", "category"]):
        grp = grp.sort_values("value", ascending=False).head(10).reset_index(drop=True)
        for rank, row in enumerate(grp.itertuples(index=False), start=1):
            out.append(dict(as_of_date=as_of, category=category, rank=rank,
                            scheme_name=row.scheme_name, amc=row.amc, aum=row.value))
    return pd.DataFrame(out, columns=C.TOP10_COLUMNS)


# --------------------------------------------------------------------------- #
# Playwright fallback (kept for resilience; API path is the default)
# --------------------------------------------------------------------------- #
def fetch_all_playwright(months_limit=None) -> pd.DataFrame:  # pragma: no cover
    """
    Drive the risk-parameters UI with headless Chromium. Only used if the JSON API
    ever disappears. Still domain-locked: navigation is restricted to amfiindia.com.
    """
    from playwright.sync_api import sync_playwright

    frames = C.load_frames()
    data_long = frames[C.SHEET_DATA_LONG]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()

        def _route(route):
            if C.host_is_allowed(httpx.URL(route.request.url).host):
                route.continue_()
            else:
                route.abort()
        ctx.route("**/*", _route)

        page = ctx.new_page()
        C.guard_url(C.RISK_PAGE_URL)
        page.goto(C.RISK_PAGE_URL, wait_until="networkidle")
        options = page.eval_on_selector_all(
            "select >> nth=0 >> option", "els => els.map(e => e.textContent.trim())")
        months = [o for o in options if re.match(r"[A-Za-z]+ 20\d\d", o)]
        if months_limit:
            months = months[:months_limit]
        for month in months:
            for category in ("midcap", "smallcap"):
                data = fetch_month_category_via_page(page, month, category)
                if data:
                    rows = records_to_long_rows(data, month, category)
                    data_long = upsert_data_long(data_long, rows)
        browser.close()
    frames[C.SHEET_DATA_LONG] = data_long
    frames[C.SHEET_TOP10] = rebuild_top10_membership(data_long)
    return frames


def fetch_month_category_via_page(page, month_label, category):  # pragma: no cover
    """Intercept the same JSON XHR while driving the UI, staying on-domain."""
    catid = C.CATEGORY_TO_CATID[category]
    api_date = C.month_label_to_api_date(month_label)
    url = f"{C.BASE_URL}{C.API_PATH}?strCatId={catid}&date={api_date}"
    C.guard_url(url)
    resp = page.request.get(url)
    if resp.status != 200:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, list) and data else None


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run(engine: str = "api", months_limit: int | None = None, latest_only: bool = False) -> dict:
    frames = C.load_frames()

    if engine == "playwright":  # pragma: no cover
        frames = fetch_all_playwright(months_limit=months_limit)
        write_workbook(frames)
        return frames

    data_long = frames[C.SHEET_DATA_LONG]
    headers = {
        "User-Agent": "amfi-liquidity-stress-etl/1.0 (+github actions cron; contact repo owner)",
        "Accept": "application/json",
    }
    total_new = 0
    fetched_months = 0
    with httpx.Client(headers=headers) as client:
        months = enumerate_months(client)
        if latest_only:
            months = months[:1]
        elif months_limit:
            months = months[:months_limit]
        print(f"Enumerated {len(months)} month(s) from AMFI: "
              f"{months[0]} … {months[-1]}")

        for month in months:
            month_had_data = False
            for category in ("midcap", "smallcap"):
                data = fetch_month_category(client, month, category)
                if data is None:
                    print(f"  {month:15s} {category:9s}: not published — skip")
                    continue
                rows = records_to_long_rows(data, month, category)
                before = len(data_long)
                data_long = upsert_data_long(data_long, rows)
                added = len(data_long) - before
                total_new += max(added, 0)
                month_had_data = True
                print(f"  {month:15s} {category:9s}: {len(data):3d} schemes, "
                      f"{len(rows):4d} rows (+{added} new)")
            if month_had_data:
                fetched_months += 1

    if data_long.empty:
        print("No data fetched — leaving workbook unchanged (nothing to overwrite).")
        return frames

    frames[C.SHEET_DATA_LONG] = data_long
    frames[C.SHEET_TOP10] = rebuild_top10_membership(data_long)
    write_workbook(frames)
    print(f"data_long now holds {len(data_long)} rows across "
          f"{data_long['as_of_date'].nunique()} months. (+{total_new} new this run)")
    return frames


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch AMFI stress-test disclosures (domain-locked).")
    ap.add_argument("--engine", choices=["api", "playwright"], default="api",
                    help="api (default, deterministic JSON) or playwright fallback.")
    ap.add_argument("--months-limit", type=int, default=None,
                    help="Only fetch the N most recent months (debug/backfill control).")
    ap.add_argument("--latest-only", action="store_true",
                    help="Fetch only the single most recent published month.")
    args = ap.parse_args(argv)
    run(engine=args.engine, months_limit=args.months_limit, latest_only=args.latest_only)


if __name__ == "__main__":
    sys.exit(main())
