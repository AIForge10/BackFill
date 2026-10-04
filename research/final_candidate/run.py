"""Reproduce the working candidate and two fixed exploratory comparisons offline.

No market-data acquisition, formal holdout evaluation or primary-file mutation.
"""
import hashlib
import json
import platform
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from backfill.analysis import mean_inference, write_report
from backfill.engine import run_portfolio, schedule_lots
from backfill.prices import load_cache
from backfill.settings import Settings
from research.final_candidate.strategy import RULES, build_requests, counterpart_audit, strict_presentations

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/processed/final_candidate/v1"
CACHE = ROOT / "data/raw/prices/final_candidate_v1"
OUTPUT = ROOT / "results/research/final_candidate_v1_20261004"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def validate_freeze():
    freeze = json.loads((DATA / "freeze.json").read_text())
    for name, expected in freeze["frozen_files"].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f"Frozen candidate input changed: {name}")
    if sha(CACHE / "manifest.json") != freeze["price_manifest_sha256"]:
        raise ValueError("Frozen quote manifest changed.")
    if sha(Path(__file__).with_name("SPEC.md")) != freeze["spec_sha256"]:
        raise ValueError("The pre-comparison specification changed.")
    factor_manifest = json.loads((DATA / "factor_manifest.json").read_text())
    if sha(DATA / "factors.csv") != factor_manifest["csv_sha256"]:
        raise ValueError("Frozen factor data changed.")
    return freeze


def frozen_settings():
    # Explicit rather than inheriting future config edits into this version.
    return Settings(start="2014-06-01", end="2024-09-30", hold_days=5,
        beta_lookback=250, event_weight=.05, name_cap=.08, country_cap=.30,
        sector_cap=.50, gross_cap=1.50, net_cap=.25, foreign_long_cap=.20,
        costs_bps={"US": 10, "UK": 15, "DE": 15, "CH": 15, "IN": 25},
        hedge_cost_bps=2, hedge_carry_bps_year=50, initial_nav=1_000_000,
        drawdown_trigger=.10, recovery_sessions=20, adv_lookback=60,
        adv_participation=.01, final=False)


def lot_cashflows(result, prices, settings):
    days = result.equity.index
    elapsed = days.to_series().diff().dt.days.fillna(0)
    rows = []
    for lot in result.lots.to_dict("records"):
        trades = result.trades[result.trades.lot_id == lot["lot_id"]]
        hedge = trades[trades.leg == "hedge"]
        units = hedge.groupby("date").units.sum().reindex(days, fill_value=0).cumsum()
        marks = prices[lot["hedge"]].adj_close.reindex(days).shift()
        carry = float((units.shift(fill_value=0).abs() * marks * elapsed).fillna(0).sum()
            * settings.hedge_carry_bps_year * settings.cost_multiplier / 10_000 / 365.25)
        pnl = -float(trades.usd_notional.sum()) - float(trades.cost.sum()) - carry
        rows.append({**lot, "transaction_cost": float(trades.cost.sum()), "hedge_carry_cost": carry,
            "net_pnl": pnl, "net_lot_return": pnl / lot["entry_usd"] if lot["entry_usd"] > 0 else None,
            "entry_stock_mark": float(prices[lot["ticker"]].at[lot["trade_date"], "adj_close"]),
            "exit_stock_mark": float(prices[lot["ticker"]].at[lot["exit_date"], "adj_close"]),
            "entry_SPY_mark": float(prices["SPY"].at[lot["trade_date"], "adj_close"]),
            "exit_SPY_mark": float(prices["SPY"].at[lot["exit_date"], "adj_close"])})
    frame = pd.DataFrame(rows)
    if not np.isclose(frame.net_pnl.sum(), result.equity.nav.iloc[-1] - settings.initial_nav, atol=1e-7):
        raise ValueError("Both-leg lot cashflows do not reconcile with daily NAV.")
    if not np.isclose(frame.hedge_carry_cost.sum(), result.equity.hedge_carry_cost.sum(), atol=1e-7):
        raise ValueError("Hedge carry does not reconcile.")
    return frame


def pre_information_drift(lots, prices):
    rows = []
    calendar = prices["SPY"].index
    for lot in lots.to_dict("records"):
        ready = pd.Timestamp(lot["evidence_ready_date"])
        # Last close strictly before the date on which ALL evidence was available.
        dates = calendar[calendar < ready][-251:]
        if len(dates) != 251:
            continue
        stock = prices[lot["ticker"]].adj_close.reindex(dates).pct_change(fill_method=None).dropna()
        spy = prices["SPY"].adj_close.reindex(dates).pct_change(fill_method=None).dropna()
        if len(stock) != 250 or len(spy) != 250:
            continue
        beta = float(stock.cov(spy) / spy.var())
        # Baseline beta was fitted later, so never use it for a pre-information test.
        rows.append(dict(lot_id=lot["lot_id"], event_id=lot["event_id"], ticker=lot["ticker"],
            information_date=ready.date().isoformat(), end_date=dates[-1].date().isoformat(),
            descriptive_pre_information_car=float((stock.tail(20) - beta * spy.tail(20)).sum()),
            beta_estimation="250 returns before evidence date; descriptive only"))
    return pd.DataFrame(rows)


