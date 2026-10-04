import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from verify_timeframes import holm_with_prior, requests_for
from backfill.settings import Settings


class TimeframeScreenTests(unittest.TestCase):
    def test_prior_searches_increase_multiplicity_burden(self):
        self.assertAlmostEqual(holm_with_prior([0.001, 0.04], prior_tests=2)[0], 0.004)
        self.assertAlmostEqual(holm_with_prior([0.001, 0.04], prior_tests=2)[1], 0.12)

    def test_dated_generic_class_and_excluded_allocation_are_preserved(self):
        ledger = pd.DataFrame([
            dict(event_id=1, ticker="HSP", country="US", role="winner", product="Injection", trade_ready_date="2015-01-01", benchmark="SPY"),
            dict(event_id=1, ticker="ICUI", country="US", role="winner", product="Injection", trade_ready_date="2015-01-01", benchmark="SPY"),
            dict(event_id=2, ticker="PFE", country="US", role="winner", product="Tablets", trade_ready_date="2016-01-01", benchmark="SPY"),
        ])
        mapping = pd.DataFrame([
            dict(ticker="HSP", listed_from="2014-01-01", listed_to="2015-09-02", is_generic_maker="1"),
            dict(ticker="ICUI", listed_from="2014-01-01", listed_to="", is_generic_maker="1"),
            dict(ticker="PFE", listed_from="2014-01-01", listed_to="", is_generic_maker="0"),
        ])
        requests = requests_for(ledger, mapping, "generic_winners", 5, Settings())
        self.assertEqual(set(requests.ticker), {"HSP", "ICUI"})
        self.assertEqual(requests.loc[requests.ticker == "ICUI", "weight"].iloc[0], 0.025)
        injection = requests_for(ledger, mapping, "injectable_winners", 120, Settings())
        self.assertEqual(set(injection.ticker), {"HSP", "ICUI"})
        self.assertEqual(set(injection.hold_days), {120})


if __name__ == "__main__":
    unittest.main()
