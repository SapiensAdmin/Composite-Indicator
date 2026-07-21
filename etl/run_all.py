"""
run_all.py — orchestrate the full monthly ETL.

    ensure workbook -> fetch AMFI -> compute composite -> export JSON

Designed for the GitHub Actions cron and for local runs. Idempotent: re-running
never duplicates rows and only appends newly published months. If AMFI hasn't
published the latest month yet, the fetch stage simply skips it and everything
downstream still recomputes cleanly.
"""
from __future__ import annotations

import argparse
import sys

import build_excel
import compute_composite
import export_json
import fetch_amfi


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the full AMFI liquidity-stress ETL.")
    ap.add_argument("--engine", choices=["api", "playwright"], default="api")
    ap.add_argument("--months-limit", type=int, default=None,
                    help="Limit to the N most recent months (debug/backfill control).")
    ap.add_argument("--latest-only", action="store_true",
                    help="Only fetch the single most recent published month.")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="Recompute composite + JSON from existing data_long (no network).")
    args = ap.parse_args(argv)

    print("== 1/4  ensure workbook ==")
    build_excel.ensure_workbook()

    if not args.skip_fetch:
        print("== 2/4  fetch AMFI (domain-locked) ==")
        fetch_amfi.run(engine=args.engine, months_limit=args.months_limit,
                       latest_only=args.latest_only)
    else:
        print("== 2/4  fetch skipped (--skip-fetch) ==")

    print("== 3/4  compute composite ==")
    compute_composite.run()

    print("== 4/4  export JSON ==")
    export_json.run()

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