def cluster_interval(lots):
    # Co-reported events and their stocks resample together; eight lots != eight independent tests.
    sample = lots[lots.entry_usd > 0].groupby("evidence_ready_date").net_lot_return.agg(["sum", "count"])
    rng = np.random.default_rng(20261004)
    indices = rng.integers(0, len(sample), (5000, len(sample)))
    means = sample["sum"].to_numpy()[indices].sum(axis=1) / sample["count"].to_numpy()[indices].sum(axis=1)
    return dict(information_date_clusters=len(sample), resamples=5000,
        percentile_95_ci_mean_lot=np.quantile(means, [.025, .975]).tolist(),
        note="Descriptive selected-sample interval; few clusters and timing searches prevent confirmatory interpretation.")


def omission_means(lots):
    values = {}
    for ticker in sorted(lots.ticker.unique()):
        kept = lots[lots.ticker != ticker].net_lot_return.dropna()
        values[ticker] = float(kept.mean()) if len(kept) else None
    return values


def risk_summary(result, prices):
    eq = result.equity
    name_fractions = []
    stock_trades = result.trades[result.trades.leg == "stock"]
    for ticker, trades in stock_trades.groupby("ticker"):
        units = trades.groupby("date").units.sum().reindex(eq.index, fill_value=0).cumsum()
        values = units * prices[ticker].adj_close.reindex(eq.index).ffill()
        name_fractions.append(float((values / eq.nav).max()))
    return dict(max_name_marked_fraction=max(name_fractions, default=0),
        max_long_market_sector_fraction=float((eq.long_usd / eq.nav).max()),
        max_gross_fraction=float((eq.gross_usd / eq.nav).max()),
        max_absolute_net_fraction=float((eq.net_usd / eq.nav).abs().max()),
        reduced_risk_days=int((eq.risk_scale < 1).sum()),
        note="Closing marked exposures; caps constrain new entries against preceding NAV, so prices can subsequently drift.")


