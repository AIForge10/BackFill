"""Tiger panel polish: closed-market note, archived FDA notices, ingest status. Database mocked."""
import os
import types
import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from dashboard import tiger
from dashboard.collect_fda_notices import archive_index, company_availability, notices
from dashboard.ingest import validate
from dashboard.market_hours import closure, eastern_label, holidays, last_session_close, market_context

FRI_CLOSE = datetime(2026, 10, 2, 20, 0, tzinfo=timezone.utc)  # Fri Oct 2, 4:00 PM ET


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class MarketHoursTests(unittest.TestCase):
    def test_2026_nyse_holidays(self):
        self.assertEqual(sorted(holidays(2026)), [
            date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25),
            date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25)])
        self.assertNotIn(date(2021, 12, 31), holidays(2021))  # Saturday New Year is not observed on Friday
        self.assertEqual(closure(date(2026, 10, 3)), "weekend")
        self.assertEqual(closure(date(2026, 11, 26)), "Thanksgiving Day")
        self.assertIsNone(closure(date(2026, 10, 5)))

    def test_label_uses_the_real_timestamp_in_eastern_time(self):
        self.assertEqual(eastern_label(FRI_CLOSE), "Fri Oct 2, 4:00 PM ET")

    def test_weekend_with_the_last_close_shows_the_note(self):
        context = market_context(utc(2026, 10, 4, 10, 0), FRI_CLOSE)
        self.assertEqual(context["note"], "Markets closed - showing last close (Fri Oct 2, 4:00 PM ET)")
        self.assertEqual(context["closure"], "weekend")

    def test_holiday_with_the_last_close_shows_the_note(self):
        wed_close = utc(2026, 11, 25, 21, 0)  # Wed Nov 25, 4:00 PM EST
        context = market_context(utc(2026, 11, 26, 18, 0), wed_close)
        self.assertEqual(context["closure"], "Thanksgiving Day")
        self.assertEqual(context["note"], "Markets closed - showing last close (Wed Nov 25, 4:00 PM ET)")

    def test_stale_on_a_trading_day_keeps_the_normal_warning(self):
        self.assertIsNone(market_context(utc(2026, 10, 5, 15, 0), FRI_CLOSE)["note"])  # Monday, market open
        self.assertIsNone(market_context(utc(2026, 10, 5, 12, 0), FRI_CLOSE)["note"])  # Monday, before the open

    def test_weekend_but_data_older_than_the_last_close_is_not_explained_away(self):
        thursday = utc(2026, 10, 1, 20, 0)
        context = market_context(utc(2026, 10, 4, 10, 0), thursday)
        self.assertIsNone(context["note"])
        self.assertFalse(context["has_last_close"])
        self.assertIsNone(market_context(utc(2026, 10, 4, 10, 0), None)["note"])

    def test_last_session_close_skips_weekends_and_holidays(self):
        self.assertEqual(last_session_close(utc(2026, 10, 4, 10, 0)), FRI_CLOSE)
        self.assertEqual(last_session_close(utc(2026, 11, 27, 14, 0)).date(), date(2026, 11, 25))


def supplier(ts, ai, company, availability="available", allocation="False", status="Currently in Shortage"):
    return dict(capture_ts=ts, ai_key=ai, page_product=f"| Back to Previous Screen {ai.title()}", company=company,
                availability=availability, on_allocation=allocation, page_status=status)


class CollectorTests(unittest.TestCase):
    def test_archive_links_match_the_drug_even_when_pages_share_a_second(self):
        base = "https://www.accessdata.fda.gov/scripts/drugshortages/dsp_ActiveIngredientDetails.cfm"
        index = archive_index([dict(timestamp="20260923054500", original=f"{base}?AI=Midazolam+Injection&st=c"),
                               dict(timestamp="20260923054500", original=f"{base}?AI=Sodium+Acetate+Injection&st=c"),
                               dict(timestamp="20260923054500", original=f"{base}?AI=Dextrose+10per+Injection")])
        rows, skipped = notices([supplier("20260923054500", "midazolam injection", "A"),
                                 supplier("20260923054500", "sodium acetate injection", "B"),
                                 supplier("20260923054500", "dextrose 10% injection", "C")], index)
        self.assertEqual(skipped, 0)
        for row in rows:
            self.assertIn("AI=" + row["product"].replace(" ", "+").replace("%", "per"), row["source_url"])
            self.assertTrue(row["source_url"].startswith("https://web.archive.org/web/20260923054500/"))

    def test_newest_snapshot_per_drug_one_row_per_supplier_with_status_and_time(self):
        url = "https://x/dsp.cfm?AI=Midazolam+Injection"
        index = archive_index([dict(timestamp=t, original=url) for t in ("20260901000000", "20260923054500")])
        rows, _ = notices([supplier("20260901000000", "midazolam injection", "Old Co"),
                           supplier("20260923054500", "midazolam injection", "Hikma"),
                           supplier("20260923054500", "midazolam injection", "Hikma", "disrupted"),
                           supplier("20260923054500", "midazolam injection", "Fresenius", "discontinued")], index)
        self.assertEqual({r["company"] for r in rows}, {"Hikma", "Fresenius"})
        self.assertTrue(all(r["observed_at"] == "2026-09-23T05:45:00+00:00" for r in rows))
        self.assertTrue(all(r["status"] == "Currently in Shortage" and r["source"] == "fda_archive" for r in rows))
        self.assertEqual(rows[0]["product"], "Midazolam Injection")
        for row in rows:
            validate("supplier_updates", row)

    def test_missing_archive_url_is_skipped_never_invented(self):
        rows, skipped = notices([supplier("20260923054500", "unknown drug", "X")], {})
        self.assertEqual((rows, skipped), ([], 1))

    def test_availability_collapses_to_schema_classes(self):
        self.assertEqual(company_availability([dict(availability="available", on_allocation="True")]), "allocation")
        self.assertEqual(company_availability([dict(availability="available", on_allocation="False")]), "available")
        self.assertEqual(company_availability([dict(availability="unknown", on_allocation="False")]), "unknown")
        self.assertEqual(company_availability([dict(availability="available", on_allocation="False"),
                                               dict(availability="discontinued", on_allocation="False")]), "disrupted")


