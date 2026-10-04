"""Check that the frozen files at a git tag match the memo written on Solana devnet.

    uv run python scripts/verify_proof.py --tag freeze-v1

Recomputes the manifest hash from the tag, fetches the transaction named in
proof/<tag>/receipt.json from the devnet RPC, and reads the memo from its log messages.
Prints PASS and exits 0 when they match; prints FAIL with the difference and exits 1 otherwise.
No wallet or Solana CLI is needed.
"""
import argparse
import json
import re
import sys

import requests

from make_manifest import ROOT, build, memo

RPC = "https://api.devnet.solana.com"
# Memo programs log the text in one of two ways:
#   older:  Program log: Memo (len 91): "backfill:..."
#   newer:  Program log: Memo (len 91)        <- header line
#           Program log: backfill:...          <- the text on the next line
MEMO_INLINE = re.compile(r'^Program log: Memo \(len \d+\): "(.*)"$')
MEMO_HEADER = re.compile(r'^Program log: Memo \(len \d+\)$')


def fetch_transaction(signature, url=RPC):
    """getTransaction from the RPC; None if the cluster does not know the signature."""
    payload = dict(jsonrpc="2.0", id=1, method="getTransaction",
                   params=[signature, {"encoding": "json", "commitment": "confirmed",
                                       "maxSupportedTransactionVersion": 0}])
    reply = requests.post(url, json=payload, timeout=30).json()
    if "error" in reply:
        raise SystemExit(f"RPC error: {reply['error']}")
    return reply["result"]


def memos_from_logs(logs):
    """Every memo string found in a transaction's log messages (either log format)."""
    logs = logs or []
    memos = []
    for i, line in enumerate(logs):
        if m := MEMO_INLINE.match(line):
            memos.append(m.group(1))
        elif MEMO_HEADER.match(line) and i + 1 < len(logs) and logs[i + 1].startswith("Program log: "):
            memos.append(logs[i + 1].removeprefix("Program log: "))
    return memos


def main():
    ap = argparse.ArgumentParser(description="Verify a freeze manifest against its Solana devnet memo.")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--rpc", default=RPC)
    args = ap.parse_args()
    receipt = json.loads((ROOT / "proof" / args.tag / "receipt.json").read_text())

    # 1. Recompute from git: anyone with a clone and the tag gets the same value.
    manifest = build(args.tag)
    expected = memo(manifest)

    # 2. Read what is actually on chain.
    tx = fetch_transaction(receipt["signature"], args.rpc)
    if tx is None:
        print(f"FAIL  transaction {receipt['signature']} not found on {args.rpc}")
        sys.exit(1)
    if tx["meta"]["err"] is not None:
        print(f"FAIL  transaction failed on chain: {tx['meta']['err']}")
        sys.exit(1)
    on_chain = memos_from_logs(tx["meta"]["logMessages"])

    # 3. Compare.
    print(f"recomputed  {expected}")
    print(f"on chain    {on_chain[0] if on_chain else '(no memo in logs)'}")
    if expected in on_chain:
        print(f"PASS  {args.tag} at {manifest['commit'][:12]} matches {receipt['explorer']}")
        sys.exit(0)
    found = on_chain[0] if on_chain else ""
    for label, ours, theirs in zip(["prefix", "tag", "manifest_sha256", "commit_short"],
                                   expected.split(":"), found.split(":") + [""] * 4):
        if ours != theirs:
            print(f"FAIL  {label} differs: recomputed {ours!r}, on chain {theirs!r}")
    sys.exit(1)


if __name__ == "__main__":
    main()
