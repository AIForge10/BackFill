"""Recompute the freeze manifest from git and check it against the memo on Solana devnet.

    uv run python -m proof.verify_proof               # uses proof/freeze-v1/receipt.json

Needs only git, the tag and network access to a devnet RPC; no key or Solana library.
Exits non-zero on any mismatch.
"""
import argparse
import json
import sys

from proof.chain import RPC, rpc
from proof.make_manifest import DEFAULT_TAG, ROOT, build, memo


def memos_in(tx):
    """Memo strings from a jsonParsed transaction (spl-memo instructions)."""
    instructions = tx["transaction"]["message"]["instructions"]
    return [ix["parsed"] for ix in instructions if ix.get("program") == "spl-memo"]


def check(tag, receipt, url):
    results = []
    manifest = build(tag)
    expected = memo(manifest)
    results.append(("manifest hash recomputed from git", manifest["manifest_sha256"] == receipt["manifest_sha256"],
                    manifest["manifest_sha256"]))
    results.append(("tag still points at anchored commit", manifest["commit"] == receipt["commit"], manifest["commit"]))
    tx = rpc("getTransaction", receipt["signature"], {"encoding": "jsonParsed", "commitment": "confirmed",
                                                      "maxSupportedTransactionVersion": 0}, url=url)
    if tx is None:
        results.append(("transaction found on chain", False, receipt["signature"]))
        return results
    results.append(("transaction succeeded", tx["meta"]["err"] is None, receipt["signature"]))
    results.append(("on-chain memo matches recomputed memo", expected in memos_in(tx), expected))
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", default=DEFAULT_TAG)
    ap.add_argument("--rpc", default=RPC)
    args = ap.parse_args(argv)
    receipt = json.loads((ROOT / "proof" / args.tag / "receipt.json").read_text())
    results = check(args.tag, receipt, args.rpc)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    if not all(ok for _, ok, _ in results):
        sys.exit(1)
    print(f"Verified: {args.tag} matches the memo in {receipt['explorer']}")


if __name__ == "__main__":
    main()
