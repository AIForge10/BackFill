"""Freeze proof: manifest determinism, exclusions, config sync, offline transaction and memo parsing. No network."""
import json
import unittest
from pathlib import Path

from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.transaction import Transaction

from proof.anchor_solana import MEMO_PROGRAM
from proof.make_manifest import FORBIDDEN, build, frozen_paths, manifest_hash, memo, resolve
from proof.verify_proof import memos_in
from research.final_candidate.run import frozen_settings

ROOT = Path(__file__).resolve().parents[1]
# Files already committed at HEAD, so the tests do not depend on the freeze-v1 tag existing.
COMMITTED = ["HYPOTHESIS.md", "research/final_candidate/SPEC.md",
             "data/processed/final_candidate/v1/price_manifest.json"]


class ProofTest(unittest.TestCase):
    def test_manifest_is_deterministic_and_reads_the_commit(self):
        first, second = build("HEAD", COMMITTED), build("HEAD", COMMITTED)
        self.assertEqual(first, second)
        self.assertEqual(first["commit"], resolve("HEAD"))
        self.assertEqual(sorted(first["files"]), sorted(COMMITTED))

    def test_any_file_change_changes_the_hash(self):
        manifest = build("HEAD", COMMITTED)
        altered = json.loads(json.dumps(manifest))
        altered["files"]["HYPOTHESIS.md"] = "0" * 64
        self.assertNotEqual(manifest_hash(altered), manifest["manifest_sha256"])

    def test_secrets_raw_data_and_proof_are_never_fingerprinted(self):
        for path in [".env", "examples/backtest/.env", "examples/backtest/.env.example", "id.json",
                     "keys/devnet-keypair.json", "data/raw/prices/is/SPY.csv", "proof/freeze-v1/receipt.json",
                     "PROOF.md"]:
            self.assertTrue(FORBIDDEN.search(path), path)
        for path in ["HYPOTHESIS.md", "results/backtest_report/summary.csv",
                     "data/processed/final_candidate/v1/price_manifest.json"]:
            self.assertFalse(FORBIDDEN.search(path), path)
        with self.assertRaises(ValueError):
            frozen_paths(resolve("HEAD"), ["examples/backtest/.env.example"])

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

    def test_memo_format(self):
        manifest = build("HEAD", COMMITTED)
        self.assertEqual(memo(manifest).split(":"),
                         ["backfill", "HEAD", manifest["manifest_sha256"], manifest["commit"]])

    def test_signed_memo_transaction_carries_the_memo(self):
        keypair, text = Keypair(), memo(build("HEAD", COMMITTED))
        instruction = Instruction(MEMO_PROGRAM, text.encode(), [AccountMeta(keypair.pubkey(), True, True)])
        tx = Transaction([keypair], Message.new_with_blockhash([instruction], keypair.pubkey(), Hash.default()),
                         Hash.default())
        tx.verify()  # raises if the signature does not match
        self.assertEqual(bytes(tx.message.instructions[0].data).decode(), text)

    def test_memo_parsing_ignores_other_programs(self):
        tx = {"transaction": {"message": {"instructions": [
            {"program": "system", "parsed": {"type": "transfer"}},
            {"program": "spl-memo", "parsed": "backfill:freeze-v1:abc:def"}]}}}
        self.assertEqual(memos_in(tx), ["backfill:freeze-v1:abc:def"])


if __name__ == "__main__":
    unittest.main()
