"""FDA Time Machine: as-of and timeline endpoints and the Tiger loader, with the database mocked."""
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock

import psycopg

from dashboard.fda_history import FdaHistory, group_asof, parse_date, status_changes
from dashboard.proof import ProofService
from dashboard.repository import ResearchRepository
from dashboard.server import handler
from dashboard.tiger import TigerMonitor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import load_tiger  # noqa: E402

ENV = {"TIGER_DATABASE_URL": "postgresql://reader:very-private-secret@db/tsdb"}


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


ASOF_ROWS = [
    dict(drug="Midazolam Injection", snapshot_ts=utc(2026, 9, 23, 5, 45), manufacturer="Hikma",
         status="Currently in Shortage", source_url="https://web.archive.org/web/20260923054500/x"),
    dict(drug="Midazolam Injection", snapshot_ts=utc(2026, 9, 23, 5, 45), manufacturer="Fresenius",
         status="Currently in Shortage", source_url="https://web.archive.org/web/20260923054500/x"),
    dict(drug="Old Drug", snapshot_ts=utc(2015, 3, 1), manufacturer="Pfizer", status="Resolved", source_url=None),
]
RANGE_ROW = [dict(first=utc(2014, 7, 14), last=utc(2026, 9, 23, 5, 45), drugs=2)]


def fake_connect(results, calls=None):
    """A psycopg.connect stand-in whose execute() returns the given result lists in order."""
    def connect(dsn, **kwargs):
        if calls is not None:
            calls.append(kwargs)
        conn = MagicMock()
        conn.__enter__.return_value = conn
        queue = [[]] + list(results)  # first execute() is SET LOCAL statement_timeout
        executed = []
        def execute(sql, params=None):
            executed.append((sql, params))
            cursor = MagicMock()
            cursor.fetchall.return_value = queue.pop(0)
            return cursor
        conn.execute.side_effect = execute
        conn.executed = executed
        connect.last = conn
        return conn
    return connect


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FdaHistoryTests(unittest.TestCase):
    def test_date_must_be_iso_and_in_range(self):
        self.assertEqual(parse_date("2026-10-04").isoformat(), "2026-10-04")
        for bad in ("", "2026-1-4", "04/10/2026", "2026-13-01", "1890-01-01", "2026-10-04; DROP"):
            with self.assertRaises(ValueError):
                parse_date(bad)

    def test_rows_group_into_one_record_per_drug_newest_first(self):
        drugs = group_asof(ASOF_ROWS)
        self.assertEqual([d["drug"] for d in drugs], ["Midazolam Injection", "Old Drug"])
        self.assertEqual(drugs[0]["manufacturers"], ["Hikma", "Fresenius"])
        self.assertEqual(drugs[0]["snapshot_ts"], "2026-09-23T05:45:00+00:00")

    def test_asof_uses_an_inclusive_utc_day_and_a_read_only_session(self):
        connect = fake_connect([RANGE_ROW, ASOF_ROWS])
        result = FdaHistory(environ=ENV, connect=connect).asof("2026-10-04")
        self.assertEqual(result["state"], "connected")
        self.assertTrue(connect.last.read_only)
        sql, params = connect.last.executed[2]
        self.assertIn("snapshot_ts < %s", sql)
        self.assertEqual(params, (utc(2026, 10, 5),))  # everything archived on Oct 4 counts
        self.assertEqual(result["counts"], {"Currently in Shortage": 1, "Resolved": 1})
        self.assertEqual(result["latest_snapshot_ts"], "2026-09-23T05:45:00+00:00")
        self.assertFalse(result["before_first_snapshot"])
        json.dumps(result, allow_nan=False)

    def test_date_before_the_archive_is_flagged(self):
        result = FdaHistory(environ=ENV, connect=fake_connect([RANGE_ROW, []])).asof("2014-07-01")
        self.assertTrue(result["before_first_snapshot"])
        self.assertEqual(result["drugs"], [])

    def test_timeline_keeps_only_status_changes(self):
        rows = [dict(snapshot_ts=utc(2024, 1, 1), status="Currently in Shortage", manufacturers=3, source_url="a"),
                dict(snapshot_ts=utc(2024, 2, 1), status="Currently in Shortage", manufacturers=4, source_url="b"),
                dict(snapshot_ts=utc(2024, 6, 1), status="Resolved", manufacturers=2, source_url="c")]
        changes = status_changes(rows)
        self.assertEqual([(c["status"], c["from_status"]) for c in changes],
                         [("Currently in Shortage", None), ("Resolved", "Currently in Shortage")])
        result = FdaHistory(environ=ENV, connect=fake_connect([rows])).timeline("Midazolam Injection")
        self.assertEqual((result["snapshots"], len(result["changes"])), (3, 2))

    def test_same_day_captures_of_different_fda_tabs_are_merged_not_flip_flopped(self):
        rows = [dict(snapshot_ts=utc(2021, 3, 18, 1), status="Discontinuation", manufacturers=1, source_url="a"),
                dict(snapshot_ts=utc(2021, 3, 18, 2), status="Currently in Shortage", manufacturers=4, source_url="b"),
                dict(snapshot_ts=utc(2021, 3, 18, 3), status="Discontinuation", manufacturers=1, source_url="c"),
                dict(snapshot_ts=utc(2021, 5, 7), status="Currently in Shortage", manufacturers=4, source_url="d")]
        changes = status_changes(rows)
        self.assertEqual([c["status"] for c in changes],
                         ["Currently in Shortage + Discontinuation", "Currently in Shortage"])
        self.assertEqual(changes[0]["manufacturers"], 4)

    def test_not_configured_does_not_crash(self):
        result = FdaHistory(environ={}).asof("2026-10-04")
        self.assertEqual(result["state"], "not_configured")
        self.assertEqual(result["drugs"], [])

    def test_unreachable_database_returns_a_message_without_secrets(self):
        def down(dsn, **kwargs):
            raise psycopg.OperationalError(f"connection to {dsn} failed")
        for call in (lambda f: f.asof("2026-10-04"), lambda f: f.timeline("Midazolam Injection")):
            result = call(FdaHistory(environ=ENV, connect=down))
            self.assertEqual(result["state"], "error")
            self.assertIn("unreachable", result["message"])
            self.assertNotIn("very-private-secret", json.dumps(result))

    def test_missing_table_asks_for_the_loader(self):
        def missing(dsn, **kwargs):
            raise psycopg.errors.UndefinedTable("fda_snapshots")
        result = FdaHistory(environ=ENV, connect=missing).asof("2026-10-04")
        self.assertEqual(result["state"], "schema_missing")
        self.assertIn("load_tiger.py", result["message"])

    def test_results_are_cached_but_outages_are_not(self):
        calls, clock = [], Clock()
        service = FdaHistory(environ=ENV, connect=fake_connect([RANGE_ROW, ASOF_ROWS], calls), clock=clock)
        service.asof("2026-10-04"); service.asof("2026-10-04")
        self.assertEqual(len(calls), 1)
        attempts = []
        def down(dsn, **kwargs):
            attempts.append(1)
            raise psycopg.OperationalError("down")
        flaky = FdaHistory(environ=ENV, connect=down)
        flaky.asof("2026-10-04"); flaky.asof("2026-10-04")
        self.assertEqual(len(attempts), 2)

    def test_server_routes_answer_and_reject_bad_dates_without_crashing(self):
        fda = FdaHistory(environ=ENV, connect=fake_connect([RANGE_ROW, ASOF_ROWS]))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(ResearchRepository(ROOT), TigerMonitor(),
                                                               ProofService(ROOT), fda=fda))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            good = json.load(urllib.request.urlopen(f"{base}/api/fda/asof?date=2026-10-04"))
            with self.assertRaises(urllib.error.HTTPError) as bad:
                urllib.request.urlopen(f"{base}/api/fda/asof?date=yesterday")
            page = urllib.request.urlopen(f"{base}/time-machine.html").read().decode()
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(good["state"], "connected")
        self.assertEqual(bad.exception.code, 404)
        self.assertIn("error", json.loads(bad.exception.read()))
        self.assertIn("FDA Time Machine", page)


