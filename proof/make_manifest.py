"""Hash the frozen research files exactly as committed at a git tag.

    uv run python -m proof.make_manifest              # tag freeze-v1 -> proof/freeze-v1/manifest.json

File bytes are read from the tag (git show <tag>:<path>), never the working tree, so anyone with a
clone gets the same manifest. The manifest hash is SHA-256 of the canonical JSON of tag, commit
and the sorted {path: sha256} map; that one hash is what gets anchored on chain.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAG = "freeze-v1"

# What a judge needs to confirm the rules were not changed later. The commit hash in the manifest
# ties these to the exact code.
FROZEN = [
    "HYPOTHESIS.md",                                         # the 20/5 rule and predictions
    "research/final_candidate/freeze_v1_config.json",        # rule, cost model, caps, decision gate
    "research/final_candidate/SPEC.md",                      # the written rule the config summarizes
    "data/processed/final_candidate/v1/price_manifest.json", # per-file hashes of the price data used
    "data/processed/shortage_events.csv",                    # FDA shortage events
    "data/processed/final_candidate/v1/winners.csv",         # the events traded
    "data/processed/final_candidate/v1/qualified_evidence.csv",
    "data/processed/final_candidate/v1/all_candidates.csv",
    "data/processed/final_candidate/v1/audit.csv",
    "results/backtest_report/summary.csv",                   # the published numbers
]
# Never fingerprinted: secrets, keys, licensed raw data, and the proof itself.
FORBIDDEN = re.compile(r"(^|/)\.env($|\.)|keypair|(^|/)id\.json$|^data/raw/|^proof/|^PROOF\.md$")


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def resolve(tag):
    return git("rev-parse", f"{tag}^{{commit}}").decode().strip()


def frozen_paths(commit, patterns=FROZEN):
    listed = git("ls-tree", "-r", "--name-only", commit).decode().splitlines()
    paths = sorted(p for p in listed if any(p == f or (f.endswith("/") and p.startswith(f)) for f in patterns))
    blocked = [p for p in paths if FORBIDDEN.search(p)]
    if blocked:
        raise ValueError(f"Refusing to fingerprint secrets, raw data or proof files: {blocked}")
    missing = [f for f in patterns if not any(p == f or p.startswith(f) for p in paths)]
    if missing:
        raise ValueError(f"Not committed at {commit[:12]}: {missing}")
    return paths


def manifest_hash(manifest):
    body = {k: manifest[k] for k in ("tag", "commit", "files")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build(tag=DEFAULT_TAG, patterns=FROZEN):
    commit = resolve(tag)
    files = {p: hashlib.sha256(git("show", f"{commit}:{p}")).hexdigest() for p in frozen_paths(commit, patterns)}
    manifest = dict(tag=tag, commit=commit, files=files)
    manifest["manifest_sha256"] = manifest_hash(manifest)
    return manifest


def memo(manifest):
    return f"backfill:{manifest['tag']}:{manifest['manifest_sha256']}:{manifest['commit']}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", default=DEFAULT_TAG)
    args = ap.parse_args(argv)
    manifest = build(args.tag)
    out = ROOT / "proof" / args.tag / "manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{len(manifest['files'])} files at {manifest['commit'][:12]} -> {out.relative_to(ROOT)}")
    print(f"manifest hash {manifest['manifest_sha256']}")
    print(f"memo          {memo(manifest)}")


if __name__ == "__main__":
    main()
