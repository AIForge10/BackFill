"""Snowflake loader: rows from the published files, the clone and count check, no secrets. Snowflake mocked."""
import contextlib
import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import load_snowflake as L  # noqa: E402

ENV = {f"SNOWFLAKE_{k}": v for k, v in dict(ACCOUNT="acct", USER="user", PASSWORD="s3cret-pw", ROLE="r",
                                             WAREHOUSE="w", DATABASE="backfill", SCHEMA="research").items()}


class LoaderTests(unittest.TestCase):
    def test_rows_match_the_published_files(self):
        self.assertEqual(len(L.runs_rows()), 11)
        self.assertEqual(len(L.manifest_rows()), 10)
        self.assertEqual(len(L.proof_rows()), 1)
        for table in L.TABLES:
            self.assertEqual(len(L.ROWS[table]()[0]), L.DDL[table].count(",") + 1, table)

    def test_trades_stack_all_four_runs_with_policy_and_costs(self):
        rows = L.trades_rows()
        self.assertEqual(len(rows), 96)
        counts = {}
        for row in rows:
            counts[(row[10], row[11])] = counts.get((row[10], row[11]), 0) + 1
        self.assertEqual(counts, {("reference_mix", 1): 32, ("reference_mix", 2): 32,
                                  ("webull_only", 1): 16, ("webull_only", 2): 16})

    def test_proof_row_comes_from_the_receipt(self):
        tag, commit, manifest_hash, signature, stamp, explorer = L.proof_rows()[0]
        self.assertEqual(tag, "freeze-v1")
        self.assertTrue(manifest_hash.startswith("9046c956"))
        self.assertTrue(explorer.endswith("?cluster=devnet"))

    def test_unsafe_identifier_is_refused(self):
        with self.assertRaises(SystemExit):
            L.ident("BACKFILL; DROP DATABASE X")

    def test_main_loads_clones_compares_and_never_prints_the_password(self):
        cursor = MagicMock()
        cursor.execute.return_value.fetchone.return_value = (5,)
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value = cursor
        connector = types.SimpleNamespace(connect=MagicMock(return_value=conn))
        modules = {"snowflake": types.SimpleNamespace(connector=connector), "snowflake.connector": connector}
        out = io.StringIO()
        with patch.dict(sys.modules, modules), patch.dict("os.environ", ENV), \
                patch("dotenv.load_dotenv"), contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as done:
            L.main()
        self.assertEqual(done.exception.code, 0)
        sql = [c.args[0] for c in cursor.execute.call_args_list]
        self.assertIn("CREATE OR REPLACE DATABASE BACKFILL_FREEZE_V1 CLONE BACKFILL", sql)
        for table in L.TABLES:
            self.assertIn(f"CREATE OR REPLACE TABLE {table}", " ".join(sql))
            self.assertIn(f"SELECT COUNT(*) FROM BACKFILL_FREEZE_V1.RESEARCH.{table}", sql)
        self.assertNotIn("s3cret-pw", out.getvalue())


if __name__ == "__main__":
    unittest.main()
