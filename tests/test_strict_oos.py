import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
spec = importlib.util.spec_from_file_location("strict_oos", ROOT / "research/strict_oos.py")
oos = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oos)


class HoldoutSpecifications(unittest.TestCase):
    def test_omission_preserves_original_allocations(self):
        frame = pd.DataFrame(dict(event_id=[1, 1, 2], ticker=["AMRX", "BAX", "PFE"],
                                  benchmark=["SPY"] * 3))
        result = oos.requests(frame, oos.Settings())
        without = result[~result.ticker.eq("AMRX")]
        self.assertAlmostEqual(float(without[without.ticker.eq("BAX")].weight.iloc[0]), .025)
        self.assertAlmostEqual(float(without[without.ticker.eq("PFE")].weight.iloc[0]), .05)

    def test_primary_retained_and_timing_pairs_fixed(self):
        self.assertEqual(oos.SPECS[0], ("registered_primary", 0, 60, False))
        self.assertEqual([(delay, hold, omit) for _, delay, hold, omit in oos.SPECS[1:]],
                         [(20, 5, False), (20, 5, True), (0, 250, False), (0, 250, True)])


if __name__ == "__main__":
    unittest.main()
