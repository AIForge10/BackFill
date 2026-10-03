"""Secondary hypothesis test: disrupted suppliers underperform (research/secondary_hypothesis_disrupted.md).

Uses the primary's evidence rules, engine, timing, costs and price cache unchanged. The engine trades
longs only, so it measures the beta-hedged LONG portfolio of disrupted names; the hypothesis predicts a
negative return, and the short's return is the negative minus the disclosed 50 bps/year borrow fee.
In-sample only. Every evaluation is appended to results/variants_log.csv.

Usage: uv run python research/secondary_disrupted.py
"""
import json
import sys
import uuid
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backfill.analysis import mean_inference, write_report  # noqa: E402
from backfill.engine import run_portfolio  # noqa: E402
from backfill.events import build_candidates  # noqa: E402
from backfill.guardrails import fingerprint, log_run  # noqa: E402
from backfill.pipeline import PRIMARY_MARKETS  # noqa: E402
from backfill.prices import load_cache, required_symbols  # noqa: E402
from backfill.settings import Settings  # noqa: E402

BORROW_BPS_YEAR = 50.0
SPEC = ROOT / "research/secondary_hypothesis_disrupted.md"


def disrupted_requests(settings):
    events = pd.read_csv(ROOT / "data/processed/shortage_events.csv")
    suppliers = pd.read_csv(ROOT / "data/processed/suppliers.csv", dtype={"capture_ts": str})
    mapping = pd.read_csv(ROOT / "data/company_ticker_map.csv", keep_default_na=False)
    ledger, _ = build_candidates(events, suppliers, mapping)
    d = ledger[(ledger.role == "disrupted") & ledger.country.isin(PRIMARY_MARKETS)].copy()
    d = d.drop_duplicates(["event_id", "ticker"])
    d["weight"] = settings.event_weight / d.groupby("event_id").ticker.transform("nunique")
    d["hold_days"] = settings.hold_days
    d["hedge"] = d.benchmark
    return d.reset_index(drop=True)


def main():
    settings = Settings()
    cache = ROOT / "data/raw/prices/is"
    requests = disrupted_requests(settings)
    manifest = json.loads((cache / "manifest.json").read_text())
    calendar = set(manifest["symbols"]) & {"^GSPC"}
    prices, manifest = load_cache(cache, sorted(set(required_symbols(requests)) | calendar), evaluation_end=settings.end)
    bundle_id = uuid.uuid4().hex[:12]
    out = ROOT / "results/backfill_secondary" / bundle_id
    out.mkdir(parents=True, exist_ok=False)
    requests.to_csv(out / "requests.csv", index=False)
    identity = fingerprint(ROOT, [SPEC, Path(__file__), cache / "manifest.json",
                                  ROOT / "data/processed/suppliers.csv", ROOT / "data/company_ticker_map.csv"], settings)
    (out / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    summary = {}
    for multiplier in [1.0, 2.0]:
        s = replace(settings, cost_multiplier=multiplier)
        label = f"secondary_disrupted/costs{int(multiplier)}"
        run_id = f"{bundle_id}:{label}"
        log_run(ROOT / "results/variants_log.csv", run_id, label, s, out / "requests.csv", prices.keys(), "started",
                identity=identity)
        result = run_portfolio(requests, prices, s, exclusions=manifest.get("exclusions", {}))
        metrics = write_report(result, prices, out / f"costs{int(multiplier)}", s)
        borrow = BORROW_BPS_YEAR * multiplier / 10_000 / 252
        short = -result.equity.daily_return - borrow * (result.equity.long_usd / result.equity.nav)
        metrics["short_side"] = dict(borrow_bps_year=BORROW_BPS_YEAR * multiplier,
                                     inference=mean_inference(short, lags=max(60, s.hold_days)),
                                     sharpe=float(short.mean() / short.std() * 252 ** 0.5) if short.std() > 0 else None)
        (out / f"costs{int(multiplier)}/metrics.json").write_text(json.dumps(metrics, indent=2, default=str) + "\n")
        log_run(ROOT / "results/variants_log.csv", run_id, label, s, out / "requests.csv", prices.keys(), "completed",
                summary=metrics, identity=identity)
        summary[label] = metrics
    print(f"Saved secondary bundle: {out}")


if __name__ == "__main__":
    main()
