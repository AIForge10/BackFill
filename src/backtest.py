"""Run the backtest offline on the cached prices (the engine never calls a vendor).

  python src/backtest.py                       # registered primary, in-sample, winners + controls, costs x1 and x2
  python src/backtest.py --variant hold120     # a pre-declared variant (see docs/BACKFILL.md)
  python src/backtest.py --leave-out PFE       # omission diagnostic

Every run is logged in results/variants_log.csv; outputs go to results/backfill/<bundle>/.
The out-of-sample run is `python run_all.py --final` (once, after the freeze-oos tag).
Implementation: backfill/pipeline.py (orchestration), backfill/engine.py (lots, fills, hedges, costs),
strategies/primary.py (signal -> position requests).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backfill.pipeline import main  # noqa: E402

if __name__ == "__main__":
    main()
