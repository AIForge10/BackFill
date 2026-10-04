"""Reproduce the note's in-sample results with one command.

  python run_all.py            # signals -> prices (only if the cache is missing) -> backtest -> summary
  python run_all.py --final    # the single out-of-sample run (needs a clean freeze-oos tag; see docs/BACKFILL.md)

Any arguments are passed straight to the backtest pipeline (e.g. --prepare-only, --variant hold120),
exactly as before. Price acquisition is the only step that uses the network; the backtest is offline.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backfill.pipeline import main as pipeline  # noqa: E402


def step(title, *args):
    print(f"\n== {title} ==", flush=True)
    subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, check=True)


def reproduce():
    step("1/4 signals: FDA shortage events and supplier evidence", ROOT / "src/signals.py")
    if not (ROOT / "data/raw/prices/is/manifest.json").exists():
        step("2/4 prices: first run, fetching daily prices (Webull for US, yfinance otherwise)",
             ROOT / "data/download.py", "prices")
    else:
        print("\n== 2/4 prices: using the validated cache in data/raw/prices/is ==")
    print("\n== 3/4 backtest: registered primary, in-sample, winners + controls, costs x1 and x2 ==", flush=True)
    pipeline([])
    step("4/4 summary", ROOT / "src/analysis.py")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        pipeline()
    else:
        reproduce()