def main():
    freeze = validate_freeze()
    settings = frozen_settings()
    manifest = json.loads((CACHE / "manifest.json").read_text())
    symbols = [s for s in manifest["symbols"] if s != "^GSPC"]
    prices, _ = load_cache(CACHE, symbols, evaluation_end=settings.end)
    # API key ^GSPC is only the engine's calendar slot; its quotes are SPY and never traded as ^GSPC.
    prices["^GSPC"] = prices["SPY"]
    factors = pd.read_csv(DATA / "factors.csv", index_col="month", parse_dates=True)
    winners = pd.read_csv(DATA / "winners.csv", dtype={"capture_ts": str})
    ledger = pd.read_csv(DATA / "all_candidates.csv", dtype={"capture_ts": str})
    qualified = pd.read_csv(DATA / "qualified_evidence.csv", dtype={"capture_ts": str})
    for row in winners.itertuples():
        evidence = qualified[(qualified.event_id == row.event_id) & (qualified.ticker == row.ticker)]
        if len(evidence) != 1 or not strict_presentations(evidence.iloc[0].evidence):
            raise ValueError("Strict winner does not match its frozen all-presentation audit.")
    counterparts = counterpart_audit(winners, ledger)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
    output = OUTPUT / stamp
    output.mkdir(parents=True, exist_ok=False)
    counterparts.to_csv(output / "counterpart_audit.csv", index=False)
    code = [*Path(__file__).parent.glob("*.py"), Path(__file__).with_name("SPEC.md"),
        ROOT / "backfill/engine.py", ROOT / "backfill/analysis.py", ROOT / "backfill/settings.py",
        ROOT / "backfill/prices.py", ROOT / "config.py", DATA / "freeze.json",
        DATA / "factors.csv", DATA / "factor_manifest.json", CACHE / "manifest.json"]
    protected = [ROOT / "HYPOTHESIS.md", ROOT / "config.py", ROOT / "results/backfill_oos_attempt.json",
                 ROOT / "results/variants_log.csv"]
    protected += [p for directory in (ROOT / "data/processed/backfill/primary", ROOT / "results/backfill")
                  for p in directory.rglob("*") if p.is_file()]
    before = {str(p.relative_to(ROOT)): sha(p) for p in protected if p.exists()}
    identity = dict(classification="post-result exploratory; IS-only", settings=settings.as_dict(),
        code_and_input_hashes={str(p.relative_to(ROOT)): sha(p) for p in code}, frozen_inputs=freeze,
        protected_files_before=before, python=platform.python_version(),
        dependencies={name: version(name) for name in ("numpy", "pandas", "statsmodels", "matplotlib", "yfinance")},
        calendar="Webull SPY dates, mapped into engine ^GSPC calendar slot; no index quotes used",
        factor_manifest=json.loads((DATA / "factor_manifest.json").read_text()))
    save_json(output / "identity.json", identity)
    log = OUTPUT / "lifecycle.jsonl"

    def evaluate(requests, label, exclusions, s):
        folder = output / label
        folder.mkdir(parents=True, exist_ok=False)
        requests.to_csv(folder / "requests.csv", index=False)
        def record(status, **detail):
            with log.open("a") as file:
                file.write(json.dumps(dict(run=stamp, label=label, status=status,
                    timestamp=datetime.now(timezone.utc).isoformat(), requests_sha256=sha(folder / "requests.csv"),
                    identity_sha256=sha(output / "identity.json"), **detail)) + "\n")
        record("started")
        try:
            scheduled, audit = schedule_lots(requests, prices, s, exclusions) if len(requests) else ([], pd.DataFrame())
            if not scheduled:
                audit.to_csv(folder / "eligibility.csv", index=False)
                record("no_eligible_lots")
                return None, None, None
            result = run_portfolio(requests, prices, s, exclusions=exclusions)
            summary = write_report(result, prices, folder, s, factors=factors)
            summary["accounting_currency"] = "USD; US-only listings, no FX conversion"
            summary["classification"] = "post-result exploratory, not blind OOS"
            lots = lot_cashflows(result, prices, s)
            lots.to_csv(folder / "lots.csv", index=False)
            drift = pre_information_drift(lots, prices)
            drift.to_csv(folder / "pre_information_drift.csv", index=False)
            summary["mean_pre_information_car"] = float(drift.descriptive_pre_information_car.mean()) if len(drift) else None
            summary["lot_cluster_interval"] = cluster_interval(lots)
            summary["company_omission_mean_lot_returns"] = omission_means(lots)
            summary["risk_exposures"] = risk_summary(result, prices)
            save_json(folder / "metrics.json", summary)
            lots.groupby("ticker").agg(positions=("ticker", "size"), net_pnl=("net_pnl", "sum"),
                mean_lot_return=("net_lot_return", "mean")).to_csv(folder / "company_concentration.csv")
            record("completed", positions=len(lots), nav_reconciled=True)
            return result, summary, lots
        except Exception as exc:
            record("failed", error=str(exc))
            raise

    table, evaluated = [], {}
    for policy in ("reference_mix", "webull_only"):
        exclusions = dict(manifest["exclusions"])
        if policy == "webull_only":
            exclusions.update({s: "Excluded by Webull-only policy; original allocation retained in cash"
                for s, info in manifest["symbols"].items() if info["vendor"] != "webull"})
        for rule in RULES:
            requests, audit = build_requests(winners, prices, prices["SPY"].index, rule,
                counterparts=counterparts, exclusions=exclusions)
            scheduled, _ = schedule_lots(requests, prices, settings, exclusions) if len(requests) else ([], None)
            events = {r["event_id"] for r in scheduled}
            controls = ledger[(ledger.country == "US") & (ledger.role == "placebo") & ledger.event_id.isin(events)]
            control_rule = "delay20_hold5" if rule == "delay20_hold5" else "below_sma60_hold5"
            controls, control_audit = build_requests(controls, prices, prices["SPY"].index,
                control_rule, exclusions=exclusions)
            for cost in (1, 2):
                s = replace(settings, cost_multiplier=float(cost))
                label = f"{policy}/{rule}/costs{cost}"
                result, summary, lots = evaluate(requests, label + "/winners", exclusions, s)
                control, control_summary, _ = evaluate(controls, label + "/controls", exclusions, s)
                audit.to_csv(output / label / "entry_filter_audit.csv", index=False)
                control_audit.to_csv(output / label / "control_filter_audit.csv", index=False)
                row = dict(vendor_policy=policy, rule=rule, cost_multiplier=cost,
                           status="completed" if result is not None else "no_eligible_lots")
                if result is not None:
                    paired = mean_inference(result.equity.daily_return - control.equity.daily_return) if control is not None else None
                    save_json(output / label / "winner_minus_control.json", paired)
                    if control is not None:
                        (result.equity.daily_return - control.equity.daily_return).to_csv(
                            output / label / "winner_minus_control.csv", header=["daily_return"])
                    row.update({k: summary[k] for k in ["annualized_return", "annualized_volatility", "sharpe",
                        "max_drawdown", "annualized_turnover", "positions", "events", "active_days"]})
                    row.update(tickers=int(lots.ticker.nunique()), unique_exposures=len(lots[["ticker", "trade_date"]].drop_duplicates()),
                        average_net_lot_return=float(lots.net_lot_return.mean()), median_net_lot_return=float(lots.net_lot_return.median()),
                        profitable_lots=int((lots.net_lot_return > 0).sum()), winner_p=summary["inference"]["p_value"],
                        paired_mean_daily=paired["mean_daily"] if paired else None, paired_p=paired["p_value"] if paired else None,
                        all_company_omission_means_positive=all(v is not None and v > 0 for v in omission_means(lots).values()),
                        control_positions=control_summary["positions"] if control_summary else 0,
                        control_events=control_summary["events"] if control_summary else 0)
                    evaluated[(policy, rule, cost)] = (result, summary, lots)
                table.append(row)
            print(f"Completed {policy}: {rule}", flush=True)
    table = pd.DataFrame(table)
    # Known lower bound only. Prior inventories include additional searches, so never call this exhaustive.
    table["winner_p_bonferroni_lower_bound"] = (table.winner_p * (111 + 168 + 24)).clip(upper=1)
    table.to_csv(output / "summary.csv", index=False)
    # Exact reference reproduction against preserved results; rounding/period substitutions cannot pass.
    prior = pd.read_csv(DATA / "prior_grid.csv")
    for cost in (1, 2):
        old = prior[(prior.vintage == "refreshed") & (prior.entry_delay_sessions == 20)
                    & (prior.hold_days == 5) & (prior.cost_multiplier == cost)].iloc[0]
        current = table[(table.vendor_policy == "reference_mix") & (table.rule == "delay20_hold5") & (table.cost_multiplier == cost)].iloc[0]
        for metric in ("sharpe", "annualized_return", "annualized_volatility", "max_drawdown", "average_net_lot_return"):
            if not np.isclose(old[metric], current[metric], atol=1e-12, rtol=1e-9):
                raise ValueError(f"Frozen baseline failed reproduction: {metric}")
    gates = []
    for policy in ("reference_mix", "webull_only"):
        for alternative in RULES[1:]:
            group = table[(table.vendor_policy == policy) & (table.rule == alternative)]
            baseline = table[(table.vendor_policy == policy) & (table.rule == RULES[0])]
            checks = dict(two_cost_runs_completed=bool(len(group) == 2 and group.status.eq("completed").all()))
            if checks["two_cost_runs_completed"]:
                checks.update(higher_sharpe_both_costs=bool((group.set_index("cost_multiplier").sharpe > baseline.set_index("cost_multiplier").sharpe).all()),
                    positive_winner_minus_control=bool(group.paired_mean_daily.gt(0).all()),
                    no_worse_drawdown=bool((group.set_index("cost_multiplier").max_drawdown >= baseline.set_index("cost_multiplier").max_drawdown).all()),
                    at_least_ten_exposures=bool(group.unique_exposures.ge(10).all()),
                    at_least_three_owners=bool(group.tickers.ge(3).all()),
                    positive_after_each_company_omission=bool(group.all_company_omission_means_positive.all()))
            gates.append(dict(vendor_policy=policy, alternative=alternative, checks=checks, passed=all(checks.values())))
    save_json(output / "replacement_gate.json", dict(gates=gates,
        decision="retain_delay20_hold5" if not any(g["passed"] for g in gates) else "review_passed_fixed_alternative",
        label="Exploratory working-candidate decision, never confirmation of the original hypothesis."))
    after = {name: sha(ROOT / name) for name in before}
    for name, expected in identity["code_and_input_hashes"].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f"Concurrent code/input mutation: {name}")
    validate_freeze()
    if after != before:
        raise ValueError("Protected primary/holdout/registration files changed during analysis.")
    save_json(output / "verification.json", dict(baseline_reproduced=True, all_completed_lot_cashflows_reconciled=True,
        frozen_inputs_unchanged=True, protected_files_unchanged=True, completed_portfolio_evaluations=sum(
            1 for row in log.read_text().splitlines() if json.loads(row)["run"] == stamp and json.loads(row)["status"] == "completed"),
        stock_price_fetches=0, holdout_evaluations=0))
    save_json(OUTPUT / "latest.json", dict(directory=str(output.relative_to(ROOT))))
    print("OUTPUT", output, flush=True)


if __name__ == "__main__":
    main()
