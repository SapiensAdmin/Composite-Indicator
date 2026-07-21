# AMFI Liquidity-Stress Composite

A small, self-contained data product that turns AMFI's monthly **mid-cap & small-cap
stress-test / liquidity disclosures** into a **custom, registry-weighted composite
indicator**, stored in one extensible Excel workbook and served as a Next.js
dashboard (deployable to Vercel). It refreshes automatically each month via a GitHub
Actions cron.

> **Regime gauge, not a trade trigger.** AMFI data is disclosed with a lag (~15th of
> the month, covering the prior month-end). The composite describes the *backdrop*.

## 🚀 Deploy to Vercel (from this repo)

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/git/external?repository-url=https://github.com/SapiensAdmin/Composite-Indicator&project-name=composite-indicator&root-directory=web&framework=nextjs)

**One click:** the button opens Vercel's import flow for this repo with **Root Directory = `web`**
and **Framework = Next.js** pre-filled. Authorize GitHub → Deploy → you get a live
`https://<project>.vercel.app` link. After that, every push to `main` (including the
monthly cron's data refresh) auto-redeploys — the deployment is fully driven from Git.

_Manual fallback:_ <https://vercel.com/new> → pick **Composite-Indicator** → set Root Directory to `web` → Deploy.

---

## 1. Data source (resolved during recon)

**Page:** <https://www.amfiindia.com/risk-parameters> — *"Disclosure of Stress Test &
Liquidity Analysis in respect of Mid Cap & Small Cap Funds"*. It's a client-rendered
Next.js SPA, but the table is populated by a clean background JSON API, so **no
browser is needed** — the fetcher is fully deterministic (API-first).

### Resolved endpoint

```
GET https://www.amfiindia.com/api/risk-parameter-data-revised?strCatId={CAT}&date={DATE}
```

| Param      | Meaning                                             | Values / format                  |
|------------|-----------------------------------------------------|----------------------------------|
| `strCatId` | Category                                            | `17` = Mid Cap, `18` = Small Cap |
| `date`     | Disclosure month (first-of-month, 3-letter month)   | e.g. `01-Jun-2026`               |
| `excel`    | *(optional)* `true` returns the `.xlsx` blob         | we use JSON, not this            |

- **Months** are enumerated dynamically from the page's embedded RSC payload
  (newest-first). Available history: **Feb 2024 → latest published**.
- **Unpublished / future months return HTTP 404** → the fetcher skips them cleanly
  (no crash, no partial overwrite).
- **Response**: a JSON array, one object per scheme, with nested groups
  `stressTest` / `concentration` / `volatility` / `valuation`. The structure is
  consistent across the full history.

### Column mapping (API → long-table `metric`)

| API field                                          | `metric`                       | `unit`   |
|----------------------------------------------------|--------------------------------|----------|
| `stressTest.StressTest_portfolio_25`               | `days_to_liquidate_25pct`      | days     |
| `stressTest.StressTest_portfolio_50`               | `days_to_liquidate_50pct`      | days     |
| `AUM`                                              | `aum`                          | inr_cr   |
| `valuation.Valuation_PortfolioTurnoverRatio`       | `portfolio_turnover`           | ratio    |
| `volatility.Volatility_PortfolioASD`               | `std_dev_portfolio`            | pct      |
| `volatility.Volatility_BenchmarkASD`               | `std_dev_benchmark`            | pct      |
| `volatility.Volatility_PortfolioBeta`              | `beta`                         | ratio    |
| `valuation.Valuation_PortfolioTrailing12mPE`       | `trailing_pe_12m`              | ratio    |
| `valuation.BenchMark.Valuation_BenchmarkTrailing12mPE(_1YA/_2YA)` | `benchmark_trailing_pe_12m(_1ya/_2ya)` | ratio |
| `concentration.AssetSide.AssetSide_LargeCap`       | `largecap_pct`                 | pct      |
| `concentration.AssetSide.AssetSide_MidCap`         | `midcap_pct`                   | pct      |
| `concentration.AssetSide.AssetSide_SmallCap`       | `smallcap_pct`                 | pct      |
| `concentration.AssetSide.AssetSide_Cash`           | `cash_pct`                     | pct      |
| `concentration.LiabilitySide`                      | `top10_investor_pct`           | pct      |

All disclosed metrics are captured (not pre-filtered), so the workbook is future-proof.

### Domain lock

Every request passes through `guard_url()` in `etl/common.py`. The allowlist is a
single set — `ALLOWED_DOMAINS = {"amfiindia.com"}` — and redirects are **not**
auto-followed; each hop is re-validated against the lock. Nothing off `amfiindia.com`
is ever fetched (the Playwright fallback aborts off-domain routes too).

---

## 2. Data model — `data/liquidity_composite.xlsx` (4 sheets)

Mirrored to machine-readable JSON under `web/public/data/`.

- **`data_long`** — tidy fact table, the single source of truth. One row per
  *metric × scheme × month*: `as_of_date, source, category, amc, scheme_name,
  metric, value, unit`. **Adding a new source = new rows only.**
- **`series_registry`** — the composite control panel (**you hand-edit this**). One
  row per input series: `series_id, active, source, category, metric, scope,
  aggregation, direction, normalization, norm_window, weight, label`.
- **`composite`** — computed: one column per active series (normalized ·
  direction) plus `composite_score`.
- **`top10_membership`** — audit trail of which 10 schemes were top-10-by-AUM each
  month × category (membership drift is expected; full `data_long` is always kept).

`largecap` exists in the schema but stays **empty** — AMFI has no large-cap stress
test under this mandate. It's never fabricated.

---

## 3. Composite logic (`etl/compute_composite.py`)

For each **active** registry series, per month:

1. Select the category's schemes, rank by `aum`, take **top 10** (`scope`).
2. Aggregate the metric (`mean` or `aum_weighted`).
3. Normalize across history (`zscore` default; also `percentile` / `minmax`;
   `norm_window` = `expanding` default or e.g. `24m` rolling). Uses only history up
   to each point (no look-ahead); constant series → 0 (never inf/NaN).
4. Multiply by `direction` (`+1` = higher ⇒ more stress; `-1` = higher ⇒ safer).
5. Normalize active `weight`s to sum 1 and take the weighted sum.

```
composite_score(t) = Σ_active  normalized(series, t) · direction · weight_norm
```

Units differ across series, so raw values are **never** summed — always normalized
first. Weights are renormalized per month over the series that actually have data,
so early months stay well-defined. See `etl/test_composite.py` for the guarantee
that a constant input normalizes to ~0 and doesn't blow up.

---

## 4. Repo layout

```
etl/
  common.py            # domain lock, schema, workbook I/O
  fetch_amfi.py        # API-first (Playwright fallback); iterates month × category
  build_excel.py       # assembles the 4-sheet workbook (preserves hand-edited registry)
  compute_composite.py # registry-driven composite -> Sheet C + composite.json
  export_json.py       # data_long / trend / scheme table / membership / meta -> JSON
  run_all.py           # orchestrates fetch -> excel -> composite -> json
  test_composite.py    # unit tests (math + extensibility)
  requirements.txt
data/
  liquidity_composite.xlsx
web/                   # Next.js (App Router) dashboard, deployable to Vercel
  app/  components/  lib/  public/data/*.json
.github/workflows/
  monthly.yml          # cron ETL + auto-commit
```

---

## 5. Run locally

```bash
# ETL (Python 3.11+)
pip install -r etl/requirements.txt
python etl/run_all.py                 # full backfill + compute + export
python etl/run_all.py --latest-only   # just the newest published month
python etl/run_all.py --skip-fetch    # recompute from existing data (no network)
cd etl && python -m pytest test_composite.py -q

# Dashboard
cd web && npm install && npm run dev   # http://localhost:3000
```

Re-running is **idempotent**: rows upsert on
`as_of_date + source + category + scheme_name + metric`, so nothing duplicates and
missing months are purely additive.

---

## 6. Add a new source later (the whole point)

No schema or code changes — two steps:

1. **Append rows to `data_long`** with a new `source` / `metric`. e.g. NSE turnover
   becomes `source=NSE, category=market, metric=cash_turnover_adv, unit=inr_cr`;
   PE/VC exits become `source=PEVC, category=macro, metric=public_market_exits,
   unit=inr_bn`. (Write a small fetcher that emits these long rows, mirroring
   `fetch_amfi.py`.)
2. **Add one row to `series_registry`** with the `series_id`, `source`, `category`,
   `metric`, `scope` (`all` for market/macro series with no per-scheme AUM),
   `aggregation`, `direction`, `weight`, `label`, and set `active = TRUE`.

Re-run (or let the cron run) — it flows into the composite automatically. This is
covered by `test_extensibility_new_source_flows_in` in the test suite.

To **re-weight**: just edit `weight` / `direction` in `series_registry` and re-run.
No code edits.

---

## 7. Deploy to Vercel

1. Import this repo into Vercel.
2. Set **Root Directory = `web`**, **Framework = Next.js**. Build/output are
   auto-detected (`next build`).
3. Deploy. The dashboard reads `web/public/data/*.json` at runtime.

Every push to `main` redeploys automatically.

## 8. Monthly refresh (GitHub Actions)

`.github/workflows/monthly.yml` runs on the **16th of each month** (after AMFI's
~15th update) and on manual `workflow_dispatch`:

`checkout → setup Python → pip install → python etl/run_all.py → pytest →
git-auto-commit` of `data/liquidity_composite.xlsx` and `web/public/data/*.json`.

The commit triggers Vercel to rebuild the dashboard with fresh data. The workflow
needs `contents: write` permission (already set).

---

## 9. Caveats

- AMFI's format can change; the parser is defensive (missing fields are skipped, not
  guessed) and fails loudly rather than silently dropping months.
- The composite is a **monthly, lagged regime/context gauge** — not an entry/exit
  signal.
- The `series_registry` sheet is the single source of truth for weights & direction,
  keeping the whole thing custom-weighted and editable without touching code.
