"""Build the trading signals: FDA shortage events and point-in-time supplier evidence.

  python src/signals.py              # rebuild from archived pages if present, else use committed tables
  python src/signals.py --tables-only

Steps (each is its own script, see its docstring):
  03_parse_main.py      weekly FDA list pages      -> data/processed/shortage_events.csv
  03b_parse_fda_csv.py  archived FDA CSV exports   -> data/processed/fda_csv_rows.csv
  04_parse_details.py   per-drug supplier pages    -> data/processed/suppliers.csv
  05_events.py          events + suppliers + owners -> data/processed/backfill/primary/{events,attrition}.csv
Holdout-dated pages are skipped by every step unless the frozen final run asks for them.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script, *args):
    print(f"$ python {script} {' '.join(args)}".rstrip(), flush=True)
    subprocess.run([sys.executable, str(ROOT / script), *args], cwd=ROOT, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tables-only", action="store_true", help="skip page parsing; use the committed tables")
    args = ap.parse_args()
    raw = ROOT / "data" / "raw"
    if not args.tables_only and any((raw / "main").rglob("*.html")):
        run("src/03_parse_main.py")
        if any((raw / "csv").glob("*.csv")):
            run("src/03b_parse_fda_csv.py")
        run("src/04_parse_details.py")
    else:
        print("No archived pages in data/raw/ (or --tables-only): using the committed data/processed tables.")
    run("src/05_events.py")


if __name__ == "__main__":
    main()
