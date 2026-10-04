"""Past-only entry, unchanged allocations and exact evidence-match fixtures."""
import unittest

import numpy as np
import pandas as pd

from research.final_candidate.strategy import build_requests, counterpart_audit, strict_presentations


class CandidateTests(unittest.TestCase):
    def fixture(self):
        calendar = pd.bdate_range("2020-01-01", periods=100)
        prices = {"A": pd.DataFrame({"adj_close": np.r_[np.full(60, 100.), 90., np.full(39, 500.)]}, index=calendar),
                  "B": pd.DataFrame({"adj_close": np.full(100, 200.)}, index=calendar)}
        rows = pd.DataFrame([dict(event_id=1, ticker=ticker, country="US", benchmark="SPY",
            role="winner", trade_ready_date=calendar[60], ai_key="drug", capture_ts="20200101120000") for ticker in ("A", "B")])
        return calendar, prices, rows

    def test_sma_signal_ignores_fill_and_future_closes(self):
        calendar, prices, rows = self.fixture()
        selected, _ = build_requests(rows, prices, calendar, "below_sma60_hold5")
        self.assertEqual(selected.ticker.tolist(), ["A"])
        self.assertEqual(selected.signal_date.iloc[0], calendar[60].date().isoformat())
        self.assertEqual(selected.signal_close.iloc[0], 90.)
        prices["A"].loc[calendar[61]:, "adj_close"] = .01
        again, _ = build_requests(rows, prices, calendar, "below_sma60_hold5")
        pd.testing.assert_frame_equal(selected, again)

    def test_rejected_company_share_is_cash_not_upweighted(self):
        calendar, prices, rows = self.fixture()
        selected, _ = build_requests(rows, prices, calendar, "below_sma60_hold5")
        self.assertEqual(selected.weight.tolist(), [.025])

    def test_twenty_additional_sessions_not_calendar_days(self):
        calendar, prices, rows = self.fixture()
        selected, _ = build_requests(rows, prices, calendar, "delay20_hold5")
        first = calendar.searchsorted(rows.trade_ready_date.iloc[0], side="right")
        fill = calendar[calendar.searchsorted(pd.Timestamp(selected.trade_ready_date.iloc[0]), side="right")]
        self.assertEqual(fill, calendar[first + 20])

    def test_disrupted_counterpart_requires_other_owner_and_exact_capture(self):
        _, _, rows = self.fixture()
        ledger = rows.copy()
        ledger["role"] = "disrupted"
        ledger.loc[ledger.ticker == "B", "capture_ts"] = "20200102120000"
        audited = counterpart_audit(rows.iloc[:1], ledger)
        self.assertFalse(audited.exact_capture_listed_disrupted.iloc[0])
        ledger.loc[ledger.ticker == "B", "capture_ts"] = rows.capture_ts.iloc[0]
        self.assertTrue(counterpart_audit(rows.iloc[:1], ledger).exact_capture_listed_disrupted.iloc[0])

    def test_all_presentations_reject_mixed_disruption_allocation_and_blank(self):
        available = dict(presentation="10mg injection", availability="available", on_allocation=False)
        self.assertTrue(strict_presentations([available]))
        for bad in [dict(available, availability="disrupted"), dict(available, on_allocation=True),
                    dict(available, presentation=" ")]:
            self.assertFalse(strict_presentations([available, bad]))
        self.assertFalse(strict_presentations([]))


if __name__ == "__main__":
    unittest.main()
