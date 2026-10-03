"""Step 2: download archived pages (resumable, polite: at most 1 request/second).

Main page: one capture per ISO week. Detail pages: every unique capture (already de-duplicated by digest).
Files go to data/raw/{main,detail}/{YYYY}/ (gitignored). Re-running skips anything already downloaded.

Usage:
  python src/02_fetch.py --which main --years 2019          # thin slice first (--year also works)
  python src/02_fetch.py --which main --years 2014-2024     # a range of years
  python src/02_fetch.py --which detail --years 2019 --shard 1/4   # every 4th row, starting at row 1
  python src/02_fetch.py --which all                        # everything (run in background)
  python src/02_fetch.py --only-needed                      # detail pages needed by shortage_events.csv only
  python src/02_fetch.py --which detail --years 2020,2022 --workers 8   # team split by years, faster

--workers N keeps N requests in flight (Wayback answers in ~9 s, so one at a time reaches only ~0.1/s);
request starts are still capped at --rps per process (default and maximum: 1/config.WAYBACK_SLEEP_SEC).
The Wayback Machine limits each IP to roughly 10-15 page requests/minute and refuses connections for a few
minutes when exceeded, so --rps 0.15 is a safe fixed rate. --adaptive starts there, speeds up slowly while every
request succeeds, and halves the rate on any refusal or error (never above --rps).
--per-week keeps one detail capture per product per ISO week (the latest; weeks already on disk are skipped),
about 40% fewer requests, and orders the work: captures near a shortage event first, then the rest,
holdout-dated captures last.

--only-needed: for each event in shortage_events.csv (all its product names), match detail captures by
normalized AI= and fetch the latest capture on/before public_date + 7 days, plus the next capture after it
(backup). If there is none on/before, the first later capture is fetched. Prints a coverage report by year.
"""
import argparse
import hashlib
import importlib.util
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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
    """data/raw/{main|detail}/{YYYY}/... : one folder per capture year, so team members can fetch
    different years in parallel and merge by copying folders (file names never collide)."""
    if kind == "main":
        return RAW / "main" / ts[:4] / f"{ts}.html"
    h = hashlib.sha1(original.encode()).hexdigest()[:12]
    return RAW / "detail" / ts[:4] / f"{ts}_{h}.html"


def _parse_main():
    """src/03_parse_main.py as a module, for its AI= normalization (shared with the event parser)."""
    spec = importlib.util.spec_from_file_location("parse_main", ROOT / "src" / "03_parse_main.py")
    pm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pm)
    return pm


def per_week(idx: pd.DataFrame, before_days: int = 30, after_days: int = 60) -> pd.DataFrame:
    """One detail capture per (product, ISO week), skipping weeks already on disk, ordered by value:
    captures within [public_date - before_days, public_date + after_days] of an event first, then the rest
    chronologically, holdout-dated captures last."""
    pm = _parse_main()
    idx = idx.copy()
    idx["ai_key"] = idx["original"].map(pm.ai_key)
    idx["date"] = pd.to_datetime(idx["timestamp"].str[:8], format="%Y%m%d")
    iso = idx["date"].dt.isocalendar()
    idx["wk"] = iso["year"].astype(str) + "-" + iso["week"].astype(str).str.zfill(2)
    idx["have"] = [out_path("detail", t, o).exists() for t, o in zip(idx["timestamp"], idx["original"])]
    done = idx.groupby(["ai_key", "wk"])["have"].transform("any")
    picks = idx[~done].sort_values("timestamp").groupby(["ai_key", "wk"]).tail(1)

    ev = pd.read_csv(PROC / "shortage_events.csv", keep_default_na=False, parse_dates=["public_date"])
    win = ev[["ai_key", "public_date"]].merge(picks[["ai_key", "date"]].reset_index(), on="ai_key")
    near = win[(win["date"] >= win["public_date"] - pd.Timedelta(days=before_days))
               & (win["date"] <= win["public_date"] + pd.Timedelta(days=after_days))]["index"]
    picks = picks.assign(near=picks.index.isin(near),
                         holdout=picks["date"] >= pd.Timestamp(config.OOS_START))
    picks = picks.sort_values(["holdout", "near", "timestamp"], ascending=[True, False, True])
    print(f"--per-week: {len(idx):,} captures -> {len(picks):,} product-weeks to fetch "
          f"({int(done.sum()):,} captures in weeks already on disk); near events: {int(picks['near'].sum()):,}, "
          f"holdout-dated: {int(picks['holdout'].sum()):,}")
    return picks


def needed_detail(idx: pd.DataFrame, window_days: int = 7) -> pd.DataFrame:
    """Detail captures needed per event; prints coverage by year. Holdout-dated captures are counted, not shown."""
    pm = _parse_main()  # same AI= normalization as the main-page parser

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


