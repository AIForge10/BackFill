# Proof of research: freeze-v1

## What this proves

Before testing the strategy on new data, we froze the rule, the data and the results at git tag
`freeze-v1` (commit `9c68c898ca2b71c2c742bcae91d1e90df99907ec`). We computed a SHA-256 fingerprint of those files and wrote it
into a Solana transaction. A blockchain transaction carries a timestamp that nobody, including us,
can change afterwards. If any frozen file is edited, or the tag is moved, the fingerprint no longer
matches and verification fails.

## What is fingerprinted

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `HYPOTHESIS.md` | 3,331 | `246c1e52e4506bcb8bc3278e6edecdc1b784d2e208a4c12858a1e319b3ac5fff` |
| `data/processed/final_candidate/v1/all_candidates.csv` | 151,790 | `131b92144dc209b743b9b0325354c6124a3fe9a023e17ed908611f1a3427cee4` |
| `data/processed/final_candidate/v1/audit.csv` | 39,916 | `3eefb17c6a6425c60b10f2a66c7764c5c59cba1601fea244c27f1af897956bb5` |
| `data/processed/final_candidate/v1/price_manifest.json` | 6,997 | `3053d3883d9dc5115c1cd8f9518df1927952e2b760c9b9bbeb4ac2a81d172da3` |
| `data/processed/final_candidate/v1/qualified_evidence.csv` | 12,312 | `ef010aa8968f94462ed7eb5019122919442d78867e3703275b68b814806a52c1` |
| `data/processed/final_candidate/v1/winners.csv` | 10,515 | `672f6ce37e988a7d70bea4bc8c7a7f4215bf912c30d2ad8474b8e51ce856eeda` |
| `data/processed/shortage_events.csv` | 74,679 | `5b1d6824ce8db884239cd42f2a60660b78c94371094e9fe5ddc137d3d04be3df` |
| `research/final_candidate/SPEC.md` | 4,332 | `2f7ea0845d16f5123ab55febb9d49c485534a0d262d9a7bbaee81523b09f3e6f` |
| `research/final_candidate/freeze_v1_config.json` | 1,981 | `e0a5d6e3794b8cf3b50e2fc7f879aaa9272963bd37926058e838e38acc2dc5ac` |
| `results/backtest_report/summary.csv` | 3,020 | `22e015d3a737c08180ba853b4bddf12f2ac8212b9ed1bdc9fa9f9fc3ed34f597` |

These are the hypothesis, the 20/5 rule with its cost model, caps and decision gate, the hashes
of the price data used, the FDA shortage events and traded events, and the published backtest
numbers. The commit hash ties them to the exact code. Never included: `.env` files, keys or
wallets, raw licensed price data, and this `proof/` folder.

## The on-chain record

| Item | Value |
| --- | --- |
| Manifest hash (SHA-256) | `9046c956c9f9618af1ab05900b8b078c1ace0d24402cea1f1316834dac264850` |
| Memo | `backfill:freeze-v1:9046c956c9f9618af1ab05900b8b078c1ace0d24402cea1f1316834dac264850:9c68c89` |
| Signature | `4hCNYKkhWvrBxXZtShVL3depyb3BmU2WjadXSv1WjpKACKCEsKHxwk2RwzYfEknpMiQsW7oebcgYGk5bRGCqq4Vg` |
| Explorer | [https://explorer.solana.com/tx/4hCNYKkhWvrBxXZtShVL3depyb3BmU2WjadXSv1WjpKACKCEsKHxwk2RwzYfEknpMiQsW7oebcgYGk5bRGCqq4Vg?cluster=devnet](https://explorer.solana.com/tx/4hCNYKkhWvrBxXZtShVL3depyb3BmU2WjadXSv1WjpKACKCEsKHxwk2RwzYfEknpMiQsW7oebcgYGk5bRGCqq4Vg?cluster=devnet) |
| Cluster | devnet |
| Sent (UTC) | 2026-10-04T08:47:16+00:00 |

## Verify it yourself

```bash
git clone https://github.com/AIForge10/Gator_Hacks.git && cd Gator_Hacks
git fetch --tags
uv sync
uv run python scripts/verify_proof.py --tag freeze-v1
```

The script reads each file as it is at `freeze-v1`, rebuilds the fingerprint, fetches the
transaction from Solana devnet and compares it with the memo. It prints PASS (exit code 0) or
FAIL with the difference (exit code 1). No wallet is needed. You can also open the explorer link
above and compare the memo by eye with `proof/freeze-v1/manifest.json`.

## Note on devnet

Devnet is Solana's free test network: its SOL has no value and Solana may reset it, which would
erase old transactions. The receipt in `proof/freeze-v1/receipt.json` keeps the signature and memo for
the record. A production version would anchor on Solana mainnet, where the record is permanent.
