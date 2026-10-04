"""Bounded timing exploration for all-presentations-available winners. Offline IS only."""
import json
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backfill.analysis import mean_inference, metrics
from backfill.engine import run_portfolio, schedule_lots
from backfill.guardrails import fingerprint, log_run
from backfill.prices import load_cache
from backfill.settings import Settings
from verify_timeframes import holm_with_prior, sha

DELAYS = (0, 5, 20)
HOLDS = (1, 5, 20, 40, 60, 120, 250)
VINTAGES = {"original": ROOT / "data/processed/full_availability",
            "refreshed": ROOT / "data/processed/full_availability_refreshed"}
CACHE = ROOT / "data/raw/prices/strict_timing_snapshot_20261003"


def delay_requests(requests, calendar, delay):
    if delay < 0:
        raise ValueError("Entry cannot precede the evidence-based entry.")
    result = requests.copy()
    result["evidence_ready_date"] = result.trade_ready_date
    result["entry_delay_sessions"] = delay
    if delay:
        def ready(day):
            first = int(calendar.searchsorted(pd.Timestamp(day), side="right"))
            before_fill = first + delay - 1
            # Entry beyond the fixed IS boundary gets a disclosed scheduling exclusion.
            return calendar[min(before_fill, len(calendar) - 1)].date().isoformat()
        result["trade_ready_date"] = result.trade_ready_date.map(ready)
    return result


def lot_net_pnl(result, prices, settings):
    """Realized both-leg cashflows less all costs and lagged lot-level hedge carry."""
    days = result.equity.index
    elapsed = days.to_series().diff().dt.days.fillna(0)
    output = []
    for lot in result.lots.to_dict("records"):
        trades = result.trades[result.trades.lot_id == lot["lot_id"]]
        hedge = trades[trades.leg == "hedge"]
        units = hedge.groupby("date").units.sum().reindex(days, fill_value=0).cumsum()
        previous_units = units.shift(fill_value=0)
        marks = prices[lot["hedge"]].adj_close.reindex(days).shift()
        carry = float((previous_units.abs() * marks * elapsed).fillna(0).sum()
                      * settings.hedge_carry_bps_year * settings.cost_multiplier / 10_000 / 365.25)
        pnl = -float(trades.usd_notional.sum()) - float(trades.cost.sum()) - carry
        amount = float(lot["entry_usd"])
        output.append({**lot, "transaction_cost": float(trades.cost.sum()), "hedge_carry_cost": carry,
                       "net_pnl": pnl, "net_lot_return": pnl / amount if amount > 0 else np.nan})
    frame = pd.DataFrame(output)
    if not np.isclose(frame.net_pnl.sum(), result.equity.nav.iloc[-1] - settings.initial_nav, atol=1e-7, rtol=1e-9):
        raise ValueError("Lot net P&L does not reconcile with portfolio NAV.")
    if not np.isclose(frame.hedge_carry_cost.sum(), result.equity.hedge_carry_cost.sum(), atol=1e-7, rtol=1e-9):
        raise ValueError("Lot carry does not reconcile with portfolio carry.")
    return frame


