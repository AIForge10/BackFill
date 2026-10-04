"""Quote collector: CSV rows match the ingest contract; no future timestamps. No network."""
import unittest
from datetime import date, timedelta

import pandas as pd

from dashboard.collect_quotes import quote_rows
from dashboard.ingest import validate


class CollectQuotesTest(unittest.TestCase):
    def test_rows_carry_previous_close_and_pass_ingest_validation(self):
        bars = pd.DataFrame(dict(date=pd.to_datetime(["2026-09-30", "2026-10-01", "2026-10-02"]),
                                 close=[10.0, 11.0, 12.5], volume=[100, 200, 300]))
        rows = quote_rows("ICUI", bars, today=date(2026, 10, 4))
        self.assertEqual([r["previous_close"] for r in rows], ["", "10.0000", "11.0000"])
        self.assertEqual(rows[-1]["time"], "2026-10-02T16:00:00-04:00")
        for row in rows:
            validate("quotes", {k: str(v) for k, v in row.items()})

    def test_session_not_yet_closed_is_skipped(self):
        tomorrow = date.today() + timedelta(days=1)
        bars = pd.DataFrame(dict(date=pd.to_datetime([tomorrow.isoformat()]), close=[10.0], volume=[1]))
        self.assertEqual(quote_rows("SPY", bars, today=tomorrow), [])


if __name__ == "__main__":
    unittest.main()
