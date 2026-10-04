"""Gemini trade summaries: only listed facts are sent, output is checked, and the server only reads the cache."""
import csv
import hashlib
import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

from dashboard.proof import ProofService
from dashboard.repository import ResearchRepository
from dashboard.server import handler
from dashboard.tiger import TigerMonitor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import explain_trades  # noqa: E402

FACT_KEYS = {"drug", "notice_date", "entry_date", "exit_date", "ticker", "net_return", "hedge"}


def lots():
    with explain_trades.source_path().open(newline="") as stream:
        return list(csv.DictReader(stream))


def reply(text, status=200, finish="STOP"):
    response = MagicMock(status_code=status)
    response.json.return_value = {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
                                  "modelVersion": "gemini-test-001"}
    return response


class ExplainScriptTests(unittest.TestCase):
    def test_only_listed_facts_are_extracted(self):
        row = lots()[0]
        given = explain_trades.facts(row)
        self.assertEqual(set(given), FACT_KEYS)
        self.assertEqual(given["net_return"], "-2.83%")
        self.assertEqual((given["ticker"], given["hedge"], given["entry_date"]), ("TEVA", "SPY", "2014-12-19"))

    def test_check_rejects_extra_numbers_and_wrong_length(self):
        given = explain_trades.facts(lots()[0])
        ok = "TEVA was bought on 2014-12-19 and sold on 2014-12-29 with SPY as hedge. It returned -2.83% net."
        self.assertEqual(explain_trades.check(ok, given), ok)
        with self.assertRaisesRegex(ValueError, "numbers not in the facts"):
            explain_trades.check("TEVA was held for 6 trading days. It returned -2.83% net.", given)
        with self.assertRaisesRegex(ValueError, "expected 2 sentences"):
            explain_trades.check("TEVA returned -2.83% net.", given)

    def test_truncated_reply_is_rejected(self):
        given = explain_trades.facts(lots()[0])
        session = MagicMock()
        session.post.return_value = reply("TEVA was bought on 2014-12-19. It returned -2.83% after", finish="MAX_TOKENS")
        text, _ = explain_trades.generate(session, "k", "m", given)
        with self.assertRaises(ValueError):
            explain_trades.check(text, given)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            explain_trades.check("TEVA was bought on 2014-12-19. It returned -2.83% after", given)

    def test_transient_errors_are_retried(self):
        session = MagicMock()
        session.post.side_effect = [reply("", status=503), reply("", status=429), reply("A. B.")]
        with patch.object(explain_trades.time, "sleep") as sleep:
            text, _ = explain_trades.generate(session, "k", "m", {})
        self.assertEqual(text, "A. B.")
        self.assertEqual(sleep.call_count, 2)

    def test_request_sends_only_facts_and_key_in_header(self):
        session = MagicMock()
        session.post.return_value = reply("x")
        given = explain_trades.facts(lots()[0])
        explain_trades.generate(session, "secret-key", "gemini-x", given)
        url, kwargs = session.post.call_args[0][0], session.post.call_args[1]
        self.assertNotIn("secret-key", url)
        self.assertEqual(kwargs["headers"], {"x-goog-api-key": "secret-key"})
        sent = kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertEqual(json.loads(sent.removeprefix("Facts:\n")), given)
        self.assertNotIn(lots()[0]["evidence"][:40], json.dumps(kwargs["json"]))

    def test_main_writes_cache_with_model_and_timestamp(self):
        rows = lots()
        texts = [f"{r['ticker']} was bought on {r['trade_date']} and sold on {r['exit_date']}. "
                 f"It returned {explain_trades.facts(r)['net_return']} net with a {r['hedge']} hedge." for r in rows]
        session = MagicMock()
        session.__enter__.return_value = session
        session.post.side_effect = [reply("Too many: 99 days.")] + [reply(t) for t in texts]
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(explain_trades, "OUTPUT", Path(temp) / "explanations.json"), \
                patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                patch("requests.Session", return_value=session), patch("sys.argv", ["explain_trades.py", "--pause", "0"]):
            explain_trades.main()
            cache = json.loads((Path(temp) / "explanations.json").read_text())
        self.assertEqual(cache["model"], "gemini-test-001")
        self.assertIn("T", cache["generated_at"])
        self.assertEqual(len(cache["explanations"]), len(rows))
        self.assertEqual(cache["explanations"][rows[0]["lot_id"]]["text"], texts[0])

    def test_nothing_written_when_a_trade_never_passes(self):
        session = MagicMock()
        session.__enter__.return_value = session
        session.post.return_value = reply("One sentence only.")
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(explain_trades, "OUTPUT", Path(temp) / "explanations.json"), \
                patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                patch("requests.Session", return_value=session), patch("sys.argv", ["explain_trades.py", "--pause", "0"]):
            with self.assertRaises(SystemExit):
                explain_trades.main()
            self.assertFalse((Path(temp) / "explanations.json").exists())


class ExplainEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        source = explain_trades.source_path().relative_to(ROOT)
        for name in ("results/research/final_candidate_v1_20261004/latest.json", str(source)):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, root / name)
        (root / "results/explanations.json").write_text(json.dumps(dict(
            model="gemini-test-001", generated_at="2026-10-04T11:00:00+00:00", source=str(source),
            source_sha256=hashlib.sha256((root / source).read_bytes()).hexdigest(),
            explanations={"93:TEVA:winner": dict(text="Cached text. Second sentence.", facts={})})))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler(ResearchRepository(root), TigerMonitor(),
                                                                   ProofService(root), audit=MagicMock(), fda=MagicMock()))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def test_returns_cached_text_without_calling_gemini(self):
        with patch("requests.Session") as session, patch("requests.post") as post:
            with urllib.request.urlopen(f"{self.base}/api/explain/93%3ATEVA%3Awinner") as response:
                data = json.loads(response.read())
        session.assert_not_called()
        post.assert_not_called()
        self.assertEqual(data["text"], "Cached text. Second sentence.")
        self.assertEqual(data["label"], "AI-generated summary of the facts above")
        self.assertEqual(data["model"], "gemini-test-001")
        self.assertTrue(data["current"])

    def test_unknown_trade_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{self.base}/api/explain/1:NOPE:winner")
        self.assertEqual(caught.exception.code, 404)


class FieldNameTests(unittest.TestCase):
    def test_raw_field_names_are_rejected_plain_words_pass(self):
        given = explain_trades.facts(lots()[0])
        bad = ("TEVA was bought on 2014-12-19 after a notice on 2014-10-27, hedged with SPY. "
               "It was sold on 2014-12-29 with a net_return of -2.83%.")
        with self.assertRaisesRegex(ValueError, "net_return"):
            explain_trades.check(bad, given)
        explain_trades.check(bad.replace("net_return", "net return"), given)


if __name__ == "__main__":
    unittest.main()
