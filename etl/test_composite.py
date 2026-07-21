"""
test_composite.py — unit tests for the composite math and extensibility.

Run:  cd etl && python -m pytest test_composite.py -q
(or:  python test_composite.py  — falls back to a plain runner if pytest absent)

Key guarantees:
  * A flat/constant input series normalizes to ~0 and never blows up (§3 of the brief).
  * Direction and weights behave as specified.
  * A brand-new source=TEST flows into the composite with only a registry row added
    (no schema/code changes) — proving extensibility.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

import common as C
import compute_composite as CC


def _month_ends(n):
    out, y, m = [], 2024, 3
    for _ in range(n):
        if m == 12:
            nxt = dt.date(y + 1, 1, 1)
        else:
            nxt = dt.date(y, m + 1, 1)
        out.append(nxt - dt.timedelta(days=1))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _long_rows(category, metric, per_month_values, unit="days", source="AMFI"):
    """Build long rows: per_month_values = list of {scheme: value} dicts, one per month."""
    dates = _month_ends(len(per_month_values))
    rows = []
    for d, scheme_vals in zip(dates, per_month_values):
        for scheme, v in scheme_vals.items():
            rows.append(dict(as_of_date=d, source=source, category=category,
                             amc=scheme.split()[0], scheme_name=scheme,
                             metric=metric, value=float(v), unit=unit))
    return rows


def test_constant_series_normalizes_to_zero():
    """Flat input -> z-score ~0, no NaN/inf."""
    raw = pd.Series([5.0] * 12, index=pd.to_datetime(_month_ends(12)))
    norm = CC.normalize_series(raw, "zscore", "expanding")
    assert np.all(np.isfinite(norm.values)), "constant series produced non-finite z-scores"
    assert np.allclose(norm.values, 0.0), "constant series should normalize to 0"


def test_zscore_last_point_direction():
    """A jump up in the last month yields a positive z-score."""
    raw = pd.Series([1, 1, 1, 1, 5.0], index=pd.to_datetime(_month_ends(5)))
    norm = CC.normalize_series(raw, "zscore", "expanding")
    assert norm.iloc[-1] > 0


def test_rolling_window_parses():
    raw = pd.Series(range(1, 31), index=pd.to_datetime(_month_ends(30)), dtype=float)
    norm = CC.normalize_series(raw, "zscore", "24m")
    assert np.all(np.isfinite(norm.values))


def test_minmax_and_percentile_bounds():
    raw = pd.Series([2, 4, 6, 8, 10.0], index=pd.to_datetime(_month_ends(5)))
    mm = CC.normalize_series(raw, "minmax", "expanding")
    assert 0.0 <= mm.iloc[-1] <= 1.0
    pc = CC.normalize_series(raw, "percentile", "expanding")
    assert -1.0 <= pc.iloc[-1] <= 1.0


def test_direction_flips_sign():
    rows = _long_rows("smallcap", "days_to_liquidate_50pct",
                      [{"A Fund": 10, "B Fund": 20}, {"A Fund": 30, "B Fund": 40}])
    # add AUM so top10 ranking has something to rank
    rows += _long_rows("smallcap", "aum",
                       [{"A Fund": 100, "B Fund": 50}, {"A Fund": 100, "B Fund": 50}],
                       unit="inr_cr")
    data_long = pd.DataFrame(rows, columns=C.DATA_LONG_COLUMNS)

    def reg(direction):
        r = C.seed_registry().iloc[[0]].copy()
        r["direction"] = direction
        return r

    up, _ = CC.compute_composite(data_long, reg(+1))
    down, _ = CC.compute_composite(data_long, reg(-1))
    assert np.sign(up["composite_score"].iloc[-1]) == -np.sign(down["composite_score"].iloc[-1])


def test_extensibility_new_source_flows_in():
    """
    Add source=TEST rows + one registry row -> it appears in the composite with NO
    schema or code changes. This mirrors acceptance-criterion 'add a dummy TEST row'.
    """
    rows = _long_rows("smallcap", "days_to_liquidate_50pct",
                      [{"A Fund": 10}, {"A Fund": 20}, {"A Fund": 30}])
    rows += _long_rows("smallcap", "aum",
                       [{"A Fund": 100}, {"A Fund": 100}, {"A Fund": 100}], unit="inr_cr")
    # brand-new source, brand-new category ('macro'), scope 'all' (no AUM needed)
    rows += _long_rows("macro", "public_market_exits",
                       [{"MarketAgg": 1}, {"MarketAgg": 3}, {"MarketAgg": 9}],
                       unit="inr_bn", source="TEST")
    data_long = pd.DataFrame(rows, columns=C.DATA_LONG_COLUMNS)

    registry = C.seed_registry().iloc[[0]].copy()  # smallcap_liq50
    new_row = dict(series_id="test_exits", active=True, source="TEST",
                   category="macro", metric="public_market_exits", scope="all",
                   aggregation="mean", direction=1, normalization="zscore",
                   norm_window="expanding", weight=2.0, label="TEST exits")
    registry = pd.concat([registry, pd.DataFrame([new_row])], ignore_index=True)

    composite, meta = CC.compute_composite(data_long, registry)
    ids = {m["series_id"] for m in meta}
    assert "test_exits" in ids, "new TEST series did not flow into the composite"
    assert "test_exits" in composite.columns
    assert np.isfinite(composite["composite_score"].iloc[-1])


def _run_plain():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  PASS {fn.__name__}")
    print(f"\n{passed}/{len(fns)} tests passed.")


if __name__ == "__main__":
    _run_plain()
