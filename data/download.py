"""Get the data. Every source is public except prices (licensed: fetched, never committed).

  python data/download.py release   # fastest: the team's archived FDA pages from the GitHub release
  python data/download.py fda-csv   # archived FDA shortage CSV exports (fill the 2024-09 -> 2025-09 gap)
  python data/download.py prices    # daily prices: Webull for US listings, yfinance otherwise
  python data/download.py rebuild   # slow: re-index and re-fetch every archived FDA page from Wayback

The derived FDA tables in data/processed/ are already committed, so a judge only needs `prices`
(run_all.py does it automatically when the price cache is missing).
"""
import argparse
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PY = sys.executable
# Delisted owners with no vendor history; excluded and disclosed in the price manifest.
PRICE_EXCLUSIONS = [
    "HSP=Hospira delisted 2015 (cash acquisition by Pfizer); no vendor history on Webull or Yahoo",
    "MYL=Mylan delisted 2020 (Viatris); not on Webull or Yahoo; predecessor history not aliased by design",
]
CSV_URL = "accessdata.fda.gov/scripts/drugshortages/Drugshortages.cfm"


def run(*args):
    print("$", " ".join(str(a) for a in args), flush=True)
    subprocess.run([PY, *map(str, args)], cwd=ROOT, check=True)


def release(_):
    """Download every zip from the `raw-html` release and merge into data/raw/ (names never collide)."""
    if not shutil.which("gh"):
        sys.exit("Needs the GitHub CLI (https://cli.github.com) logged in: gh auth login")
    target = RAW / "_release"
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(["gh", "release", "download", "raw-html", "--dir", str(target), "--clobber"], cwd=ROOT, check=True)
    for z in sorted(target.glob("*.zip")):
        with zipfile.ZipFile(z) as archive:
            archive.extractall(ROOT)
    pages = sum(1 for _ in RAW.rglob("*.html"))
    print(f"Merged {len(list(target.glob('*.zip')))} zips into data/raw/ ({pages:,} archived pages).")


def fda_csv(args):
    """Archived copies of the FDA's own CSV export, captured during the list-page gap."""
    cdx = requests.get("https://web.archive.org/cdx/search/cdx", timeout=120, params=dict(
        url=CSV_URL, matchType="prefix", filter=["statuscode:200", "mimetype:text/csv"],
        fl="timestamp,original", collapse="digest", output="json")).json()[1:]
    wanted = [(ts, url) for ts, url in cdx if args.start <= ts[:8] < args.end]
    out = RAW / "csv"
    out.mkdir(parents=True, exist_ok=True)
    got = 0
    for ts, url in wanted:
        dest = out / f"{ts}.csv"
        if dest.exists() and dest.stat().st_size > 1000:
            got += 1
            continue
        for attempt in range(3):
            r = requests.get(f"https://web.archive.org/web/{ts}id_/{url}", timeout=90)
            if r.ok and len(r.content) > 1000:
                dest.write_bytes(r.content)
                got += 1
                break
            time.sleep(15 * (attempt + 1))
        time.sleep(6)  # polite: the archive refuses bursts
    print(f"{got}/{len(wanted)} CSV copies in {out}")


def prices(args):
    run(ROOT / "src/06_prices.py", *[x for e in PRICE_EXCLUSIONS for x in ("--exclude", e)], "--vendor", args.vendor)


def rebuild(_):
    run(ROOT / "src/01_wayback_index.py")
    run(ROOT / "src/02_fetch.py", "--which", "main", "--years", "2014-2026", "--workers", "3", "--adaptive", "--rps", "0.2")
    run(ROOT / "src/02_fetch.py", "--which", "detail", "--per-week", "--workers", "3", "--adaptive", "--rps", "0.2")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("release").set_defaults(fn=release)
    p = sub.add_parser("fda-csv")
    p.add_argument("--start", default="20240901")
    p.add_argument("--end", default="20250930")
    p.set_defaults(fn=fda_csv)
    p = sub.add_parser("prices")
    p.add_argument("--vendor", choices=["webull", "yfinance"], default="webull")
    p.set_defaults(fn=prices)
    sub.add_parser("rebuild").set_defaults(fn=rebuild)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
