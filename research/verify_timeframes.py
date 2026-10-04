"""A bounded, disclosed in-sample screen using the real offline portfolio engine.

This is not a holdout evaluator. The default source is the already-inspected
primary bundle; no vendors are called and no original output is overwritten.
"""
import argparse
import hashlib
import json
import sys
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))

from backfill.analysis import mean_inference, metrics
from backfill.engine import run_portfolio, schedule_lots
from backfill.events import active_mapping, truth
from backfill.guardrails import fingerprint, log_run
from backfill.prices import load_cache
from backfill.settings import Settings

HORIZONS = (1, 5, 20, 40, 60, 120, 250)
GROUPS = ("all_winners", "generic_winners", "injectable_winners")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def holm_with_prior(pvalues, prior_tests=27):
    """Conservatively include prior inspected tests as p=1 in this family.

    25 prior gross-grid cells plus the secondary and earnings tests. Prior unit
    p-values retain those trials in the multiplicity burden without asserting
    that the new HAC statistics can replace their original statistics.
    """
    values = np.asarray([1.0] * prior_tests + list(pvalues), dtype=float)
    order = np.argsort(values)
    adjusted = np.empty(len(values))
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (len(values) - rank) * values[index]))
        adjusted[index] = running
    return adjusted[prior_tests:]


