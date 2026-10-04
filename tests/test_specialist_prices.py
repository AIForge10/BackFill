"""Webull specialist prices: indexing, caching, failure handling and the endpoint. Webull mocked."""
import json
import threading
import time
import unittest
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path

from dashboard import specialist_prices as sp
from dashboard.proof import ProofService
from dashboard.repository import ResearchRepository
from dashboard.server import handler
from dashboard.tiger import TigerMonitor

ROOT = Path(__file__).resolve().parents[1]
RAW = {"AMPH": [("2026-09-01", 20.0), ("2026-10-02", 25.0)], "AMRX": [("2026-09-01", 10.0), ("2026-10-02", 9.0)],
       "ANIP": [("2026-09-01", 70.0), ("2026-10-02", 72.1)], "ICUI": [("2026-09-01", 160.0), ("2026-10-02", 159.38)]}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class SpecialistPriceTests(unittest.TestCase):
    def test_series_are_indexed_to_100_at_the_first_session(self):
        series = sp.to_series(RAW)
        self.assertEqual([s["ticker"] for s in series], ["AMPH", "AMRX", "ANIP", "ICUI"])
        amph = series[0]
        self.assertEqual(amph["points"][0]["index"], 100.0)
        self.assertEqual(amph["points"][-1]["index"], 125.0)
        self.assertAlmostEqual(amph["change"], 0.25)
        self.assertEqual(amph["last_date"], "2026-10-02")

    def test_requests_the_four_specialists_over_about_30_sessions(self):
        calls = []
        def fetch(tickers, start, end):
            calls.append((tickers, start, end))
            return RAW
        result = sp.SpecialistPrices(fetch=fetch, today=lambda: date(2026, 10, 4)).snapshot()
        self.assertEqual(result["state"], "ok")
        self.assertEqual(calls[0], (("AMPH", "AMRX", "ANIP", "ICUI"), "2026-08-20", "2026-10-05"))
        json.dumps(result, allow_nan=False)

    def test_success_is_cached_for_an_hour(self):
        calls, clock = [], Clock()
        prices = sp.SpecialistPrices(fetch=lambda *a: calls.append(1) or RAW, clock=clock)
        prices.snapshot()
        clock.now += 3599
        self.assertTrue(prices.snapshot()["cached"])
        self.assertEqual(len(calls), 1)
        clock.now += 2
        self.assertFalse(prices.snapshot()["cached"])
        self.assertEqual(len(calls), 2)

    def test_failure_is_unavailable_without_details_and_retried_after_5_minutes(self):
        calls, clock = [], Clock()
        def broken(*args):
            calls.append(1)
            raise RuntimeError("401 app_key=very-secret-key endpoint api.sandbox.webull.com")
        prices = sp.SpecialistPrices(fetch=broken, clock=clock)
        result = prices.snapshot()
        self.assertEqual(result["state"], "unavailable")
        self.assertNotIn("very-secret-key", json.dumps(result))
        self.assertNotIn("sandbox", json.dumps(result))
        clock.now += 299
        prices.snapshot()
        self.assertEqual(len(calls), 1)
        clock.now += 2
        prices.snapshot()
        self.assertEqual(len(calls), 2)

    def test_partial_data_keeps_the_rest_and_lists_what_is_missing(self):
        result = sp.SpecialistPrices(fetch=lambda *a: {"AMPH": RAW["AMPH"], "ICUI": RAW["ICUI"]}).snapshot()
        self.assertEqual(result["state"], "ok")
        self.assertEqual(result["missing"], ["AMRX", "ANIP"])

    def test_empty_or_slow_webull_is_unavailable(self):
        self.assertEqual(sp.SpecialistPrices(fetch=lambda *a: {}).snapshot()["state"], "unavailable")
        original = sp.TIMEOUT_SECONDS
        sp.TIMEOUT_SECONDS = 0.05
        try:
            slow = sp.SpecialistPrices(fetch=lambda *a: time.sleep(0.5) or RAW).snapshot()
        finally:
            sp.TIMEOUT_SECONDS = original
        self.assertEqual(slow["state"], "unavailable")
        self.assertIn("in time", slow["message"])

    def test_endpoint_serves_the_cached_snapshot(self):
        prices = sp.SpecialistPrices(fetch=lambda *a: RAW)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(ResearchRepository(ROOT), TigerMonitor(),
                                                               ProofService(ROOT), prices=prices))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            data = json.load(urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/prices/specialists"))
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(data["state"], "ok")
        self.assertEqual(len(data["series"]), 4)


if __name__ == "__main__":
    unittest.main()
