"""
common.py — shared constants, domain lock, schema, and workbook I/O helpers.

This module is intentionally dependency-light (httpx + pandas + openpyxl) and is
imported by every stage of the ETL. The two things that matter most here:

  1. DOMAIN LOCK. Every outbound request in this project must pass through
     `guard_url()` / `guarded_get()`. The allowlist is a single set. If AMFI ever
     serves a redirect off-domain, the guard raises rather than following it.

  2. THE EXTENSIBLE LONG SCHEMA. `DATA_LONG_COLUMNS` is the tidy fact table.
     Adding a new data source later == appending rows with a new `source`/`metric`
     and adding a registry row. No column changes, ever.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pandas as pd

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ETL_DIR = Path(__file__).resolve().parent
ROOT = ETL_DIR.parent
DATA_DIR = ROOT / "data"
WORKBOOK_PATH = DATA_DIR / "liquidity_composite.xlsx"
WEB_DATA_DIR = ROOT / "web" / "public" / "data"

# --------------------------------------------------------------------------- #
# DOMAIN LOCK — single source of truth for allowed hosts.
# --------------------------------------------------------------------------- #
ALLOWED_DOMAINS = {"amfiindia.com"}

BASE_URL = "https://www.amfiindia.com"
RISK_PAGE_URL = f"{BASE_URL}/risk-parameters"
API_PATH = "/api/risk-parameter-data-revised"


class DomainLockError(RuntimeError):
    """Raised when a URL points outside the AMFI allowlist."""


def host_is_allowed(host: str) -> bool:
    """True iff `host` is amfiindia.com or a subdomain of it."""
    host = (host or "").lower().split(":")[0]
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)


def guard_url(url: str) -> str:
    """Raise DomainLockError unless `url` is on an allowed domain. Returns the url."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise DomainLockError(f"Refusing non-http(s) URL: {url!r}")
    if not host_is_allowed(parsed.hostname or ""):
        raise DomainLockError(
            f"Blocked off-domain request to {parsed.hostname!r}; "
            f"allowed domains are {sorted(ALLOWED_DOMAINS)}"
        )
    return url


