"""Write the manifest hash as a memo on Solana devnet and save the receipt.

    uv run --extra proof python -m proof.anchor_solana     # reads proof/freeze-v1/manifest.json

The memo is "backfill:<tag>:<manifest hash>:<commit>". The fee payer is a throwaway devnet key kept
outside the repo (default ~/.config/backfill/devnet-keypair.json); it is created and funded by a
devnet airdrop on first use. Also writes PROOF.md. Devnet SOL has no value. Refuses to anchor the same tag twice.
"""
import argparse
import base64
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from proof.chain import RPC, rpc
from proof.make_manifest import DEFAULT_TAG, ROOT, build, memo
from proof.render import proof_markdown

MEMO_PROGRAM = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")
KEYPAIR = Path.home() / ".config/backfill/devnet-keypair.json"
FEE_RESERVE = 1_000_000  # lamports; a memo costs 5,000


def load_keypair(path):
    if path.exists():
        return Keypair.from_bytes(bytes(json.loads(path.read_text())))
    keypair = Keypair()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(bytes(keypair))))
    path.chmod(0o600)
    return keypair


def fund(pubkey, url):
    if rpc("getBalance", str(pubkey), url=url)["value"] >= FEE_RESERVE:
        return
    signature = rpc("requestAirdrop", str(pubkey), 100_000_000, url=url)
    wait(signature, url)


def wait(signature, url, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = rpc("getSignatureStatuses", [signature], url=url)["value"][0]
        if status and status.get("err"):
            raise RuntimeError(f"{signature} failed: {status['err']}")
        if status and status.get("confirmationStatus") in ("confirmed", "finalized"):
            return status
        time.sleep(2)
    raise TimeoutError(f"{signature} not confirmed after {timeout}s")


def send_memo(keypair, text, url):
    instruction = Instruction(MEMO_PROGRAM, text.encode(), [AccountMeta(keypair.pubkey(), True, True)])
    blockhash = Hash.from_string(rpc("getLatestBlockhash", {"commitment": "finalized"}, url=url)["value"]["blockhash"])
    tx = Transaction([keypair], Message.new_with_blockhash([instruction], keypair.pubkey(), blockhash), blockhash)
    signature = rpc("sendTransaction", base64.b64encode(bytes(tx)).decode(), {"encoding": "base64"}, url=url)
    wait(signature, url)
    return signature


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", default=DEFAULT_TAG)
    ap.add_argument("--keypair", type=Path, default=KEYPAIR)
    ap.add_argument("--rpc", default=RPC)
    args = ap.parse_args(argv)
    folder = ROOT / "proof" / args.tag
    receipt_path = folder / "receipt.json"
    if receipt_path.exists():
        raise SystemExit(f"{receipt_path.relative_to(ROOT)} exists; {args.tag} is already anchored.")
    saved = json.loads((folder / "manifest.json").read_text())
    if build(args.tag) != saved:
        raise SystemExit("Saved manifest no longer matches the tag; rerun proof.make_manifest.")
    text = memo(saved)
    keypair = load_keypair(args.keypair)
    fund(keypair.pubkey(), args.rpc)
    signature = send_memo(keypair, text, args.rpc)
    tx = rpc("getTransaction", signature, {"encoding": "json", "commitment": "confirmed",
                                           "maxSupportedTransactionVersion": 0}, url=args.rpc)
    receipt = dict(
        network="devnet", rpc=args.rpc, signature=signature, slot=tx["slot"],
        block_time=datetime.fromtimestamp(tx["blockTime"], timezone.utc).isoformat(),
        anchored_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        signer=str(keypair.pubkey()), memo=text, tag=saved["tag"], commit=saved["commit"],
        manifest_sha256=saved["manifest_sha256"],
        explorer=f"https://explorer.solana.com/tx/{signature}?cluster=devnet",
    )
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    (ROOT / "PROOF.md").write_text(proof_markdown(saved, receipt))
    print(f"Anchored {args.tag}: {receipt['explorer']}")


if __name__ == "__main__":
    main()
