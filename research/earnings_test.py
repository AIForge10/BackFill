"""Test research/hypothesis_earnings_8k.md: abnormal earnings reaction (AER) after a shortage.

For each position, the first 8-K Item 2.02 filed after entry (within 120 calendar days) is the
post-shortage announcement. Reaction = return over trading days -1..+1 around the filing date minus
beta x SPY (beta from the 250 sessions before that window). Baseline = the company's mean reaction
over its other announcements, excluding the post-shortage announcements of its winner positions.
One pre-registered test (winners); disrupted and controls are descriptive. In-sample only.

Usage: uv run python research/earnings_test.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backfill.engine import schedule_lots  # noqa: E402
from backfill.events import build_candidates  # noqa: E402
from backfill.pipeline import PRIMARY_MARKETS  # noqa: E402
from backfill.prices import load_cache, required_symbols  # noqa: E402
from backfill.settings import Settings  # noqa: E402

WINDOW_DAYS = 120
ROLES = {"winner": "winner", "disrupted": "disrupted", "placebo": "control"}


def reaction(prices, calendar, ticker, day, lookback=250):
    """Window -1..+1 sessions around `day` (next session if `day` isn't one); beta-hedged vs SPY."""
    i = int(calendar.searchsorted(pd.Timestamp(day)))
    if i - 2 - lookback < 0 or i + 1 >= len(calendar):
        return None
    s, m = prices[ticker].adj_close, prices["SPY"].adj_close
    hist = calendar[i - 2 - lookback:i - 1]
    if not hist.isin(s.index).all() or not calendar[i - 2:i + 2].isin(s.index).all():
        return None
    rs_h, rm_h = s.reindex(hist).pct_change().dropna(), m.reindex(hist).pct_change().dropna()
    beta = rs_h.cov(rm_h) / rm_h.var()
    a, b = calendar[i - 2], calendar[i + 1]
    return (s[b] / s[a] - 1) - beta * (m[b] / m[a] - 1)


def main():
    settings = Settings()
    events = pd.read_csv(ROOT / "data/processed/shortage_events.csv")
    suppliers = pd.read_csv(ROOT / "data/processed/suppliers.csv", dtype={"capture_ts": str})
    mapping = pd.read_csv(ROOT / "data/company_ticker_map.csv", keep_default_na=False)
    earnings = pd.read_csv(ROOT / "data/processed/earnings_8k.csv", parse_dates=["filing_date"])
    ledger, _ = build_candidates(events, suppliers, mapping)
    ledger = ledger[ledger.role.isin(ROLES) & ledger.country.isin(PRIMARY_MARKETS)].drop_duplicates(
        ["event_id", "ticker", "role"])

    cache = ROOT / "data/raw/prices/is"
    manifest = json.loads((cache / "manifest.json").read_text())
    prices, manifest = load_cache(cache, sorted(set(required_symbols(ledger)) | ({"^GSPC"} & set(manifest["symbols"]))),
                                  evaluation_end=settings.end)
    calendar = prices["^GSPC"].index
    scheduled, _ = schedule_lots(ledger.assign(hold_days=1, hedge=ledger.benchmark, weight=0.0), prices, settings,
                                 manifest.get("exclusions", {}))

    rows, excluded = [], []
    for lot in scheduled:
        t, entry = lot["ticker"], pd.Timestamp(lot["trade_date"])
        dates = earnings[earnings.ticker == t].filing_date
        if dates.empty:
            excluded.append(dict(ticker=t, event_id=lot["event_id"], reason="no 8-K Item 2.02 dates (6-K filer or pre-2018 Teva)"))
            continue
        post = dates[(dates > entry) & (dates <= entry + pd.Timedelta(days=WINDOW_DAYS))]
        if post.empty:
            excluded.append(dict(ticker=t, event_id=lot["event_id"], reason=f"no 8-K Item 2.02 within {WINDOW_DAYS} days"))
            continue
        rows.append(dict(role=ROLES[lot["role"]], event_id=lot["event_id"], ticker=t, entry=entry.date(),
                         announcement=post.iloc[0].date()))
    pos = pd.DataFrame(rows)
    pos["reaction"] = [reaction(prices, calendar, r.ticker, r.announcement) for r in pos.itertuples()]

    treated = set(zip(pos[pos.role == "winner"].ticker, pos[pos.role == "winner"].announcement))
    baseline = {}
    for t, g in earnings.groupby("ticker"):
        if t not in prices:
            continue
        values = [reaction(prices, calendar, t, d) for d in g.filing_date if (t, d.date()) not in treated]
        values = [v for v in values if v is not None]
        baseline[t] = (float(np.mean(values)), len(values)) if values else (np.nan, 0)
    pos["baseline"] = pos.ticker.map(lambda t: baseline.get(t, (np.nan, 0))[0])
    pos["baseline_n"] = pos.ticker.map(lambda t: baseline.get(t, (np.nan, 0))[1])
    pos["aer"] = pos.reaction - pos.baseline
    pos = pos.dropna(subset=["aer"])
    pos.to_csv(ROOT / "results/earnings_8k_positions.csv", index=False)
    pd.DataFrame(excluded).to_csv(ROOT / "results/earnings_8k_excluded.csv", index=False)

    pd.set_option("display.width", 200)
    w = pos[pos.role == "winner"]
    print(w.assign(reaction=w.reaction.map("{:+.2%}".format), baseline=w.baseline.map("{:+.2%}".format),
                   aer=w.aer.map("{:+.2%}".format)).to_string(index=False))
    print("\nexcluded positions:", pd.DataFrame(excluded).groupby(["reason"]).size().to_dict() if excluded else {})
    for role, g in pos.groupby("role"):
        n = len(g)
        t, p = stats.ttest_1samp(g.aer, 0.0) if n >= 3 else (np.nan, np.nan)
        wp = stats.wilcoxon(g.aer).pvalue if n >= 3 else np.nan
        tag = "PRE-REGISTERED TEST" if role == "winner" else "descriptive"
        print(f"{role:9} n={n:3} distinct announcements={g.drop_duplicates(['ticker','announcement']).shape[0]:3} "
              f"mean AER {g.aer.mean():+.2%} median {g.aer.median():+.2%} positive {(g.aer > 0).mean():.0%} "
              f"t {t:+.2f} p {p:.3f} wilcoxon p {wp:.3f}  [{tag}]")
    print("baseline announcements per company:", {t: n for t, (_, n) in baseline.items()})


if __name__ == "__main__":
    main()
