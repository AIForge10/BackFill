"""Step 2: download archived pages (resumable, polite: ~1 request/second).

Main page: one capture per ISO week. Detail pages: every unique capture (already de-duplicated by digest).
Files go to data/raw/ (gitignored). Re-running skips anything already downloaded.

Usage:
  python src/02_fetch.py --which main --years 2019          # thin slice first (--year also works)
  python src/02_fetch.py --which main --years 2014-2024     # a range of years
  python src/02_fetch.py --which detail --years 2019 --shard 1/4   # every 4th row, starting at row 1
  python src/02_fetch.py --which all                        # everything (run in background)
  python src/02_fetch.py --only-needed                      # detail pages needed by shortage_events.csv only

--only-needed: for each event in shortage_events.csv (all its product names), match detail captures by
normalized AI= and fetch the latest capture on/before public_date + 7 days, plus the next capture after it
(backup). If there is none on/before, the first later capture is fetched. Prints a coverage report by year.
"""
import argparse
import hashlib
import importlib.util
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config  # noqa: E402

PROC = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
HEADERS = {"User-Agent": "GQH2026-research (student hackathon; contact via repo)"}


def pick_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the last capture in each ISO week."""
    df = df.copy()
    df["date"] = pd.to_datetime(df["timestamp"].astype(str).str[:8], format="%Y%m%d")
    iso = df["date"].dt.isocalendar()
    df["yw"] = iso["year"].astype(str) + "-" + iso["week"].astype(str).str.zfill(2)
    return df.sort_values("timestamp").groupby("yw").tail(1)


def out_path(kind: str, ts: str, original: str) -> Path:
    if kind == "main":
        return RAW / "main" / f"{ts}.html"
    h = hashlib.sha1(original.encode()).hexdigest()[:12]
    return RAW / "detail" / f"{ts}_{h}.html"


def needed_detail(idx: pd.DataFrame, window_days: int = 7) -> pd.DataFrame:
    """Detail captures needed per event; prints coverage by year. Holdout-dated captures are counted, not shown."""
    spec = importlib.util.spec_from_file_location("parse_main", ROOT / "src" / "03_parse_main.py")
    pm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pm)  # same AI= normalization as the main-page parser

    ev = pd.read_csv(PROC / "shortage_events.csv", keep_default_na=False, parse_dates=["public_date"])
    idx = idx.copy()
    idx["ai_key"] = idx["original"].map(pm.ai_key)
    idx["date"] = pd.to_datetime(idx["timestamp"].str[:8], format="%Y%m%d")
    idx = idx.sort_values("timestamp")
    oos = pd.Timestamp(config.OOS_START)

    picks, report = [], []
    for eid, g in ev.groupby("event_id"):
        pub = g["public_date"].iloc[0]
        caps = idx[idx["ai_key"].isin(set(g["ai_key"]))]
        before = caps[caps["date"] <= pub + pd.Timedelta(days=window_days)]
        row = {"event_id": eid, "year": pub.year, "lag_days": None, "age_days": None, "after_oos": False}
        if len(before):
            first = before.iloc[-1]
            backup = caps[caps["timestamp"] > first["timestamp"]].head(1)
            row.update(coverage="on_time", age_days=(pub - first["date"]).days)
            picks += [first.to_frame().T, backup]
        elif len(caps):
            first = caps.iloc[0]
            row.update(coverage="later_only", lag_days=(first["date"] - pub).days, after_oos=first["date"] >= oos)
            picks += [caps.head(2)]
        else:
            row.update(coverage="no_match")
        report.append(row)

    rep = pd.DataFrame(report)
    tab = pd.crosstab(rep["year"], rep["coverage"]).reindex(columns=["on_time", "later_only", "no_match"], fill_value=0)
    tab["events"] = tab.sum(axis=1)
    tab.loc["all"] = tab.sum()
    print(f"Detail coverage per event (on_time = capture dated <= public_date + {window_days}d):\n{tab}\n")
    on = rep[rep["coverage"] == "on_time"]
    print(f"on_time capture age (public_date - capture date, days): median {on['age_days'].median():.0f}, "
          f"<= 30d: {(on['age_days'] <= 30).sum()}, 31-180d: {on['age_days'].between(31, 180).sum()}, "
          f"> 180d: {(on['age_days'] > 180).sum()}")
    late = rep[rep["coverage"] == "later_only"]
    lag = late.loc[~late["after_oos"], "lag_days"].astype(float)
    print(f"later_only lag (first capture - public_date, days): n={len(lag)}, median {lag.median():.0f}, "
          f"<= 30d: {(lag <= 30).sum()}, 31-90d: {lag.between(31, 90).sum()}, > 90d: {(lag > 90).sum()}; "
          f"first capture on/after {config.OOS_START} (not shown): {int(late['after_oos'].sum())}")
    if len(late):
        print("later_only by year (median lag days):", late[~late["after_oos"]].groupby("year")["lag_days"]
              .median().astype(int).to_dict())

    need = pd.concat(picks).drop_duplicates(["timestamp", "original"])
    print(f"\nCaptures to fetch: {len(need):,} ({(need['date'] >= oos).sum()} dated on/after {config.OOS_START}; "
          f"downloaded, not opened)")
    return need[["timestamp", "original"]]


def fetch(ts: str, original: str, dest: Path, log: list):
    if dest.exists() and dest.stat().st_size > 500:
        log.append((ts, original, "ok", dest.stat().st_size))  # already on disk; keeps the log current
        return
    url = f"https://web.archive.org/web/{ts}id_/{original}"  # id_ = original HTML, no toolbar
    for attempt in range(5):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            if r.status_code == 200 and len(r.content) > 500:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content)
                log.append((ts, original, "ok", len(r.content)))
                return
            if r.status_code in (404, 410):
                log.append((ts, original, f"http_{r.status_code}", 0))
                return
        except requests.RequestException:
            pass
        time.sleep(5 * (attempt + 1))  # backoff on 429/5xx/offline
    log.append((ts, original, "failed", 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", choices=["main", "detail", "all"], default="main")
    ap.add_argument("--years", "--year", dest="years", default=None,
                    help='one year ("2019") or an inclusive range ("2014-2019")')
    ap.add_argument("--only-needed", action="store_true",
                    help="detail pages for shortage_events.csv only (implies --which detail)")
    ap.add_argument("--shard", default=None, help='"k/n": keep every n-th row of the filtered index, from row k (1-based)')
    args = ap.parse_args()

    years = None
    if args.years:
        lo, _, hi = args.years.partition("-")
        years = {str(y) for y in range(int(lo), int(hi or lo) + 1)}
    if args.shard:
        k, n = (int(x) for x in args.shard.split("/"))
        if not 1 <= k <= n:
            ap.error("--shard must be k/n with 1 <= k <= n")

    kinds = ["main", "detail"] if args.which == "all" else [args.which]
    if args.only_needed:
        kinds = ["detail"]
    for kind in kinds:
        idx = pd.read_csv(PROC / f"index_{kind}.csv", dtype={"timestamp": str})
        if kind == "main":
            idx = pick_weekly(idx)
        if args.only_needed:
            idx = needed_detail(idx)
        if years:
            idx = idx[idx["timestamp"].str[:4].isin(years)]
        if args.shard:
            idx = idx.iloc[k - 1::n]
        print(f"{kind}: {len(idx):,} captures to check")
        log = []
        for i, row in enumerate(idx.itertuples(index=False), 1):
            dest = out_path(kind, row.timestamp, row.original)
            already = dest.exists() and dest.stat().st_size > 500
            fetch(row.timestamp, row.original, dest, log)
            if not already:
                time.sleep(config.WAYBACK_SLEEP_SEC)
            if i % 50 == 0:
                print(f"  {i:,}/{len(idx):,}")
        if log:
            lp = PROC / f"fetch_log_{kind}.csv"
            new = pd.DataFrame(log, columns=["timestamp", "original", "status", "bytes"])
            if lp.exists():
                new = pd.concat([pd.read_csv(lp, dtype={"timestamp": str}), new])
            new = new.drop_duplicates(["timestamp", "original"], keep="last")  # latest status per capture
            new.to_csv(lp, index=False)
            print(new["status"].value_counts().to_string())


if __name__ == "__main__":
    main()