class IngestStatusTests(unittest.TestCase):
    def test_status_is_stored_and_optional(self):
        row = dict(observed_at="2026-09-23T05:45:00+00:00", event_key="k", product="p", company="c",
                   availability="available", source="fda_archive", source_url="https://web.archive.org/web/1/x")
        self.assertIsNone(validate("supplier_updates", row)[-1])
        self.assertEqual(validate("supplier_updates", dict(row, status="Resolved"))[-1], "Resolved")
        with self.assertRaises(ValueError):
            validate("supplier_updates", dict(row, status="x" * 101))


def mocked_driver(execute_results, errors=None):
    connection = MagicMock()
    connection.execute.side_effect = execute_results
    connection.__enter__.return_value = connection
    driver = types.ModuleType("psycopg")
    driver.connect = MagicMock(return_value=connection)
    driver.errors = errors or types.SimpleNamespace(UndefinedTable=type("UndefinedTable", (Exception,), {}))
    rows = types.ModuleType("psycopg.rows")
    rows.dict_row = object()
    return connection, {"psycopg": driver, "psycopg.rows": rows}


class TigerReadTests(unittest.TestCase):
    def test_snapshot_returns_grouped_notices_and_the_closed_market_note(self):
        quote = dict(time=FRI_CLOSE, received_at=FRI_CLOSE, ticker="ICUI", price=159.38, previous_close=157.18,
                     volume=1, source="webull_daily_close")
        notice = dict(observed_at=utc(2026, 9, 23, 5, 45), event_key="midazolam", received_at=FRI_CLOSE,
                      product="Midazolam Hydrochloride Injection", status="Currently in Shortage",
                      source="fda_archive", source_url="https://web.archive.org/web/20260923054500/x",
                      suppliers=[dict(company="Hikma", availability="available", ticker=None)])
        connection, modules = mocked_driver([MagicMock(), MagicMock(fetchall=lambda: [quote]),
                                             MagicMock(fetchall=lambda: [notice])])
        with patch.dict("sys.modules", modules), patch.object(tiger, "_utcnow", lambda: utc(2026, 10, 4, 10, 0)), \
                patch.dict(os.environ, {"TIGER_DATABASE_URL": "postgresql://reader@db/test"}):
            result = tiger.TigerMonitor().snapshot()
        self.assertTrue(connection.read_only)
        self.assertEqual(result["market"]["note"], "Markets closed - showing last close (Fri Oct 2, 4:00 PM ET)")
        self.assertEqual(result["events"][0]["suppliers"][0]["company"], "Hikma")
        self.assertEqual(result["events"][0]["observed_at"], "2026-09-23T05:45:00+00:00")
        sql, params = connection.execute.call_args_list[2].args
        self.assertIn("GROUP BY observed_at, event_key", sql)
        self.assertIn("ORDER BY observed_at DESC", sql)
        self.assertEqual(params, (10,))

    def test_missing_status_column_asks_for_the_schema_rerun(self):
        undefined_column = type("UndefinedColumn", (Exception,), {})
        errors = types.SimpleNamespace(UndefinedTable=type("UndefinedTable", (Exception,), {}),
                                       UndefinedColumn=undefined_column)
        _, modules = mocked_driver([MagicMock(), MagicMock(fetchall=lambda: []), undefined_column("status")], errors)
        with patch.dict("sys.modules", modules), patch.dict(os.environ, {"TIGER_DATABASE_URL": "postgresql://r@db/t"}):
            result = tiger.TigerMonitor().snapshot()
        self.assertEqual(result["state"], "schema_missing")
        self.assertIn("schema.sql", result["message"])


if __name__ == "__main__":
    unittest.main()


class EvidenceArchiveLinkTests(unittest.TestCase):
    def test_every_evidence_link_opens_its_own_drug_page(self):
        from pathlib import Path
        from urllib.parse import parse_qs, urlsplit
        from dashboard.archive import drug_key
        from dashboard.repository import ResearchRepository, rows
        repo = ResearchRepository(Path(__file__).resolve().parents[1])
        data = rows(repo.frozen / "all_candidates.csv")
        self.assertTrue(data)
        for row in data:
            url = repo.archive_url(row)
            self.assertIsNotNone(url, row["ai_key"])
            drug = parse_qs(urlsplit(url.split("/", 5)[5]).query)["AI"][0]
            self.assertEqual(drug_key(drug), drug_key(row["ai_key"]), url)

    def test_unknown_capture_gets_no_link_rather_than_a_neighbouring_page(self):
        from dashboard.archive import archive_index, wayback_url
        index = archive_index([dict(timestamp="20260923054500", original="https://x/d.cfm?AI=Midazolam+Injection")])
        self.assertIsNone(wayback_url(index, "20260923054500", "sodium acetate injection"))
        self.assertTrue(wayback_url(index, "20260923054500", "midazolam injection").endswith("AI=Midazolam+Injection"))
