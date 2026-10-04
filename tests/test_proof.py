"""Proof scripts: manifest from a git tag, exclusions, config sync and memo parsing. No network, no wallet."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from make_manifest import FORBIDDEN, build, canonical_hash, check_allowed, memo, read_paths  # noqa: E402
from verify_proof import memos_from_logs  # noqa: E402
from research.final_candidate.run import frozen_settings  # noqa: E402

# Committed at HEAD and at freeze-v1, so the tests need no particular tag.
COMMITTED = ["HYPOTHESIS.md", "research/final_candidate/SPEC.md",
             "data/processed/final_candidate/v1/price_manifest.json"]


class ProofScriptsTest(unittest.TestCase):
    def test_manifest_is_deterministic_sorted_and_canonical(self):
        first, second = build("HEAD", COMMITTED), build("HEAD", COMMITTED)
        self.assertEqual(first, second)
        self.assertEqual([f["path"] for f in first["files"]], sorted(COMMITTED))
        self.assertEqual(len(first["commit"]), 40)
        self.assertEqual(first["manifest_sha256"], canonical_hash(first["tag"], first["commit"], first["files"]))
        self.assertTrue(all(f["bytes"] > 0 and len(f["sha256"]) == 64 for f in first["files"]))

    def test_any_file_change_changes_the_hash(self):
        manifest = build("HEAD", COMMITTED)
        files = json.loads(json.dumps(manifest["files"]))
        files[0]["sha256"] = "0" * 64
        self.assertNotEqual(canonical_hash(manifest["tag"], manifest["commit"], files), manifest["manifest_sha256"])

    def test_memo_format(self):
        manifest = build("HEAD", COMMITTED)
        self.assertEqual(memo(manifest), f"backfill:HEAD:{manifest['manifest_sha256']}:{manifest['commit'][:7]}")

    def test_secrets_proof_and_gitignored_files_are_refused(self):
        for path in [".env", "examples/backtest/.env", "examples/backtest/.env.example", "id.json",
                     "devnet-keypair.json", "data/raw/prices/is/SPY.csv", "proof/freeze-v1/receipt.json",
                     "PROOF.md"]:
            self.assertTrue(FORBIDDEN.search(path), path)
        with self.assertRaises(ValueError):
            check_allowed("results/backfill/anything.csv")  # gitignored, not covered by FORBIDDEN
        for path in COMMITTED + ["results/backtest_report/summary.csv"]:
            check_allowed(path)

    def test_file_list_is_allowed(self):
        paths = read_paths()
        self.assertEqual(len(paths), 10)
        for path in paths:
            check_allowed(path)

    def test_freeze_config_matches_the_settings_the_runner_uses(self):
        config = json.loads((ROOT / "research/final_candidate/freeze_v1_config.json").read_text())
        settings = frozen_settings()
        self.assertEqual(config["rule"]["hold_sessions"], settings.hold_days)
        self.assertEqual(config["rule"]["beta_lookback"], settings.beta_lookback)
        self.assertEqual(config["rule"]["event_weight"], settings.event_weight)
        self.assertEqual(config["sample"], {"start": settings.start, "end": settings.end})
        self.assertEqual(config["costs"]["stock_bps_per_side"], settings.costs_bps)
        self.assertEqual(config["costs"]["hedge_bps_per_side"], settings.hedge_cost_bps)
        self.assertEqual(config["costs"]["hedge_carry_bps_per_year"], settings.hedge_carry_bps_year)
        self.assertEqual(config["caps"], dict(name=settings.name_cap, country=settings.country_cap,
                                              sector=settings.sector_cap, gross=settings.gross_cap,
                                              net=settings.net_cap, foreign_long=settings.foreign_long_cap))

    def test_memo_is_read_from_log_messages(self):
        logs = ["Program 11111111111111111111111111111111 invoke [1]",
                "Program MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr invoke [1]",
                'Program log: Memo (len 26): "backfill:freeze-v1:abc:def"',
                "Program MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr success"]
        self.assertEqual(memos_from_logs(logs), ["backfill:freeze-v1:abc:def"])
        self.assertEqual(memos_from_logs(None), [])

    def test_memo_is_read_from_the_newer_two_line_log_format(self):
        # Exact logs of the freeze-v1 anchor transaction (Memo4c2p... program, Solana CLI 4.3).
        logs = ["Program 11111111111111111111111111111111 invoke [1]",
                "Program 11111111111111111111111111111111 success",
                "Program Memo4c2pN8afCj432Lb7RMVKi9PbQnnW7ewFFaV3oAH invoke [1]",
                "Program log: Memo (len 91)",
                "Program log: backfill:freeze-v1:9046c956c9f9618af1ab05900b8b078c1ace0d24402cea1f1316834dac264850:9c68c89",
                "Program Memo4c2pN8afCj432Lb7RMVKi9PbQnnW7ewFFaV3oAH success"]
        self.assertEqual(memos_from_logs(logs), [
            "backfill:freeze-v1:9046c956c9f9618af1ab05900b8b078c1ace0d24402cea1f1316834dac264850:9c68c89"])


if __name__ == "__main__":
    unittest.main()
