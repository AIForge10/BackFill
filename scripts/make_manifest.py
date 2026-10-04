"""Fingerprint the frozen research files exactly as they are at a git tag.

    uv run python scripts/make_manifest.py --tag freeze-v1

Reads the paths in proof/manifest_files.txt, takes each file's bytes from the tag
(git show <tag>:<path>, never the working tree), and writes proof/<tag>/manifest.json.
manifest_sha256 is the SHA-256 of the canonical JSON of {tag, commit, files}.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE_LIST = ROOT / "proof/manifest_files.txt"

# Never fingerprinted: env files, keys/wallets, raw licensed data, the proof folder itself.
FORBIDDEN = re.compile(r"(^|/)\.env($|\.)|keypair|wallet|(^|/)id\.json$|\.pem$|^data/raw/|^proof/|^PROOF\.md$")


def git(*args):
    """Run a git command in the repo and return its raw stdout bytes."""
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def read_paths(file_list=FILE_LIST):
    """Repo-relative paths, one per line; blank lines and # comments are skipped."""
    lines = (line.strip() for line in Path(file_list).read_text().splitlines())
    return sorted({line for line in lines if line and not line.startswith("#")})


def check_allowed(path):
    """Refuse secrets, the proof folder and anything gitignored."""
    if FORBIDDEN.search(path):
        raise ValueError(f"Refusing to fingerprint {path}: env, key, raw data or proof file.")
    # --no-index checks the ignore rules even for files that are tracked.
    ignored = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=ROOT).returncode == 0
    if ignored:
        raise ValueError(f"Refusing to fingerprint {path}: it is gitignored.")


def canonical_hash(tag, commit, files):
    """SHA-256 over canonical JSON: sorted keys, no extra spaces."""
    body = json.dumps(dict(tag=tag, commit=commit, files=files), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def build(tag, paths=None):
    """Manifest for `tag`: full commit hash plus {path, sha256, bytes} per file, sorted by path."""
    commit = git("rev-parse", f"{tag}^{{commit}}").decode().strip()
    files = []
    for path in sorted(paths if paths is not None else read_paths()):
        check_allowed(path)
        content = git("show", f"{commit}:{path}")  # fails if the file is not in the tagged commit
        files.append(dict(path=path, sha256=hashlib.sha256(content).hexdigest(), bytes=len(content)))
    return dict(tag=tag, commit=commit, files=files, manifest_sha256=canonical_hash(tag, commit, files))


def memo(manifest):
    """The exact text written on chain: backfill:<tag>:<manifest_sha256>:<commit_short>."""
    return f"backfill:{manifest['tag']}:{manifest['manifest_sha256']}:{manifest['commit'][:7]}"


def main():
    ap = argparse.ArgumentParser(description="Fingerprint frozen files at a git tag.")
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    manifest = build(args.tag)
    out = ROOT / "proof" / args.tag / "manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{len(manifest['files'])} files at {manifest['commit'][:12]} -> {out.relative_to(ROOT)}")
    print(f"manifest_sha256  {manifest['manifest_sha256']}")
    print(f"memo             {memo(manifest)}")


if __name__ == "__main__":
    main()
