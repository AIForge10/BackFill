"""Research audit endpoints with Snowflake mocked: labels, sorting, caching, file fallback, no secrets."""
import json
import sys
import threading
import types
import unittest
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

from dashboard.audit import REGISTERED, AuditService
from dashboard.proof import ProofService
from dashboard.repository import ResearchRepository
from dashboard.server import handler
from dashboard.tiger import TigerMonitor

ROOT = Path(__file__).resolve().parents[1]
ENV = {f"SNOWFLAKE_{k}": v for k, v in dict(ACCOUNT="acct", USER="user", PASSWORD="s3cret-pw", ROLE="r",
                                             WAREHOUSE="w", DATABASE="backfill", SCHEMA="research").items()}
RUNS = [dict(SPEC_NAME="primary", SOURCE="rerun", POSITIONS=19, SHARPE=-0.58, SHARPE_COSTS_X2=-0.61,
             TOTAL_RETURN=-0.056, ANNUALIZED_RETURN=-0.0056, MAX_DRAWDOWN=-0.066, WINNER_P=0.16,
             WINNER_MINUS_PLACEBO_P=0.12),
        dict(SPEC_NAME="final_candidate/reference_mix", SOURCE="committed", POSITIONS=8, SHARPE=0.53,
             SHARPE_COSTS_X2=0.49, TOTAL_RETURN=0.011, ANNUALIZED_RETURN=0.001, MAX_DRAWDOWN=-0.002,
             WINNER_P=0.28, WINNER_MINUS_PLACEBO_P=0.21),
        dict(SPEC_NAME="hold120", SOURCE="rerun", POSITIONS=19, SHARPE=-0.15, SHARPE_COSTS_X2=-0.17,
             TOTAL_RETURN=-0.021, ANNUALIZED_RETURN=-0.002, MAX_DRAWDOWN=-0.066, WINNER_P=0.56,
             WINNER_MINUS_PLACEBO_P=0.5)]
PROOF = [dict(TAG="freeze-v1", COMMIT="9c68c89", MANIFEST_SHA256="9046c956", SIGNATURE="SIG",
              TIMESTAMP_UTC=datetime(2026, 10, 4, 8, 47, 16, tzinfo=timezone.utc),
              EXPLORER="https://explorer.solana.com/tx/SIG?cluster=devnet")]


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def fake_query(calls):
    def run(settings, statements):
        calls.append(statements)
        return [RUNS if ".RUNS" in sql else PROOF for sql in statements]
    return run


