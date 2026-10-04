"""Proof on Solana panel: saved receipt, live verify states and caching. No network, no wallet."""
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from dashboard.proof import ProofService, _scripts
from dashboard.repository import ResearchRepository
from dashboard.server import handler
from dashboard.tiger import TigerMonitor

ROOT = Path(__file__).resolve().parents[1]
MEMO = "backfill:freeze-v1:" + "a" * 64 + ":1234567"
MANIFEST = dict(tag="freeze-v1", commit="1234567" + "0" * 33, manifest_sha256="a" * 64,
                files=[dict(path="HYPOTHESIS.md", sha256="b" * 64, bytes=10)])
RECEIPT = dict(tag="freeze-v1", commit=MANIFEST["commit"], manifest_sha256="a" * 64, memo=MEMO,
               signature="SIG", cluster="devnet", signer="ME", timestamp_utc="2026-10-04T08:47:16+00:00",
               explorer="https://explorer.solana.com/tx/SIG?cluster=devnet")


def tx_with(memo, err=None):
    return {"meta": {"err": err, "logMessages": [
        "Program Memo4c2pN8afCj432Lb7RMVKi9PbQnnW7ewFFaV3oAH invoke [1]",
        "Program log: Memo (len 91)", f"Program log: {memo}"]}}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ProofPanelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        folder = self.root / "proof/freeze-v1"
        folder.mkdir(parents=True)
        (folder / "receipt.json").write_text(json.dumps(RECEIPT))
        (folder / "manifest.json").write_text(json.dumps(MANIFEST))
        # Recompute from a fixed manifest instead of the real git tag.
        self.build = patch.object(_scripts(), "build", return_value=MANIFEST)
        self.build.start()

    def tearDown(self):
        self.build.stop()
        self.temp.cleanup()

    def service(self, fetch, clock=None):
        return ProofService(self.root, fetch_transaction=fetch, clock=clock or Clock())

    def test_real_receipt_summary_states_the_limit_and_both_checks(self):
        self.build.stop()
        summary = ProofService(ROOT).summary()
        self.build.start()
        self.assertTrue(summary["anchored"])
        self.assertEqual(summary["statement"], "Proves the frozen rules existed at 2026-10-04 08:47 UTC. "
                                               "It does not make the 2014–2024 backtest out-of-sample.")
        self.assertEqual(summary["comparison"]["older"]["files"], 8)
        self.assertEqual(summary["comparison"]["anchored"]["files"], 10)
        self.assertEqual(len(summary["comparison"]["shared"]), 4)
        self.assertTrue(summary["receipt"]["explorer"].endswith("?cluster=devnet"))
        self.assertEqual(summary["verify_command"], "uv run python scripts/verify_proof.py --tag freeze-v1")
        json.dumps(summary, allow_nan=False)

    def test_pass_shows_both_values(self):
        result = self.service(lambda sig: tx_with(MEMO)).verify()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["recomputed"], MEMO)
        self.assertEqual(result["on_chain"], MEMO)

    def test_fail_names_each_differing_field(self):
        other = "backfill:freeze-v1:" + "c" * 64 + ":7654321"
        result = self.service(lambda sig: tx_with(other)).verify()
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["on_chain"], other)
        self.assertEqual([d["field"] for d in result["differences"]], ["manifest_sha256", "commit_short"])

    def test_network_down_is_unavailable_with_saved_receipt(self):
        def down(sig):
            raise ConnectionError("devnet unreachable")
        result = self.service(down).verify()
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["on_chain"], MEMO)  # the saved receipt's memo, labelled as such in the UI
        self.assertEqual(result["receipt"]["signature"], "SIG")

    def test_rpc_error_exit_does_not_crash(self):
        def rpc_error(sig):
            raise SystemExit("RPC error")
        self.assertEqual(self.service(rpc_error).verify()["status"], "UNAVAILABLE")

    def test_unknown_or_failed_transaction_is_fail(self):
        self.assertEqual(self.service(lambda sig: None).verify()["status"], "FAIL")
        self.assertEqual(self.service(lambda sig: tx_with(MEMO, err={"x": 1})).verify()["status"], "FAIL")

    def test_git_recompute_failure_is_unavailable(self):
        with patch.object(_scripts(), "build", side_effect=RuntimeError("tag missing")):
            result = self.service(lambda sig: tx_with(MEMO)).verify()
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertIn("git fetch --tags", result["reason"])

    def test_result_is_cached_for_sixty_seconds(self):
        calls, clock = [], Clock()
        service = self.service(lambda sig: calls.append(sig) or tx_with(MEMO), clock)
        self.assertFalse(service.verify()["cached"])
        clock.now += 59
        second = service.verify()
        self.assertTrue(second["cached"])
        self.assertEqual(second["age_seconds"], 59)
        self.assertEqual(len(calls), 1)
        clock.now += 2
        self.assertFalse(service.verify()["cached"])
        self.assertEqual(len(calls), 2)

    def test_missing_receipt_is_not_anchored_and_unavailable(self):
        (self.root / "proof/freeze-v1/receipt.json").unlink()
        service = self.service(lambda sig: self.fail("must not fetch without a receipt"))
        self.assertFalse(service.summary()["anchored"])
        self.assertEqual(service.verify()["status"], "UNAVAILABLE")

    def test_server_exposes_proof_and_verify_endpoints(self):
        proof = self.service(lambda sig: tx_with(MEMO))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(ResearchRepository(ROOT), TigerMonitor(), proof))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            summary = json.load(urllib.request.urlopen(f"{base}/api/proof"))
            verified = json.load(urllib.request.urlopen(f"{base}/api/proof/verify"))
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(summary["receipt"]["signature"], "SIG")
        self.assertEqual(verified["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
