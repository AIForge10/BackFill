"""Write PROOF.md from proof/<tag>/manifest.json and, once anchored, receipt.json.

    uv run python scripts/render_proof.py --tag freeze-v1

anchor_solana.py calls this automatically after sending the memo.
"""
import argparse
import json

from make_manifest import ROOT

PENDING = "_not yet anchored; run `scripts/anchor_solana.py`_"


def write_proof_md(manifest, receipt=None):
    r = receipt or {}
    tag = manifest["tag"]
    signature = r.get("signature", PENDING)
    explorer = f"[{r['explorer']}]({r['explorer']})" if receipt else PENDING
    files = "\n".join(f"| `{f['path']}` | {f['bytes']:,} | `{f['sha256']}` |" for f in manifest["files"])
    text = f"""# Proof of research: {tag}

## What this proves

Before testing the strategy on new data, we froze the rule, the data and the results at git tag
`{tag}` (commit `{manifest['commit']}`). We computed a SHA-256 fingerprint of those files and wrote it
into a Solana transaction. A blockchain transaction carries a timestamp that nobody, including us,
can change afterwards. If any frozen file is edited, or the tag is moved, the fingerprint no longer
matches and verification fails.

## What is fingerprinted

| File | Bytes | SHA-256 |
| --- | ---: | --- |
{files}

These are the hypothesis, the 20/5 rule with its cost model, caps and decision gate, the hashes
of the price data used, the FDA shortage events and traded events, and the published backtest
numbers. The commit hash ties them to the exact code. Never included: `.env` files, keys or
wallets, raw licensed price data, and this `proof/` folder.

## The on-chain record

| Item | Value |
| --- | --- |
| Manifest hash (SHA-256) | `{manifest['manifest_sha256']}` |
| Memo | `{r.get('memo', PENDING)}` |
| Signature | `{signature}` |
| Explorer | {explorer} |
| Cluster | {r.get('cluster', 'devnet')} |
| Sent (UTC) | {r.get('timestamp_utc', PENDING)} |

## Verify it yourself

```bash
git clone https://github.com/AIForge10/Gator_Hacks.git && cd Gator_Hacks
git fetch --tags
uv sync
uv run python scripts/verify_proof.py --tag {tag}
```

The script reads each file as it is at `{tag}`, rebuilds the fingerprint, fetches the
transaction from Solana devnet and compares it with the memo. It prints PASS (exit code 0) or
FAIL with the difference (exit code 1). No wallet is needed. You can also open the explorer link
above and compare the memo by eye with `proof/{tag}/manifest.json`.

## Note on devnet

Devnet is Solana's free test network: its SOL has no value and Solana may reset it, which would
erase old transactions. The receipt in `proof/{tag}/receipt.json` keeps the signature and memo for
the record. A production version would anchor on Solana mainnet, where the record is permanent.
"""
    (ROOT / "PROOF.md").write_text(text)


def main():
    ap = argparse.ArgumentParser(description="Write PROOF.md from the manifest and receipt.")
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    folder = ROOT / "proof" / args.tag
    manifest = json.loads((folder / "manifest.json").read_text())
    receipt_path = folder / "receipt.json"
    write_proof_md(manifest, json.loads(receipt_path.read_text()) if receipt_path.exists() else None)
    print("Wrote PROOF.md")


if __name__ == "__main__":
    main()