class AuditTests(unittest.TestCase):
    def test_not_configured_falls_back_to_the_summary_file(self):
        result = AuditService(ROOT, environ={}).variants()
        self.assertEqual(result["source"], "file")
        self.assertEqual(result["location"], "results/backtest_report/summary.csv")
        self.assertEqual(len(result["rows"]), 11)
        self.assertEqual((result["registered"], result["post_hoc"]), (9, 2))
        sharpes = [r["sharpe"] for r in result["rows"]]
        self.assertEqual(sharpes, sorted(sharpes, reverse=True))

    def test_every_registered_variant_is_labelled_and_the_rest_are_post_hoc(self):
        rows = AuditService(ROOT, environ={}).variants()["rows"]
        for row in rows:
            expected = "registered" if row["spec"] in REGISTERED else "chosen after seeing results"
            self.assertEqual(row["label"], expected, row["spec"])
        self.assertEqual({r["spec"] for r in rows if r["label"] == "registered"}, set(REGISTERED))

    def test_snowflake_rows_are_sorted_labelled_and_read_from_the_configured_tables(self):
        calls = []
        result = AuditService(ROOT, run_query=fake_query(calls), environ=ENV).variants()
        self.assertEqual(result["source"], "snowflake")
        self.assertEqual(result["location"], "BACKFILL.RESEARCH.RUNS")
        self.assertEqual([r["spec"] for r in result["rows"]], ["final_candidate/reference_mix", "hold120", "primary"])
        self.assertEqual(result["rows"][0]["label"], "chosen after seeing results")
        self.assertIn("FROM BACKFILL.RESEARCH.RUNS", calls[0][0])

    def test_freeze_reads_the_clone_and_links_the_proof_row(self):
        calls = []
        result = AuditService(ROOT, run_query=fake_query(calls), environ=ENV).freeze()
        self.assertEqual(result["snapshot"], "BACKFILL_FREEZE_V1")
        self.assertIn("FROM BACKFILL_FREEZE_V1.RESEARCH.RUNS", calls[0][0])
        self.assertIn("FROM BACKFILL_FREEZE_V1.RESEARCH.PROOF", calls[0][1])
        self.assertEqual(result["proof"]["manifest_sha256"], "9046c956")
        self.assertEqual(result["proof"]["timestamp_utc"], "2026-10-04T08:47:16+00:00")
        json.dumps(result, allow_nan=False)

    def test_freeze_fallback_uses_the_saved_receipt(self):
        result = AuditService(ROOT, environ={}).freeze()
        self.assertEqual(result["source"], "file")
        self.assertIsNone(result["snapshot"])
        self.assertEqual(result["proof_source"], "proof/freeze-v1/receipt.json")
        self.assertTrue(result["proof"]["explorer"].endswith("?cluster=devnet"))

    def test_snowflake_failure_falls_back_without_exposing_the_error_or_password(self):
        def broken(settings, statements):
            raise RuntimeError(f"login failed for user with password {settings['PASSWORD']}")
        result = AuditService(ROOT, run_query=broken, environ=ENV).variants()
        self.assertEqual(result["source"], "file")
        self.assertEqual(len(result["rows"]), 11)
        self.assertNotIn("s3cret-pw", json.dumps(result))
        self.assertIn("RuntimeError", result["reason"])

    def test_results_are_cached_for_ten_minutes(self):
        calls, clock = [], Clock()
        service = AuditService(ROOT, run_query=fake_query(calls), environ=ENV, clock=clock)
        self.assertFalse(service.variants()["cached"])
        clock.now += 599
        self.assertTrue(service.variants()["cached"])
        self.assertEqual(len(calls), 1)
        clock.now += 2
        self.assertFalse(service.variants()["cached"])
        self.assertEqual(len(calls), 2)

    def test_fallback_is_cached_too_so_a_down_snowflake_is_not_retried_per_request(self):
        attempts, clock = [], Clock()
        def broken(settings, statements):
            attempts.append(1)
            raise TimeoutError
        service = AuditService(ROOT, run_query=broken, environ=ENV, clock=clock)
        service.variants(); service.variants()
        self.assertEqual(len(attempts), 1)

    def test_real_connector_path_uses_env_settings_and_closes_the_connection(self):
        cursor = MagicMock()
        cursor.execute.return_value.fetchall.return_value = RUNS
        conn = MagicMock()
        conn.cursor.return_value = cursor
        connector = types.SimpleNamespace(connect=MagicMock(return_value=conn), DictCursor=object)
        modules = {"snowflake": types.SimpleNamespace(connector=connector), "snowflake.connector": connector}
        with patch.dict(sys.modules, modules):
            result = AuditService(ROOT, environ=ENV).variants()
        self.assertEqual(result["source"], "snowflake")
        kwargs = connector.connect.call_args.kwargs
        self.assertEqual((kwargs["account"], kwargs["user"], kwargs["password"]), ("acct", "user", "s3cret-pw"))
        conn.close.assert_called_once()
        self.assertNotIn("s3cret-pw", json.dumps(result))

    def test_missing_connector_package_falls_back(self):
        with patch.dict(sys.modules, {"snowflake": None, "snowflake.connector": None}):
            result = AuditService(ROOT, environ=ENV).variants()
        self.assertEqual(result["source"], "file")
        self.assertIn("not installed", result["reason"])

    def test_unsafe_identifier_in_env_falls_back(self):
        env = dict(ENV, SNOWFLAKE_DATABASE="x; DROP DATABASE y")
        result = AuditService(ROOT, run_query=fake_query([]), environ=env).variants()
        self.assertEqual(result["source"], "file")

    def test_server_exposes_both_audit_endpoints(self):
        audit = AuditService(ROOT, run_query=fake_query([]), environ=ENV)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(ResearchRepository(ROOT), TigerMonitor(),
                                                               ProofService(ROOT), audit))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            variants = json.load(urllib.request.urlopen(f"{base}/api/audit/variants"))
            frozen = json.load(urllib.request.urlopen(f"{base}/api/audit/freeze"))
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(variants["source"], "snowflake")
        self.assertEqual(frozen["proof"]["tag"], "freeze-v1")


if __name__ == "__main__":
    unittest.main()
