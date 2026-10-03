"""Exploratory grid from research/exploration_grid.md: 3 roles x 2 company types x 5 horizons.

Entry, exit and beta come from the engine's own scheduler, so timing matches the primary exactly.
Prints every cell with raw and Holm-adjusted p-values and writes them to results/exploration_grid.csv.
In-sample only (holds must end by 2024-09-30).

Usage: uv run python research/exploration_scan.py
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

HORIZONS = [1, 5, 20, 60, 120]
ROLES = {"winner": "winner", "disrupted": "disrupted", "placebo": "control"}
MIN_EVENTS = 10


def holm(p):
    p = np.asarray(p, float)
    order = np.argsort(p)
    adjusted = np.empty_like(p)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(p) - rank) * p[i]))
        adjusted[i] = running
    return adjusted


def main():
    settings = Settings()
    events = pd.read_csv(ROOT / "data/processed/shortage_events.csv")
    suppliers = pd.read_csv(ROOT / "data/processed/suppliers.csv", dtype={"capture_ts": str})
    mapping = pd.read_csv(ROOT / "data/company_ticker_map.csv", keep_default_na=False)
    ledger, _ = build_candidates(events, suppliers, mapping)
    ledger = ledger[ledger.role.isin(ROLES) & ledger.country.isin(PRIMARY_MARKETS)].drop_duplicates(
        ["event_id", "ticker", "role"])
    generic = mapping.assign(g=mapping.is_generic_maker.astype(str).str.strip().isin(["1", "true", "True"])) \
        .groupby("ticker").g.max().to_dict()
    ledger["company_type"] = ledger.ticker.map(lambda t: "generic_maker" if generic.get(t) else "diversified_major")

    cache = ROOT / "data/raw/prices/is"
    manifest = json.loads((cache / "manifest.json").read_text())
    prices, manifest = load_cache(cache, sorted(set(required_symbols(ledger)) | ({"^GSPC"} & set(manifest["symbols"]))),
                                  evaluation_end=settings.end)
    exclusions = manifest.get("exclusions", {})

    rows = []
    for h in HORIZONS:
        requests = ledger.assign(hold_days=h, hedge=ledger.benchmark, weight=0.0)
        scheduled, _ = schedule_lots(requests, prices, settings, exclusions)
        for lot in scheduled:
            s, m = prices[lot["ticker"]].adj_close, prices[lot["hedge"]].adj_close
            rs = s[lot["exit_date"]] / s[lot["trade_date"]] - 1
            rm = m[lot["exit_date"]] / m[lot["trade_date"]] - 1
            rows.append(dict(horizon=h, role=ROLES[lot["role"]], company_type=lot["company_type"],
                             event_id=lot["event_id"], ticker=lot["ticker"], hedged=rs - lot["beta"] * rm))
    positions = pd.DataFrame(rows)
    positions.to_csv(ROOT / "results/exploration_positions.csv", index=False)

    cells = []
    for (role, ctype, h), g in positions.groupby(["role", "company_type", "horizon"]):
        per_event = g.groupby("event_id").hedged.mean()
        n = len(per_event)
        t, p = stats.ttest_1samp(per_event, 0.0) if n >= 3 else (np.nan, np.nan)
        cells.append(dict(role=role, company_type=ctype, horizon=h, events=n, positions=len(g),
                          mean=per_event.mean(), median=per_event.median(), share_positive=(per_event > 0).mean(),
                          t=t, p=p))
    grid = pd.DataFrame(cells)
    testable = grid.p.notna()
    grid.loc[testable, "p_holm"] = holm(grid.loc[testable, "p"])
    grid["survives"] = (grid.p_holm < 0.05) & (grid.events >= MIN_EVENTS)
    grid = grid.sort_values(["role", "company_type", "horizon"])
    grid.to_csv(ROOT / "results/exploration_grid.csv", index=False)
    pd.set_option("display.width", 200)
    print(grid.assign(mean=grid["mean"].map("{:+.2%}".format), median=grid["median"].map("{:+.2%}".format),
                      share_positive=grid.share_positive.map("{:.0%}".format),
                      t=grid.t.round(2), p=grid.p.round(3), p_holm=grid.p_holm.round(3)).to_string(index=False))
    print(f"\ncells: {len(grid)} | testable: {int(testable.sum())} | surviving Holm p<0.05 with >= {MIN_EVENTS} events: "
          f"{int(grid.survives.sum())}")


if __name__ == "__main__":
    main()
