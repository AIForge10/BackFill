"""Explicit price acquisition. All backtests subsequently run offline.

Default vendor policy: Webull OpenAPI for US stocks/ETFs (credentials from
examples/backtest/.env), yfinance for indices/FX/non-US and as a recorded fallback,
with a per-symbol Webull-vs-Yahoo cross-check in the manifest.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from backfill.guardrails import require_oos_freeze
from backfill.prices import fetch_cache


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events", type=Path, nargs="+", default=[ROOT / "data/processed/backfill/primary/events.csv"],
                    help="one or more evidence ledgers; acquire the union once for all declared variants")
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--start", default="2013-01-01")
    ap.add_argument("--exclude", action="append", default=[], metavar="TICKER=REASON",
                    help="explicitly reviewed stock-data exclusions; never automatically inferred")
    ap.add_argument("--vendor", choices=["webull", "yfinance"], default="webull",
                    help="webull (default): Webull for US listings, yfinance for the rest and as a recorded fallback")
    ap.add_argument("--oos-stage", action="store_true", help="requires clean freeze-oos; no evaluation")
    args = ap.parse_args()
    if args.oos_stage:
        require_oos_freeze(ROOT)
    exclusions = {}
    for value in args.exclude:
        ticker, sep, reason = value.partition("=")
        if not sep or not ticker.strip() or not reason.strip():
            raise ValueError("Each exclusion requires TICKER=REASON.")
        exclusions[ticker.strip()] = reason.strip()
    events = pd.concat([pd.read_csv(path) for path in args.events], ignore_index=True)
    if events.empty:
        raise ValueError("No candidates; prepare the evidence ledger first.")
    end = str((pd.Timestamp(config.OOS_END) + pd.Timedelta(days=1)).date()) if args.oos_stage else config.OOS_START
    cache = args.cache or ROOT / "data/raw/prices" / ("oos" if args.oos_stage else "is")
    fetch_cache(events, cache, start=args.start, end=end, exclusions=exclusions, vendor=args.vendor)
    print(f"Validated immutable cache saved to {cache}; no strategy evaluated.")


if __name__ == "__main__":
    main()
