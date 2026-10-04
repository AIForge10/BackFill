"""One frozen OOS batch: registered primary plus four disclosed strict comparisons."""
import argparse
import json
import sys
import uuid
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backfill.analysis import mean_inference, metrics
from backfill.engine import run_portfolio, schedule_lots
from backfill.guardrails import fingerprint, finish_holdout, log_run, require_oos_freeze, reserve_holdout
from backfill.prices import load_cache, required_symbols, sha256
from backfill.settings import Settings
from strict_timing import delay_requests, lot_net_pnl

SPECS = (("registered_primary", 0, 60, False),
         ("strict_wait20_hold5_with_amrx", 20, 5, False),
         ("strict_wait20_hold5_without_amrx", 20, 5, True),
         ("strict_immediate_hold250_with_amrx", 0, 250, False),
         ("strict_immediate_hold250_without_amrx", 0, 250, True))


def requests(frame, settings):
    result = frame.drop_duplicates(["event_id", "ticker"]).copy()
    result["weight"] = settings.event_weight / result.groupby("event_id").ticker.transform("nunique")
    result["hedge"] = result.benchmark
    return result.assign(hold_days=settings.hold_days)


def validate_primary(identity_file, source_root):
    identity = json.loads(identity_file.read_text())
    for raw, expected in identity["files"].items():
        path = Path(raw)
        if path.suffix == ".py" or path.name in {"HYPOTHESIS.md", "company_ticker_map.csv"}:
            frozen = ROOT / path.relative_to(source_root)
            if sha256(frozen) != expected:
                raise ValueError(f"Registered primary code/map changed: {frozen}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-root", type=Path, required=True,
                    help="original shared repository holding the canonical one-attempt lock")
    ap.add_argument("--primary-identity", type=Path, required=True)
    args = ap.parse_args()
    require_oos_freeze(ROOT)
    validate_primary(args.primary_identity, args.source_root)
    settings = replace(Settings(), start="2024-10-01", end="2026-10-01", final=True)
    inputs = ROOT / "data/raw/oos/signals"
    cache = ROOT / "data/raw/prices/oos"
    files = [*sorted(inputs.glob("*.csv")), inputs / "preparation.json", cache / "manifest.json",
             args.primary_identity, ROOT / "research/strict_oos_protocol.md", ROOT / "HYPOTHESIS.md",
             ROOT / "data/company_ticker_map.csv", ROOT / "config.py",
             *sorted((ROOT / "backfill").glob("*.py")), *sorted((ROOT / "research").glob("*.py"))]
    identity = fingerprint(ROOT, files, settings)
    identity.update(classification="single holdout batch; primary preserved; strict timing exploratory",
                    specifications=SPECS)
    lock = args.source_root / "results/backfill_oos_attempt.json"
    # All branches/worktrees share the original operational lock. Reserving a
    # worktree-specific path would allow a second trial and is prohibited.
    reserve_holdout(lock, identity)
    output = ROOT / "results/strict_oos" / uuid.uuid4().hex[:12]
    output.mkdir(parents=True, exist_ok=False)
    (output / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    try:
        primary = pd.read_csv(inputs / "primary.csv")
        strict = pd.read_csv(inputs / "strict.csv")
        manifest = json.loads((cache / "manifest.json").read_text())
        symbols = sorted(set(required_symbols(primary)) | {"^GSPC"})
        prices, manifest = load_cache(cache, symbols, evaluation_end=settings.end)
        rows = []
        for label, delay, hold, omit in SPECS:
            s = replace(settings, hold_days=hold)
            base = primary[primary.role.eq("winner")] if label == "registered_primary" else strict
            winners = requests(base, s)
            if omit:
                winners = winners[~winners.ticker.eq("AMRX")].copy()
            winners = delay_requests(winners, prices["^GSPC"].index, delay)
            scheduled, eligibility = schedule_lots(winners, prices, s, manifest.get("exclusions", {}))
            folder = output / label
            folder.mkdir()
            eligibility.to_csv(folder / "eligibility.csv", index=False)
            winners.to_csv(folder / "requests.csv", index=False)
            if not scheduled:
                rows.append(dict(specification=label, status="no eligible completed lots", lots=0,
                                 events=0, entry_delay_sessions=delay, hold_days=hold))
                continue
            events = {lot["event_id"] for lot in scheduled}
            controls = requests(primary[primary.role.eq("placebo") & primary.event_id.isin(events)], s)
            controls = delay_requests(controls, prices["^GSPC"].index, delay)
            for cost in (1., 2.):
                cs = replace(s, cost_multiplier=cost)
                results = {}
                for role, req in (("winners", winners), ("controls", controls)):
                    directory = folder / f"costs{int(cost)}" / role
                    directory.mkdir(parents=True)
                    trial = f"{output.name}:{label}:{role}:costs{int(cost)}"
                    log_run(args.source_root / "results/variants_log.csv", trial, label + "/" + role,
                            cs, inputs / "strict.csv", prices.keys(), "started", identity=identity)
                    try:
                        result = run_portfolio(req, prices, cs, exclusions=manifest.get("exclusions", {}))
                        summary = metrics(result, cs)
                        lots = lot_net_pnl(result, prices, cs)
                        for name, frame in (("equity", result.equity), ("lots", lots),
                                            ("trades", result.trades), ("eligibility", result.eligibility)):
                            frame.to_csv(directory / (name + ".csv"), index=name == "equity")
                        (directory / "metrics.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
                        log_run(args.source_root / "results/variants_log.csv", trial, label + "/" + role,
                                cs, inputs / "strict.csv", prices.keys(), "completed", summary=summary, identity=identity)
                        results[role] = (result, summary, lots)
                    except Exception as exc:
                        log_run(args.source_root / "results/variants_log.csv", trial, label + "/" + role,
                                cs, inputs / "strict.csv", prices.keys(), "failed", summary={"error": str(exc)}, identity=identity)
                        raise
                winner, summary, lots = results["winners"]
                control = results["controls"][0]
                if not winner.equity.index.equals(control.equity.index):
                    raise ValueError("Winner/control calendar mismatch")
                paired = winner.equity.daily_return - control.equity.daily_return
                comparison = mean_inference(paired, lags=max(60, hold))
                paired.to_csv(folder / f"winner_minus_controls_costs{int(cost)}.csv")
                rows.append(dict(specification=label, status="completed", cost_multiplier=cost,
                    entry_delay_sessions=delay, hold_days=hold, lots=len(lots), events=lots.event_id.nunique(),
                    unique_exposures=len(lots[["ticker", "trade_date"]].drop_duplicates()),
                    average_net_lot_return=lots.net_lot_return.mean(), median_net_lot_return=lots.net_lot_return.median(),
                    winning_lots=int(lots.net_pnl.gt(0).sum()), annualized_return=summary["annualized_return"],
                    annualized_volatility=summary["annualized_volatility"], sharpe=summary["sharpe"],
                    max_drawdown=summary["max_drawdown"], turnover=summary["annualized_turnover"],
                    winner_p=summary["inference"]["p_value"], paired_p=comparison["p_value"]))
        for path, expected in identity["files"].items():
            if sha256(path) != expected:
                raise ValueError(f"Frozen input changed during evaluation: {path}")
        table = pd.DataFrame(rows)
        table.to_csv(output / "summary.csv", index=False)
        finish_holdout(lock, "completed", {"bundle": str(output)})
        print(table.to_string(index=False))
        print("OUTPUT", output)
    except Exception as exc:
        finish_holdout(lock, "failed", {"error": str(exc), "bundle": str(output)})
        raise


if __name__ == "__main__":
    main()
