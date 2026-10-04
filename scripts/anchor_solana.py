"""Write the manifest fingerprint on Solana devnet with the Solana CLI, then save a receipt.

    uv run python scripts/make_manifest.py --tag freeze-v1    # first; check the manifest
    uv run python scripts/anchor_solana.py --tag freeze-v1

Sends a 0.000001 SOL transfer from your default CLI keypair to your own address, carrying the
memo "backfill:<tag>:<manifest_sha256>:<commit_short>". Refuses to run twice for one tag.
Writes proof/<tag>/receipt.json and regenerates PROOF.md.
"""
import argparse
import json
import subprocess
from datetime import datetime, timezone

from make_manifest import ROOT, build, memo
from render_proof import write_proof_md

CLUSTER = "devnet"
AMOUNT_SOL = "0.000001"


def solana(*args):
    """Run the Solana CLI against devnet and return stdout text."""
    result = subprocess.run(["solana", *args, "--url", CLUSTER], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"solana {' '.join(args[:1])} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def main():
    ap = argparse.ArgumentParser(description="Anchor a freeze manifest on Solana devnet.")
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    folder = ROOT / "proof" / args.tag
    receipt_path = folder / "receipt.json"

    # One anchor per tag: a second memo would make the record ambiguous.
    if receipt_path.exists():
        raise SystemExit(f"{receipt_path.relative_to(ROOT)} exists; the memo for {args.tag} was already sent.")

    # The saved manifest must still match the tag, so we anchor exactly what was reviewed.
    saved = json.loads((folder / "manifest.json").read_text())
    if build(args.tag) != saved:
        raise SystemExit("proof/<tag>/manifest.json no longer matches the tag; rerun make_manifest.py and review it.")
    text = memo(saved)

    me = solana("address")
    print(f"Sending {AMOUNT_SOL} SOL to {me} on {CLUSTER} with memo:\n  {text}")
    sent = json.loads(solana("transfer", me, AMOUNT_SOL, "--with-memo", text,
                             "--allow-unfunded-recipient", "--output", "json"))
    signature = sent["signature"]

    receipt = dict(
        tag=saved["tag"], commit=saved["commit"], manifest_sha256=saved["manifest_sha256"], memo=text,
        signature=signature, cluster=CLUSTER, signer=me,
        timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        explorer=f"https://explorer.solana.com/tx/{signature}?cluster={CLUSTER}",
    )
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    write_proof_md(saved, receipt)
    print(f"Saved {receipt_path.relative_to(ROOT)} and PROOF.md\n{receipt['explorer']}")


if __name__ == "__main__":
    main()