def requests_for(ledger, mapping, group, horizon, settings):
    winners = ledger[(ledger.role == "winner") & (ledger.country == "US")].copy()
    if group == "generic_winners":
        def generic(row):
            owners = active_mapping(mapping, row.trade_ready_date)
            owners = owners[owners.ticker == row.ticker]
            labels = set(owners.is_generic_maker.map(truth))
            if len(labels) != 1:
                raise ValueError(f"Missing/ambiguous generic classification: {row.ticker}")
            return next(iter(labels))
        winners = winners[winners.apply(generic, axis=1)]
    elif group == "injectable_winners":
        # A frozen formulation-name heuristic, NOT a manufacturer-specialization flag.
        winners = winners[winners['product'].str.contains(r"injection|injectable", case=False, na=False)]
    elif group != "all_winners":
        raise ValueError(group)
    winners = winners.drop_duplicates(["event_id", "ticker"])
    winners["weight"] = settings.event_weight / winners.groupby("event_id").ticker.transform("nunique")
    winners["hold_days"] = horizon
    winners["hedge"] = winners.benchmark
    return winners


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--bundle", default="222584aadc36")
    args = parser.parse_args()
    source = args.data_root.resolve()
    primary = source / "results/backfill" / args.bundle
    original_identity = json.loads((primary / "identity.json").read_text())
    if original_identity["settings"].get("final") or original_identity["settings"]["end"] != "2024-09-30":
        raise ValueError("Only the fixed in-sample primary source is permitted.")
    # Ensure this review uses the same engine, settings, map and source vintage.
    for raw, expected in original_identity["files"].items():
        if not Path(raw).exists() or sha(raw) != expected:
            raise ValueError(f"Primary inputs changed: {raw}")
    for raw, expected in original_identity["files"].items():
        relative = Path(raw).relative_to(source)
        if relative.parts[0] in {"backfill", "strategies"} and sha(CODE_ROOT / relative) != expected:
            raise ValueError(f"Review implementation differs from the evaluated primary: {relative}")
    settings = Settings()
    if settings.final or settings.end != "2024-09-30":
        raise ValueError("In-sample-only settings required.")
    ledger_file = primary / "primary/inputs/events.csv"
    ledger = pd.read_csv(ledger_file)
    mapping_file = source / "data/company_ticker_map.csv"
    mapping = pd.read_csv(mapping_file, keep_default_na=False)
    cache = source / "data/raw/prices/is"
    manifest = json.loads((cache / "manifest.json").read_text())
    prices, manifest = load_cache(cache, sorted(manifest["symbols"]), evaluation_end=settings.end)
    exclusions = manifest.get("exclusions", {})
    run_id = uuid.uuid4().hex[:12]
    output = CODE_ROOT / "results/timeframe_verification" / run_id
    output.mkdir(parents=True, exist_ok=False)
    protocol_file = Path(__file__).with_name("timeframe_verification_protocol.md")
    identity = fingerprint(CODE_ROOT, [Path(__file__), protocol_file, ledger_file, mapping_file,
                                      cache / "manifest.json"], settings)
    identity["origin_primary_bundle"] = args.bundle
    identity["classification"] = "post-primary exploratory; in-sample only"
    identity["started_at"] = datetime.now(timezone.utc).isoformat()
    (output / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    ledger.to_csv(output / "source_ledger.csv", index=False)
    log = CODE_ROOT / "results/variants_log.csv"
    cells = []
    results = {}

    def evaluate(requests, label, s):
        directory = output / label
        directory.mkdir(parents=True, exist_ok=False)
        events_file = directory / "requests.csv"
        requests.to_csv(events_file, index=False)
        trial = f"{run_id}:{label}"
        log_run(log, trial, f"exploratory_timeframes/{label}", s, events_file, prices.keys(), "started", identity=identity)
        try:
            result = run_portfolio(requests, prices, s, exclusions=exclusions)
            summary = metrics(result, s)
            for name, frame in [("equity", result.equity), ("lots", result.lots),
                                ("trades", result.trades), ("eligibility", result.eligibility)]:
                frame.to_csv(directory / f"{name}.csv", index=name == "equity")
            (directory / "metrics.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
            log_run(log, trial, f"exploratory_timeframes/{label}", s, events_file, prices.keys(), "completed",
                    summary=summary, identity=identity)
            return result, summary
        except Exception as exc:
            log_run(log, trial, f"exploratory_timeframes/{label}", s, events_file, prices.keys(), "failed",
                    summary={"error": str(exc)}, identity=identity)
            raise

    for group in GROUPS:
        for horizon in HORIZONS:
            started = time.monotonic()
            s = replace(settings, hold_days=horizon)
            winners = requests_for(ledger, mapping, group, horizon, s)
            scheduled, _ = schedule_lots(winners, prices, s, exclusions)
            eligible_events = {r["event_id"] for r in scheduled}
            if not eligible_events:
                raise ValueError(f"No eligible winner events for {group}/{horizon}")
            controls = ledger[(ledger.role == "placebo") & (ledger.country == "US") &
                              ledger.event_id.isin(eligible_events)].drop_duplicates(["event_id", "ticker"]).copy()
            controls["weight"] = s.event_weight / controls.groupby("event_id").ticker.transform("nunique")
            controls["hold_days"] = horizon
            controls["hedge"] = controls.benchmark
            if set(controls.event_id) != eligible_events:
                raise ValueError("Every eligible winner event must have matched controls.")
            for cost in (1.0, 2.0):
                cost_settings = replace(s, cost_multiplier=cost)
                prefix = f"{group}/hold{horizon}/costs{int(cost)}"
                result, summary = evaluate(winners, prefix + "/winners", cost_settings)
                control, _ = evaluate(controls, prefix + "/controls", cost_settings)
                paired = result.equity.daily_return - control.equity.daily_return
                paired.to_csv(output / prefix / "winner_minus_control.csv", header=["daily_return"])
                contrast = mean_inference(paired, lags=max(60, horizon))
                (output / prefix / "comparison.json").write_text(json.dumps(contrast, indent=2) + "\n")
                if group == "all_winners" and horizon == 60 and cost == 1:
                    reference = json.loads((primary / "primary/winner/costs1/metrics.json").read_text())
                    for key in ("annualized_return", "sharpe", "max_drawdown", "transaction_cost", "positions"):
                        if not np.isclose(summary[key], reference[key], rtol=1e-10, atol=1e-10):
                            raise ValueError(f"Primary reproduction differs on {key}")
                exposures = result.lots[["ticker", "trade_date"]].drop_duplicates()
                row = dict(group=group, hold_days=horizon, cost_multiplier=cost,
                           events=summary["events"], lots=summary["positions"], unique_exposures=len(exposures),
                           tickers=result.lots.ticker.nunique(), sharpe=summary["sharpe"],
                           annualized_return=summary["annualized_return"], max_drawdown=summary["max_drawdown"],
                           winner_mean_daily=summary["inference"]["mean_daily"],
                           winner_p=summary["inference"]["p_value"],
                           paired_mean_daily=contrast["mean_daily"], paired_p=contrast["p_value"])
                cells.append(row)
                results[(group, horizon, cost)] = (winners, controls, result, control)
                pd.DataFrame(cells).to_csv(output / "summary_running.csv", index=False)
            print(f"{group:19} h={horizon:3}: Sharpe {cells[-2]['sharpe']:+.2f}, doubled {cells[-1]['sharpe']:+.2f}, "
                  f"winner p={cells[-2]['winner_p']:.3f}, paired p={cells[-2]['paired_p']:.3f}, "
                  f"{cells[-2]['events']} events, {time.monotonic()-started:.1f}s", flush=True)
    table = pd.DataFrame(cells)
    flat = table[["winner_p", "paired_p"]].fillna(1.0).to_numpy().ravel()
    adjusted = holm_with_prior(flat).reshape(-1, 2)
    table["winner_p_adjusted"] = adjusted[:, 0]
    table["paired_p_adjusted"] = adjusted[:, 1]
    table["statistical_gate"] = ((table.winner_mean_daily > 0) & (table.paired_mean_daily > 0) &
                                  (table.winner_p_adjusted < 0.05) & (table.paired_p_adjusted < 0.05) &
                                  (table.unique_exposures >= 10) & (table.tickers >= 3))
    nominees = []
    for (group, horizon), rows in table.groupby(["group", "hold_days"]):
        if rows.statistical_gate.all():
            nominees.append((group, int(horizon)))
    (output / "screen.json").write_text(json.dumps({"new_strategy_cells":21,"cost_scenarios":2,
        "new_mean_tests":84,"prior_inspected_tests_counted":27,"statistical_nominees":nominees,
        "interpretation":"Exploratory screen, not independent confirmation. No candidate is verified merely by passing this screen.",
        "next_gate":"Nominees require same-sign nearby horizons and leave-one-company/year-out net portfolio checks before promotion."},indent=2)+"\n")
    table.to_csv(output / "summary.csv", index=False)
    print("OUTPUT",output,flush=True)
    print("STATISTICAL NOMINEES",nominees,flush=True)


if __name__ == "__main__":
    main()