def main():
    settings = Settings()
    if settings.final or settings.end != "2024-09-30":
        raise ValueError("In-sample-only frozen settings required.")
    manifest = json.loads((CACHE / "manifest.json").read_text())
    prices, manifest = load_cache(CACHE, sorted(manifest["symbols"]), evaluation_end=settings.end)
    exclusions = manifest.get("exclusions", {})
    run_id = uuid.uuid4().hex[:12]
    output = ROOT / "results/strict_timing" / run_id
    output.mkdir(parents=True, exist_ok=False)
    paths = [Path(__file__), Path(__file__).with_name("strict_timing_protocol.md"), CACHE / "manifest.json",
             ROOT / "research/verify_timeframes.py", ROOT / "backfill/engine.py",
             ROOT / "backfill/analysis.py", ROOT / "backfill/settings.py", ROOT / "config.py"]
    for directory in VINTAGES.values():
        paths += [directory / "preparation.json", directory / "capture30/winners.csv",
                  directory / "capture30/all_candidates.csv"]
    identity = fingerprint(ROOT, paths, settings)
    identity["classification"] = "post-primary exploratory; strict availability and timing; IS only"
    (output / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    log = ROOT / "results/variants_log.csv"
    rows = []

    def evaluate(requests, label, s):
        directory = output / label
        directory.mkdir(parents=True, exist_ok=False)
        requests.to_csv(directory / "requests.csv", index=False)
        trial = f"{run_id}:{label}"
        log_run(log, trial, f"strict_timing/{label}", s, directory / "requests.csv", prices.keys(), "started", identity=identity)
        try:
            result = run_portfolio(requests, prices, s, exclusions=exclusions)
            summary = metrics(result, s)
            net_lots = lot_net_pnl(result, prices, s)
            for name, frame in [("equity", result.equity), ("lots", net_lots),
                                ("trades", result.trades), ("eligibility", result.eligibility)]:
                frame.to_csv(directory / f"{name}.csv", index=name == "equity")
            (directory / "metrics.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
            log_run(log, trial, f"strict_timing/{label}", s, directory / "requests.csv", prices.keys(), "completed", summary=summary, identity=identity)
            return result, summary, net_lots
        except Exception as exc:
            log_run(log, trial, f"strict_timing/{label}", s, directory / "requests.csv", prices.keys(), "failed", summary={"error": str(exc)}, identity=identity)
            raise

    for vintage, directory in VINTAGES.items():
        winners = pd.read_csv(directory / "capture30/winners.csv")
        winners = winners[winners.country == "US"].drop_duplicates(["event_id", "ticker"]).copy()
        ledger = pd.read_csv(directory / "capture30/all_candidates.csv")
        ledger = ledger[ledger.country == "US"]
        winners["weight"] = settings.event_weight / winners.groupby("event_id").ticker.transform("nunique")
        winners["hedge"] = winners.benchmark
        for delay in DELAYS:
            for hold in HOLDS:
                started = time.monotonic()
                s = replace(settings, hold_days=hold)
                requests = delay_requests(winners.assign(hold_days=hold), prices["^GSPC"].index, delay)
                scheduled, _ = schedule_lots(requests, prices, s, exclusions)
                eligible_events = {r["event_id"] for r in scheduled}
                if not eligible_events:
                    raise ValueError("No eligible strict winners; do not report empty portfolios.")
                controls = ledger[(ledger.role == "placebo") & ledger.event_id.isin(eligible_events)].drop_duplicates(["event_id", "ticker"]).copy()
                if set(controls.event_id) != eligible_events:
                    raise ValueError("Missing contemporaneous controls for strict winner events.")
                controls["weight"] = s.event_weight / controls.groupby("event_id").ticker.transform("nunique")
                controls["hedge"] = controls.benchmark
                controls = delay_requests(controls.assign(hold_days=hold), prices["^GSPC"].index, delay)
                for cost in (1.0, 2.0):
                    cs = replace(s, cost_multiplier=cost)
                    prefix = f"{vintage}/delay{delay}/hold{hold}/costs{int(cost)}"
                    result, summary, lots = evaluate(requests, prefix + "/winners", cs)
                    control, _, _ = evaluate(controls, prefix + "/controls", cs)
                    paired = result.equity.daily_return - control.equity.daily_return
                    paired.to_csv(output / prefix / "winner_minus_control.csv", header=["daily_return"])
                    comparison = mean_inference(paired, lags=max(60, hold))
                    (output / prefix / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
                    rows.append(dict(vintage=vintage, entry_delay_sessions=delay, hold_days=hold,
                        cost_multiplier=cost, events=summary["events"], lots=summary["positions"],
                        tickers=result.lots.ticker.nunique(), unique_exposures=len(result.lots[["ticker", "trade_date"]].drop_duplicates()),
                        annualized_return=summary["annualized_return"], annualized_volatility=summary["annualized_volatility"],
                        sharpe=summary["sharpe"], max_drawdown=summary["max_drawdown"],
                        turnover=summary["annualized_turnover"], total_net_pnl=float(lots.net_pnl.sum()),
                        average_net_lot_return=lots.net_lot_return.mean(), median_net_lot_return=lots.net_lot_return.median(),
                        winning_lots=int((lots.net_pnl > 0).sum()), winner_mean_daily=summary["inference"]["mean_daily"],
                        winner_p=summary["inference"]["p_value"], paired_mean_daily=comparison["mean_daily"], paired_p=comparison["p_value"]))
                    pd.DataFrame(rows).to_csv(output / "summary_running.csv", index=False)
                print(f"{vintage:9} delay={delay:2} hold={hold:3}: Sharpe {rows[-2]['sharpe']:+.2f}, x2 {rows[-1]['sharpe']:+.2f}, "
                      f"mean net lot {rows[-2]['average_net_lot_return']:+.2%}, winner p={rows[-2]['winner_p']:.3f}, "
                      f"{rows[-2]['events']} events, {time.monotonic()-started:.1f}s", flush=True)
    table = pd.DataFrame(rows)
    adjusted = holm_with_prior(table[["winner_p", "paired_p"]].fillna(1).to_numpy().ravel(), prior_tests=111).reshape(-1, 2)
    table["winner_p_adjusted"], table["paired_p_adjusted"] = adjusted[:, 0], adjusted[:, 1]
    table["statistical_gate"] = ((table.winner_mean_daily > 0) & (table.paired_mean_daily > 0) &
        (table.winner_p_adjusted < .05) & (table.paired_p_adjusted < .05) & (table.unique_exposures >= 10) & (table.tickers >= 3))
    table.to_csv(output / "summary.csv", index=False)
    for path, expected in identity["files"].items():
        if sha(path) != expected:
            raise ValueError(f"Concurrent input/code mutation: {path}")
    nominees = [list(key) for key, group in table.groupby(["vintage", "entry_delay_sessions", "hold_days"]) if group.statistical_gate.all()]
    (output / "screen.json").write_text(json.dumps(dict(strategy_cells=42, portfolio_evaluations=168,
        new_mean_tests=168, counted_prior_probes=111, statistical_nominees=nominees,
        caveat="Exploratory dependent comparisons on a small in-sample dataset; not independent validation."),indent=2)+"\n")
    print("OUTPUT", output, flush=True)
    print("STATISTICAL NOMINEES", nominees, flush=True)


if __name__ == "__main__":
    main()
