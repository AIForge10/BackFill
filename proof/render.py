"""Write PROOF.md from a saved manifest and receipt (no network).

    uv run python -m proof.render                     # proof/freeze-v1/{manifest,receipt}.json -> PROOF.md
"""
import argparse
import json

from proof.make_manifest import DEFAULT_TAG, ROOT


def proof_markdown(manifest, receipt):
    files = "\n".join(f"| `{path}` | `{digest[:16]}…` |" for path, digest in manifest["files"].items())
    return f"""# Proof of freeze: {receipt['tag']}

The research files below were frozen at git tag `{receipt['tag']}` (commit `{receipt['commit']}`)
and their combined hash was written to Solana devnet on {receipt['block_time']}.
Any later change to a frozen file, or moving the tag, makes verification fail.

| Item | Value |
| --- | --- |
| Manifest hash (SHA-256) | `{receipt['manifest_sha256']}` |
| On-chain memo | `{receipt['memo']}` |
| Transaction | [{receipt['signature'][:20]}…]({receipt['explorer']}) |
| Slot / block time | {receipt['slot']} / {receipt['block_time']} |
| Signer (devnet) | `{receipt['signer']}` |

## Verify it yourself

```bash
git fetch --tags
uv run python -m proof.verify_proof --tag {receipt['tag']}
```

This recomputes every file hash from the tagged commit, rebuilds the manifest hash, and checks
that the memo in the devnet transaction matches. Devnet can be reset by Solana; the receipt and
this file keep the signature, slot and memo for the record.

## Frozen files ({len(manifest['files'])})

| File | SHA-256 |
| --- | --- |
{files}
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", default=DEFAULT_TAG)
    args = ap.parse_args(argv)
    folder = ROOT / "proof" / args.tag
    manifest = json.loads((folder / "manifest.json").read_text())
    receipt = json.loads((folder / "receipt.json").read_text())
    (ROOT / "PROOF.md").write_text(proof_markdown(manifest, receipt))
    print("Wrote PROOF.md")


if __name__ == "__main__":
    main()