def guarded_get(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    """
    GET through the domain guard. `follow_redirects` is forced OFF so AMFI cannot
    bounce us to another host without us noticing; if a redirect is returned we
    re-validate the Location against the allowlist before following it manually.
    """
    guard_url(url)
    kwargs.setdefault("timeout", 60)
    resp = client.get(url, follow_redirects=False, **kwargs)
    # Manually validate up to a few redirects, each re-checked against the lock.
    hops = 0
    while resp.is_redirect and hops < 5:
        location = resp.headers.get("location", "")
        # Resolve relative redirects against the current URL, then re-guard.
        next_url = str(httpx.URL(str(resp.url)).join(location))
        guard_url(next_url)
        resp = client.get(next_url, follow_redirects=False, **kwargs)
        hops += 1
    return resp


# --------------------------------------------------------------------------- #
# Category encoding (AMFI strCatId <-> our category slug)
# --------------------------------------------------------------------------- #
# AMFI only discloses mid-cap and small-cap under this mandate. `largecap` exists
# in the schema but is never populated from AMFI (see README / acceptance criteria).
CATID_TO_CATEGORY = {17: "midcap", 18: "smallcap"}
CATEGORY_TO_CATID = {v: k for k, v in CATID_TO_CATEGORY.items()}

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_NAME_TO_NUM = {
    m: i for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"], start=1)
}


def month_label_to_api_date(label: str) -> str:
    """'June 2026' -> '01-Jun-2026' (the exact format AMFI's API expects)."""
    name, year = label.split()
    return f"01-{MONTH_ABBR[MONTH_NAME_TO_NUM[name] - 1]}-{year}"


def month_label_to_month_end(label: str) -> dt.date:
    """'June 2026' -> date(2026, 6, 30). Disclosures cover the prior month-end."""
    name, year = label.split()
    num = MONTH_NAME_TO_NUM[name]
    year = int(year)
    if num == 12:
        first_next = dt.date(year + 1, 1, 1)
    else:
        first_next = dt.date(year, num + 1, 1)
    return first_next - dt.timedelta(days=1)


# --------------------------------------------------------------------------- #
# THE LONG SCHEMA
# --------------------------------------------------------------------------- #
DATA_LONG_COLUMNS = [
    "as_of_date",   # date (month-end)     e.g. 2026-06-30
    "source",       # text                 e.g. AMFI
    "category",     # text                 midcap / smallcap / largecap / market / macro
    "amc",          # text                 e.g. Quant
    "scheme_name",  # text                 e.g. Quant Small Cap Fund
    "metric",       # text                 e.g. days_to_liquidate_50pct
    "value",        # number
    "unit",         # text                 days / inr_cr / pct / ratio
]
# Natural key for idempotent upsert.
DATA_LONG_KEY = ["as_of_date", "source", "category", "scheme_name", "metric"]

REGISTRY_COLUMNS = [
    "series_id", "active", "source", "category", "metric", "scope",
    "aggregation", "direction", "normalization", "norm_window", "weight", "label",
]

TOP10_COLUMNS = ["as_of_date", "category", "rank", "scheme_name", "amc", "aum"]

SHEET_DATA_LONG = "data_long"
SHEET_REGISTRY = "series_registry"
SHEET_COMPOSITE = "composite"
SHEET_TOP10 = "top10_membership"


def seed_registry() -> pd.DataFrame:
    """The two AMFI series the brief asks us to seed. Everything else is hand-added."""
    rows = [
        dict(series_id="smallcap_liq50", active=True, source="AMFI",
             category="smallcap", metric="days_to_liquidate_50pct",
             scope="top10_by_aum", aggregation="mean", direction=1,
             normalization="zscore", norm_window="expanding", weight=1.0,
             label="Small Cap — days to liquidate 50%"),
        dict(series_id="midcap_liq50", active=True, source="AMFI",
             category="midcap", metric="days_to_liquidate_50pct",
             scope="top10_by_aum", aggregation="mean", direction=1,
             normalization="zscore", norm_window="expanding", weight=1.0,
             label="Mid Cap — days to liquidate 50%"),
    ]
    return pd.DataFrame(rows, columns=REGISTRY_COLUMNS)


def empty_frames() -> dict[str, pd.DataFrame]:
    """A fresh workbook: empty facts, seeded registry, empty computed sheets."""
    return {
        SHEET_DATA_LONG: pd.DataFrame(columns=DATA_LONG_COLUMNS),
        SHEET_REGISTRY: seed_registry(),
        SHEET_COMPOSITE: pd.DataFrame(columns=["as_of_date", "composite_score"]),
        SHEET_TOP10: pd.DataFrame(columns=TOP10_COLUMNS),
    }


def load_frames() -> dict[str, pd.DataFrame]:
    """
    Read the workbook back into DataFrames. If it does not exist yet, return a
    freshly seeded set. IMPORTANT: an existing `series_registry` is read verbatim
    so hand-edited weights/directions survive re-runs.
    """
    if not WORKBOOK_PATH.exists():
        return empty_frames()
    frames = empty_frames()
    xls = pd.ExcelFile(WORKBOOK_PATH, engine="openpyxl")
    for sheet in frames:
        if sheet in xls.sheet_names:
            df = xls.parse(sheet)
            if sheet == SHEET_DATA_LONG and not df.empty:
                df["as_of_date"] = pd.to_datetime(df["as_of_date"]).dt.date
            if sheet == SHEET_TOP10 and not df.empty:
                df["as_of_date"] = pd.to_datetime(df["as_of_date"]).dt.date
            frames[sheet] = df
    # If the registry sheet was somehow empty, re-seed it.
    if frames[SHEET_REGISTRY].empty:
        frames[SHEET_REGISTRY] = seed_registry()
    return frames