class LoaderTests(unittest.TestCase):
    def test_rows_dedupe_per_manufacturer_and_keep_one_name_per_drug(self):
        index = load_tiger.archive_index([dict(timestamp="20260923054500",
                                               original="https://x/d.cfm?AI=Midazolam+Injection")])
        supplier = lambda ts, name, company, status="Currently in Shortage": dict(
            capture_ts=ts, ai_key="midazolam injection", page_product=f"| Back to Previous Screen {name}",
            company=company, page_status=status)
        rows = load_tiger.build_rows([supplier("20200101000000", "MIDAZOLAM injection", "Hikma", "Resolved"),
                                      supplier("20260923054500", "Midazolam Injection", "Hikma"),
                                      supplier("20260923054500", "Midazolam Injection", "Hikma"),
                                      supplier("20260923054500", "Midazolam Injection", "")], index)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r[1] for r in rows}, {"Midazolam Injection"})  # latest display name for all
        self.assertEqual(rows[0][0], utc(2020, 1, 1))
        self.assertIsNone(rows[0][4])
        self.assertTrue(rows[1][4].startswith("https://web.archive.org/web/20260923054500/"))

    def test_load_creates_hypertable_and_bulk_copies(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.rowcount = 1
        conn.execute.return_value.fetchone.return_value = (1, 1, utc(2026, 9, 23), utc(2026, 9, 23))
        load_tiger.load(conn, [(utc(2026, 9, 23), "Midazolam Injection", "Hikma", "Currently in Shortage", None)])
        sql = " ".join(str(c.args[0]) for c in conn.execute.call_args_list)
        self.assertIn("CREATE TABLE IF NOT EXISTS backfill_live.fda_snapshots", sql)
        self.assertIn("create_hypertable('backfill_live.fda_snapshots', by_range('snapshot_ts')", sql)
        cursor.copy.assert_called_once()
        self.assertIn("ON CONFLICT DO NOTHING", cursor.execute.call_args.args[0])
        conn.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
