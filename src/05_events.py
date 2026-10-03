"""Prepare the evidence ledger only; no price loading and no performance evaluation."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backfill.guardrails import require_oos_freeze
from backfill.pipeline import VARIANTS, prepare


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events-source", type=Path, default=ROOT / "data/processed/shortage_events.csv")
    ap.add_argument("--suppliers-source", type=Path, default=ROOT / "data/processed/suppliers.csv")
    ap.add_argument("--mapping", type=Path, default=ROOT / "data/company_ticker_map.csv")
    ap.add_argument("--status-source", type=Path, default=ROOT / "data/processed/main_status.csv")
    ap.add_argument("--variant", choices=VARIANTS, default="primary")
    ap.add_argument("--output", type=Path)
    ap.add_argument("--oos-stage", action="store_true", help="frozen signal-data stage only; does not evaluate")
    args = ap.parse_args()
    if args.oos_stage:
        require_oos_freeze(ROOT)
    output = args.output or ROOT / ("data/raw/oos/signals" if args.oos_stage else "data/processed/backfill") / args.variant
    prepare(args.events_source, args.suppliers_source, args.mapping, output,
            variant=args.variant, final=args.oos_stage, status_path=args.status_source)
    print(f"Evidence ledger and attrition saved to {output}; no prices or returns loaded.")


if __name__ == "__main__":
    main()
