"""Step 1: list every archived capture of the FDA Drug Shortages pages (Wayback CDX API).

Outputs:
  data/processed/index_main.csv    (main list page, exact URL)
  data/processed/index_detail.csv  (per-drug detail pages, URL prefix)
  data/processed/coverage_main.csv (main page: per-year coverage + largest gaps, for the note)
Prints a per-year coverage table (goes into the note).

Usage: python src/01_wayback_index.py
"""
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config  # noqa: E402

CDX = "https://web.archive.org/cdx/search/cdx"
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

TARGETS = {
    "main": ("accessdata.fda.gov/scripts/drugshortages/default.cfm", "exact"),
    "detail": ("accessdata.fda.gov/scripts/drugshortages/dsp_ActiveIngredientDetails.cfm", "prefix"),
}
FIELDS = ["timestamp", "original", "statuscode", "digest", "mimetype"]


def cdx_query(url: str, match_type: str, page_size: int = 5000) -> pd.DataFrame:
    """Page through the CDX API using resume keys. Retries politely on errors."""
    rows, resume_key = [], None
    while True:
        params = {
            "url": url,
            "matchType": match_type,
            "output": "json",
            "fl": ",".join(FIELDS),
            "filter": "statuscode:200",
            "collapse": "digest",
            "limit": page_size,
            "showResumeKey": "true",
        }
        if resume_key:
            params["resumeKey"] = resume_key
        for attempt in range(6):
            try:
                r = requests.get(CDX, params=params, timeout=120)
                if r.status_code == 200 and r.text.strip().startswith("["):
                    break
                print(f"  CDX status {r.status_code} (archive may be offline); retry {attempt + 1}")
            except requests.RequestException as e:
                print(f"  CDX error {e}; retry {attempt + 1}")
            time.sleep(10 * (attempt + 1))
        else:
            raise RuntimeError("CDX API unavailable. The Internet Archive may be offline; try again later.")

        data = r.json()
        if not data:
            break
        header, body = data[0], data[1:]
        resume_key = None
        # With showResumeKey, the last rows are [] then [resume_key]
        if len(body) >= 2 and body[-2] == [] and len(body[-1]) == 1:
            resume_key = body[-1][0]
            body = body[:-2]
        rows.extend(r_ for r_ in body if len(r_) == len(header))
        print(f"  fetched {len(rows):,} rows so far")
        if not resume_key:
            break
        time.sleep(config.WAYBACK_SLEEP_SEC)
    return pd.DataFrame(rows, columns=FIELDS)


def coverage(df: pd.DataFrame, n_top: int = 5):
    """Per-year coverage plus the largest gaps between consecutive captures.

    Gaps are measured over the full series, so a gap spanning a year boundary counts
    toward every year it overlaps (e.g. Sep 2024 -> Sep 2025 shows in both 2024 and 2025).
    """
    dates = df["date"].sort_values().reset_index(drop=True)
    gaps = pd.DataFrame({"gap_start": dates.shift(), "gap_end": dates})
    gaps["gap_days"] = (gaps["gap_end"] - gaps["gap_start"]).dt.days
    gaps = gaps.dropna()

    cov = df.groupby(df["date"].dt.year).agg(
        captures=("timestamp", "size"),
        first=("date", "min"),
        last=("date", "max"),
    )
    cov["max_gap_days"] = [
        gaps.loc[(gaps["gap_start"].dt.year <= y) & (gaps["gap_end"].dt.year >= y), "gap_days"].max()
        for y in cov.index
    ]
    cov.index.name = "year"
    top = gaps.nlargest(n_top, "gap_days").reset_index(drop=True)
    return cov, top


def main():
    for name, (url, match_type) in TARGETS.items():
        print(f"Indexing {name}: {url} ({match_type})")
        df = cdx_query(url, match_type)
        df = df[df["mimetype"].str.contains("html", na=False)].copy()
        df["date"] = pd.to_datetime(df["timestamp"].str[:8], format="%Y%m%d")
        df = df.sort_values("timestamp").drop_duplicates("digest")
        path = OUT / f"index_{name}.csv"
        df.to_csv(path, index=False)
        cov, top = coverage(df)
        print(f"\nSaved {len(df):,} captures -> {path}\nCoverage by year:\n{cov}\n"
              f"Largest gaps:\n{top}\n")
        if name == "main":
            out = pd.concat([
                cov.reset_index().assign(table="year"),
                top.assign(table="top_gap"),
            ])[["table", "year", "captures", "first", "last", "max_gap_days",
                "gap_start", "gap_end", "gap_days"]]
            out = out.astype({"year": "Int64", "captures": "Int64", "max_gap_days": "Int64", "gap_days": "Int64"})
            out.to_csv(OUT / "coverage_main.csv", index=False)
            print(f"Saved coverage table -> {OUT / 'coverage_main.csv'}\n")


if __name__ == "__main__":
    main()
