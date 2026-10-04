import sys
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from strict_timing import delay_requests, lot_net_pnl
from backfill.engine import Result
from backfill.settings import Settings


class StrictTimingTests(unittest.TestCase):
    def test_delay_counts_sessions_from_first_eligible_close(self):
        calendar = pd.bdate_range("2024-01-01", periods=20)
        request = pd.DataFrame([dict(trade_ready_date="2024-01-06", known_at="2024-01-06T23:59:59Z")])
        delayed = delay_requests(request, calendar, 5)
        base = calendar.searchsorted(pd.Timestamp("2024-01-06"), side="right")
        actual = calendar.searchsorted(pd.Timestamp(delayed.trade_ready_date.iloc[0]), side="right")
        self.assertEqual(actual, base + 5)
        self.assertEqual(delayed.evidence_ready_date.iloc[0], "2024-01-06")
        self.assertEqual(delayed.known_at.iloc[0], request.known_at.iloc[0])
        self.assertEqual(delay_requests(request, calendar, 0).trade_ready_date.iloc[0], "2024-01-06")
        with self.assertRaises(ValueError):
            delay_requests(request, calendar, -1)

    def test_lot_cashflow_reconciliation_includes_costs_and_lagged_carry(self):
        days = pd.bdate_range("2024-01-02", periods=3)
        settings = replace(Settings(), initial_nav=1000)
        carry = (50 + 55) * .005 / 365.25
        eq = pd.DataFrame(dict(nav=[999.75, 999.75-50*.005/365.25, 1000-.53-carry],
                               hedge_carry_cost=[0, 50*.005/365.25, 55*.005/365.25]), index=days)
        trades = pd.DataFrame([
            dict(date=days[0],lot_id="a",leg="stock",units=1.,usd_notional=100.,cost=.2),
            dict(date=days[0],lot_id="a",leg="hedge",units=-.5,usd_notional=-50.,cost=.05),
            dict(date=days[2],lot_id="a",leg="stock",units=-1.,usd_notional=-110.,cost=.22),
            dict(date=days[2],lot_id="a",leg="hedge",units=.5,usd_notional=60.,cost=.06),
        ])
        lots = pd.DataFrame([dict(lot_id="a",entry_usd=100.,hedge="SPY")])
        result = Result(eq,trades,lots,pd.DataFrame())
        net = lot_net_pnl(result,{"SPY":pd.DataFrame(dict(adj_close=[100.,110.,120.]),index=days)},settings)
        self.assertAlmostEqual(net.net_pnl.iloc[0],-.53-carry)
        self.assertAlmostEqual(net.net_lot_return.iloc[0],(-.53-carry)/100)


if __name__ == "__main__":
    unittest.main()
