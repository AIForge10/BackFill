"""Verify provenance, feed states and ingestion contracts without real returns or a DB."""
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from dashboard.ingest import validate
from dashboard.repository import ResearchRepository, number
from dashboard.tiger import TigerMonitor

ROOT = Path(__file__).resolve().parents[1]


class DashboardTests(unittest.TestCase):
    def test_saved_candidate_does_not_fabricate_a_basket_curve(self):
        repo = ResearchRepository(ROOT)
        candidate = repo.scenario()
        self.assertTrue(candidate["available"])
        self.assertEqual(len(candidate["lots"]), candidate["metrics"]["positions"])
        self.assertEqual(len(candidate["equity"]), candidate["metrics"]["sessions"])
        basket = repo.scenario("basket")
        self.assertEqual(basket["equity"], [])
        self.assertEqual(basket["classification"], "Exploratory · reported")
        self.assertIn("Yahoo", basket["vendor"])
        json.dumps(repo.overview(), allow_nan=False)

    def test_source_changes_do_not_keep_a_matching_integrity_label(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            frozen = base / "data/processed/final_candidate/v1"
            frozen.mkdir(parents=True)
            (base / "source.csv").write_text("changed")
            (frozen / "freeze.json").write_text(json.dumps({"frozen_files": {"source.csv": "old"}}))
            checks = ResearchRepository(base).overview()["frozen_checks"]
            self.assertEqual(checks[0]["status"], "changed")

    def test_downloads_do_not_allow_arbitrary_repository_files(self):
        repo = ResearchRepository(ROOT)
        for name in ("../../.env", "config.py", "/etc/passwd", "raw_prices.csv"):
            with self.assertRaises(KeyError):
                repo.download(name)
        self.assertEqual(repo.download("events.csv").name, "all_candidates.csv")

    def test_unavailable_vendor_combination_is_not_substituted(self):
        repo = ResearchRepository(ROOT)
        self.assertFalse(repo.scenario("basket", vendor="webull_only")["available"])
        self.assertFalse(repo.scenario("primary", costs=2)["available"])
        with self.assertRaises(ValueError):
            repo.scenario("candidate", costs=0)

    def test_filter_and_pagination_preserve_underlying_metrics(self):
        repo = ResearchRepository(ROOT)
        before = repo.scenario()["metrics"]
        selected = repo.evidence(ticker="TEVA", role="winner", limit=2)
        self.assertLessEqual(len(selected["rows"]), 2)
        self.assertTrue(all(r["ticker"] == "TEVA" and r["role"] == "winner" for r in selected["rows"]))
        self.assertEqual(repo.scenario()["metrics"], before)
        self.assertEqual(repo.evidence(query="NO SUCH DRUG 000")['total'], 0)

    def test_not_configured_does_not_claim_live_observations(self):
        with patch.dict(os.environ, {"TIGER_DATABASE_URL": ""}):
            live = TigerMonitor().snapshot()
        self.assertEqual(live["state"], "not_configured")
        self.assertEqual(live["quotes"], [])
        self.assertIsNone(live["latest_received_at"])

    def test_source_link_matches_actual_archive_index(self):
        repo = ResearchRepository(ROOT)
        lot = repo.scenario()["lots"][0]
        event = repo.event(lot["event_id"], lot["ticker"])
        self.assertIn(lot["capture_ts"], event["selected"]["archive_url"])
        self.assertEqual(event["executions"][0]["trade_date"], lot["trade_date"])

    def test_ingestion_rejects_unverifiable_or_invalid_observations(self):
        row = dict(time="2024-01-01T12:00:00Z", ticker="ICUI", price="100", source="webull")
        self.assertEqual(validate("quotes", row)[1], "ICUI")
        for bad in (dict(row, price="NaN"), dict(row, price="-1"), dict(row, source=""),
                    dict(row, time="2024-01-01"), dict(row, time="2999-01-01T00:00:00Z")):
            with self.assertRaises(ValueError):
                validate("quotes", bad)
        update = dict(observed_at="2024-01-01T12:00:00Z", event_key="one", product="drug", company="supplier",
                      ticker="ICUI", availability="available", source="fda", source_url="javascript:alert(1)")
        with self.assertRaises(ValueError):
            validate("supplier_updates", update)

    def test_missing_or_nonfinite_numbers_are_not_displayed_as_zero(self):
        for value in ("", None, "NaN", "inf", "unknown"):
            self.assertIsNone(number(value))

    def test_database_errors_never_expose_connection_secrets(self):
        driver = types.ModuleType("psycopg")
        driver.connect = MagicMock(side_effect=RuntimeError("password=very-private-secret"))
        driver.errors = types.SimpleNamespace(UndefinedTable=type("UndefinedTable", (Exception,), {}))
        factories = types.ModuleType("psycopg.rows")
        factories.dict_row = object()
        with patch.dict("sys.modules", {"psycopg": driver, "psycopg.rows": factories}), \
                patch.dict(os.environ, {"TIGER_DATABASE_URL": "postgresql://reader:very-private-secret@db/test"}):
            result = TigerMonitor().snapshot()
        self.assertEqual(result["state"], "error")
        self.assertNotIn("very-private-secret", json.dumps(result))

    def test_live_rows_have_source_and_staleness_and_use_read_only_session(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        quote = dict(time=now - timedelta(minutes=10), received_at=now, ticker="ICUI", price=100,
                     previous_close=99, volume=20, source="test vendor")
        connection = MagicMock()
        connection.execute.side_effect = [MagicMock(), MagicMock(fetchall=lambda: [quote]),
                                          MagicMock(fetchall=lambda: [])]
        connection.__enter__.return_value = connection
        driver = types.ModuleType("psycopg")
        driver.connect = MagicMock(return_value=connection)
        driver.errors = types.SimpleNamespace(UndefinedTable=type("UndefinedTable", (Exception,), {}))
        factories = types.ModuleType("psycopg.rows")
        factories.dict_row = object()
        with patch.dict("sys.modules", {"psycopg": driver, "psycopg.rows": factories}), \
                patch.dict(os.environ, {"TIGER_DATABASE_URL": "postgresql://reader@db/test"}):
            result = TigerMonitor().snapshot()
        self.assertTrue(connection.read_only)
        self.assertEqual(result["state"], "connected")
        self.assertTrue(result["quotes"][0]["stale"])
        self.assertEqual(result["quotes"][0]["source"], "test vendor")
        self.assertIsNotNone(result["latest_received_at"])

    def test_empty_database_is_connected_but_not_presented_as_a_received_signal(self):
        connection = MagicMock()
        connection.execute.return_value.fetchall.return_value = []
        connection.__enter__.return_value = connection
        driver = types.ModuleType("psycopg")
        driver.connect = MagicMock(return_value=connection)
        driver.errors = types.SimpleNamespace(UndefinedTable=type("UndefinedTable", (Exception,), {}))
        factories = types.ModuleType("psycopg.rows")
        factories.dict_row = object()
        with patch.dict("sys.modules", {"psycopg": driver, "psycopg.rows": factories}), \
                patch.dict(os.environ, {"TIGER_DATABASE_URL": "postgresql://reader@db/test"}):
            result = TigerMonitor().snapshot()
        self.assertEqual(result["state"], "empty")
        self.assertIsNone(result["latest_received_at"])


if __name__ == "__main__":
    unittest.main()
