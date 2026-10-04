"""Solana proof of the freeze-v1 files: saved receipt plus a cached live re-verification.

Reuses scripts/make_manifest.py (recompute the memo from the git tag) and scripts/verify_proof.py
(fetch the transaction from devnet and read its memo). Never raises: a network or git problem
returns UNAVAILABLE with the saved receipt, so the dashboard keeps working offline.
"""
import json
import sys
import threading
import time
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = CODE_ROOT / "scripts"
TAG = "freeze-v1"
CACHE_SECONDS = 60
OLDER_FREEZE = "data/processed/final_candidate/v1/freeze.json"
MEMO_FIELDS = ("prefix", "tag", "manifest_sha256", "commit_short")


def _scripts():
    """Import the proof scripts (a plain folder, not a package) on first use."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import make_manifest
    return make_manifest


def _default_fetch(signature):
    _scripts()
    from verify_proof import fetch_transaction  # imports requests lazily, only when verifying
    return fetch_transaction(signature)


def _read(path):
    return json.loads(path.read_text()) if path.exists() else None


class ProofService:
    def __init__(self, root, tag=TAG, fetch_transaction=None, clock=time.monotonic, cache_seconds=CACHE_SECONDS):
        self.root = Path(root).resolve()
        self.tag = tag
        self.folder = self.root / "proof" / tag
        self.fetch_transaction = fetch_transaction or _default_fetch
        self.clock = clock
        self.cache_seconds = cache_seconds
        self._cached = None  # (time, result)
        self._lock = threading.Lock()

    def receipt(self):
        return _read(self.folder / "receipt.json")

    def summary(self):
        """Saved, offline facts about the anchor; no network or git calls."""
        receipt, manifest = self.receipt(), _read(self.folder / "manifest.json")
        older = _read(self.root / OLDER_FREEZE) or {}
        older_files = sorted(older.get("frozen_files", {}))
        files = (manifest or {}).get("files", [])
        anchored_at = (receipt or {}).get("timestamp_utc", "")
        minute = f"{anchored_at[:10]} {anchored_at[11:16]} UTC" if anchored_at else "the anchor time"
        return dict(
            tag=self.tag, anchored=bool(receipt and manifest), receipt=receipt, files=files,
            commit=(manifest or {}).get("commit"), manifest_sha256=(manifest or {}).get("manifest_sha256"),
            statement=f"Proves the frozen rules existed at {minute}. "
                      "It does not make the 2014–2024 backtest out-of-sample.",
            verify_command=f"uv run python scripts/verify_proof.py --tag {self.tag}",
            comparison=dict(
                older=dict(name="freeze.json", files=len(older_files), source=OLDER_FREEZE,
                           checks="Your local copy against hashes recorded by the research team",
                           timestamp="None outside the repository"),
                anchored=dict(name=self.tag, files=len(files), source=f"proof/{self.tag}/manifest.json",
                              checks="The files at the git tag against a fingerprint on Solana devnet",
                              timestamp=minute),
                shared=sorted(set(older_files) & {f["path"] for f in files}),
            ),
        )

    def verify(self):
        """PASS / FAIL / UNAVAILABLE, cached for cache_seconds. Never raises."""
        with self._lock:
            now = self.clock()
            if self._cached and now - self._cached[0] < self.cache_seconds:
                return dict(self._cached[1], cached=True, age_seconds=round(now - self._cached[0]))
            result = self._verify_uncached()
            self._cached = (now, result)
            return dict(result, cached=False, age_seconds=0)

    def _verify_uncached(self):
        receipt = self.receipt()
        checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        base = dict(tag=self.tag, checked_at=checked_at, receipt=receipt, recomputed=None, on_chain=None,
                    differences=[], explorer=(receipt or {}).get("explorer"))
        if not receipt:
            return dict(base, status="UNAVAILABLE", reason="No saved receipt; the tag has not been anchored.")
        # 1. Recompute the memo from the git tag (needs git and the fetched tag).
        try:
            make_manifest = _scripts()
            recomputed = make_manifest.memo(make_manifest.build(self.tag))
        except Exception:
            return dict(base, status="UNAVAILABLE", on_chain=receipt.get("memo"),
                        reason=f"Could not recompute from git tag {self.tag}; run git fetch --tags. Showing the saved receipt.")
        base["recomputed"] = recomputed
        # 2. Read the memo from devnet. SystemExit is how verify_proof reports an RPC error.
        try:
            tx = self.fetch_transaction(receipt["signature"])
        except (Exception, SystemExit):
            return dict(base, status="UNAVAILABLE", on_chain=receipt.get("memo"),
                        reason="Solana devnet could not be reached. Showing the memo saved in the receipt.")
        if tx is None:
            return dict(base, status="FAIL", reason="Devnet does not know this transaction signature.")
        if (tx.get("meta") or {}).get("err") is not None:
            return dict(base, status="FAIL", reason="The transaction failed on chain.")
        _scripts()
        from verify_proof import memos_from_logs
        memos = memos_from_logs((tx.get("meta") or {}).get("logMessages"))
        on_chain = memos[0] if memos else None
        base["on_chain"] = on_chain
        if recomputed in memos:
            return dict(base, status="PASS", on_chain=recomputed,
                        reason="The fingerprint recomputed from the git tag matches the memo on Solana devnet.")
        theirs = (on_chain or "").split(":") + [""] * len(MEMO_FIELDS)
        differences = [dict(field=name, recomputed=ours, on_chain=theirs[i])
                       for i, (name, ours) in enumerate(zip(MEMO_FIELDS, recomputed.split(":"))) if ours != theirs[i]]
        return dict(base, status="FAIL", differences=differences,
                    reason="The fingerprint recomputed from the git tag does not match the memo on chain.")