class RateLimiter:
    """At most `rps` request starts per second across all worker threads; backoff pauses everyone.

    adaptive=True: start at min(rps, SAFE_RPS) and add ADAPT_STEP after every ADAPT_STREAK successes (never above
    rps). Rate-limit signals (HTTP 429, connection refused) halve the rate; slowness (timeouts, 5xx) only trims it
    by 15%, since that is the archive being busy rather than us being too fast. Never below ADAPT_FLOOR."""
    SAFE_RPS, ADAPT_STEP, ADAPT_STREAK, ADAPT_FLOOR = 0.15, 0.01, 10, 0.05
    CUT = {"429": 0.5, "refused": 0.5, "timeout": 0.85, "5xx": 0.85, "other": 0.85}

    def __init__(self, rps: float, adaptive: bool = False):
        self.max_rps = rps
        self.rps = min(rps, self.SAFE_RPS) if adaptive else rps
        self.adaptive = adaptive
        self.ok_streak = 0
        self.fails = {k: 0 for k in self.CUT}
        self.lock = threading.Lock()
        self.next_t = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next_t)
            self.next_t = t + 1.0 / self.rps
        time.sleep(max(0.0, t - now))

    def success(self):
        if not self.adaptive:
            return
        with self.lock:
            self.ok_streak += 1
            if self.ok_streak >= self.ADAPT_STREAK:
                self.rps = min(self.max_rps, self.rps + self.ADAPT_STEP)
                self.ok_streak = 0

    def backoff(self, seconds: float, kind: str = "other"):
        with self.lock:
            self.fails[kind] = self.fails.get(kind, 0) + 1
            self.next_t = max(self.next_t, time.monotonic() + seconds)
            if self.adaptive:
                self.rps = max(self.ADAPT_FLOOR, self.rps * self.CUT.get(kind, 0.85))
                self.ok_streak = 0


def fetch(ts: str, original: str, dest: Path, log: list, limiter: RateLimiter | None = None):
    if dest.exists() and dest.stat().st_size > 500:
        log.append((ts, original, "ok", dest.stat().st_size))  # already on disk; keeps the log current
        return
    url = f"https://web.archive.org/web/{ts}id_/{original}"  # id_ = original HTML, no toolbar
    for attempt in range(5):
        if limiter:
            limiter.wait()
        kind = "other"
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            if r.status_code == 200 and len(r.content) > 500:
                if limiter:
                    limiter.success()
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content)
                log.append((ts, original, "ok", len(r.content)))
                return
            if r.status_code in (404, 410):
                log.append((ts, original, f"http_{r.status_code}", 0))
                return
            kind = "429" if r.status_code == 429 else "5xx" if r.status_code >= 500 else "other"
        except requests.Timeout:
            kind = "timeout"
        except requests.ConnectionError as e:
            kind = "refused" if "refused" in str(e).lower() else "other"
        except requests.RequestException:
            pass
        if limiter:
            limiter.backoff(5 * (attempt + 1), kind)  # pause all workers; adaptive rate cut depends on kind
        else:
            time.sleep(5 * (attempt + 1))
    log.append((ts, original, "failed", 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", choices=["main", "detail", "all"], default="main")
    ap.add_argument("--years", "--year", dest="years", default=None,
                    help='"2019", a range "2014-2019", or a list "2020,2022" (ranges allowed in the list)')
    ap.add_argument("--only-needed", action="store_true",
                    help="detail pages for shortage_events.csv only (implies --which detail)")
    ap.add_argument("--shard", default=None, help='"k/n": keep every n-th row of the filtered index, from row k (1-based)')
    ap.add_argument("--workers", type=int, default=1, help="requests in flight (default 1)")
    ap.add_argument("--rps", type=float, default=1.0 / config.WAYBACK_SLEEP_SEC,
                    help="max request starts per second for this process (cannot exceed the config limit)")
    ap.add_argument("--adaptive", action="store_true",
                    help="start at a safe rate, speed up while requests succeed, halve on refusals (max --rps)")
    ap.add_argument("--per-week", action="store_true",
                    help="detail only: one capture per product per ISO week, most useful first")
    args = ap.parse_args()

    max_rps = 1.0 / config.WAYBACK_SLEEP_SEC
    if not 0 < args.rps <= max_rps:
        ap.error(f"--rps must be in (0, {max_rps:g}] (config.WAYBACK_SLEEP_SEC)")
    if args.workers < 1:
        ap.error("--workers must be >= 1")

    years = None
    if args.years:
        years = set()
        for part in args.years.split(","):
            lo, _, hi = part.strip().partition("-")
            years |= {str(y) for y in range(int(lo), int(hi or lo) + 1)}
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
        if args.per_week and kind == "detail":
            idx = per_week(idx)
        if args.shard:
            idx = idx.iloc[k - 1::n]
        print(f"{kind}: {len(idx):,} captures to check")
        log, limiter, done = [], RateLimiter(args.rps, adaptive=args.adaptive), [0]
        t0 = time.monotonic()

        def one(row):
            fetch(row.timestamp, row.original, out_path(kind, row.timestamp, row.original), log, limiter)
            with limiter.lock:
                done[0] += 1
                if done[0] % 50 == 0:
                    rate = done[0] / max(time.monotonic() - t0, 1e-9) * 60
                    fails = " ".join(f"{k}={v}" for k, v in limiter.fails.items() if v) or "none"
                    print(f"  {done[0]:,}/{len(idx):,}  ({rate:.0f}/min, rps {limiter.rps:.2f}, failures: {fails})",
                          flush=True)

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(one, idx.itertuples(index=False)))
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
