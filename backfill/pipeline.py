"""Explicit orchestration: prepare evidence, load cache, account, report, log."""
import argparse
import importlib.util
import json
import uuid
from dataclasses import replace
from pathlib import Path

import pandas as pd

import config
from backfill.analysis import mean_inference, write_report
from backfill.engine import run_portfolio
from backfill.events import build_candidates
from backfill.guardrails import (fingerprint, finish_holdout, log_run, require_oos_freeze,
                                reserve_holdout)
from backfill.prices import load_cache, required_symbols, sha256
from backfill.settings import Settings
from strategies.primary import select

ROOT = Path(__file__).resolve().parents[1]

# Nine predeclared specifications, including the fixed primary. Omission tests
# are diagnostics, not selection candidates. Nothing auto-searches parameters.
# Primary scope is US listings (team decision, 2026-10-03: Webull is the price
# source and covers US listings); all_markets adds the non-US listed winners.
PRIMARY_MARKETS = ("US",)
VARIANTS = {
    "primary": {}, "capture60": {"window_days": 60},
    "allocation": {"include_allocation": True}, "certain_dates": {"exclude_uncertain": True},
    "all_flags": {"include_flags": True}, "hold20": {"hold_days": 20},
    "hold40": {"hold_days": 40}, "hold120": {"hold_days": 120},
    "all_markets": {"markets": tuple(config.MARKET_INDEX)},
}


def prepare(events_path, suppliers_path, mapping_path, directory, *, variant="primary", final=False, status_path=None):
    paths = [Path(events_path), Path(suppliers_path), Path(mapping_path)]
    if status_path is not None:
        paths.append(Path(status_path))
    before = {str(p): sha256(p) for p in paths}
    events = pd.read_csv(events_path)
    suppliers = pd.read_csv(suppliers_path, dtype={"capture_ts": str})
    mapping = pd.read_csv(mapping_path, keep_default_na=False)
    if status_path is not None:
        # Recompute this flag because older processed events used all future
        # names. Use the same corrected upstream function, not a second rule.
        status = pd.read_csv(status_path, parse_dates=["snapshot_date"])
        dated = events.copy()
        dated["public_date"] = pd.to_datetime(dated.public_date)
        dated["left_censored"] = dated.get("left_censored", pd.Series(False, index=dated.index)).map(
            lambda value: str(value).lower() in {"true", "1"})
        parser_path = Path(__file__).resolve().parents[1] / "src/03_parse_main.py"
        spec = importlib.util.spec_from_file_location("backfill_parse_main", parser_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suspects = module.rename_suspects(dated, status)
        events["rename_match"] = events.event_id.map(suspects)
        events["rename_suspect"] = events.rename_match.notna()
    params = VARIANTS[variant]
    ledger, audit = build_candidates(events, suppliers, mapping, final=final,
                                    **{k: v for k, v in params.items()
                                       if k in {"window_days", "include_allocation", "exclude_uncertain", "include_flags"}})
    markets = tuple(params.get("markets", PRIMARY_MARKETS))
    removed = ledger[~ledger.country.isin(markets)]
    if not removed.empty:
        audit = pd.concat([audit, removed[["event_id", "ticker"]].assign(stage="subset", reason="outside_markets")],
                          ignore_index=True)
    ledger = ledger[ledger.country.isin(markets)].copy()
    # Event capital is split across the in-scope winners only.
    winners = ledger[ledger.role == "winner"].groupby("event_id").ticker.nunique()
    ledger["winner_count"] = ledger.event_id.map(winners).fillna(0).astype(int)
    ledger = ledger[ledger.winner_count > 0]
    if before != {str(p): sha256(p) for p in paths}:
        raise ValueError("Source tables changed during preparation; rerun after the background parser finishes.")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(directory / "events.csv", index=False)
    audit.to_csv(directory / "attrition.csv", index=False)
    reasons = audit.groupby(["stage", "reason"]).size().rename("rows").reset_index() if not audit.empty else pd.DataFrame()
    reasons.to_csv(directory / "attrition_summary.csv", index=False)
    metadata = dict(variant=variant, parameters=params, markets=list(markets), final=final, source_hashes=before,
                    control_warning="FDA-page nonlisted controls; not verified nonmanufacturers",
                    timestamp_rule="first observed listing known at UTC day end; next local session close",
                    page_rule="one page per event: latest pre-listing capture else first post-listing capture")
    winners = ledger[ledger.role == "winner"]
    metadata["counts"] = dict(winner_events=int(winners.event_id.nunique()), winner_positions=len(winners),
                              control_positions=int((ledger.role == "placebo").sum()),
                              winner_tickers=int(winners.ticker.nunique()))
    (directory / "preparation.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return ledger


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events-source", type=Path, default=ROOT / "data/processed/shortage_events.csv")
    ap.add_argument("--suppliers-source", type=Path, default=ROOT / "data/processed/suppliers.csv")
    ap.add_argument("--mapping", type=Path, default=ROOT / "data/company_ticker_map.csv")
    ap.add_argument("--status-source", type=Path, default=ROOT / "data/processed/main_status.csv",
                    help="snapshot status panel used to recompute point-in-time rename flags")
    ap.add_argument("--variant", choices=VARIANTS, default="primary")
    ap.add_argument("--cache", type=Path, help="bounded immutable cache; default data/raw/prices/{is,oos}")
    ap.add_argument("--output", type=Path, default=ROOT / "results/backfill")
    ap.add_argument("--prepare-only", action="store_true", help="prepare signals/audits without prices or returns")
    ap.add_argument("--leave-out", help="diagnostic omission of one ticker; no capital redistribution")
    ap.add_argument("--factors", type=Path, help="optional monthly USD decimal factor CSV: date,Mkt-RF,HML,Mom,RF")
    ap.add_argument("--selection", type=Path, default=ROOT / "data/processed/backfill/selection.json",
                    help="frozen in-sample selection record required for --final")
    ap.add_argument("--final", action="store_true", help="single frozen OOS bundle; never used during development")
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    if args.final and args.prepare_only:
        raise ValueError("Use 05_events.py --oos-stage for signal preparation; --final is reserved for evaluation.")
    settings = Settings()
    if args.final:
        require_oos_freeze(ROOT)
        if args.leave_out:
            raise ValueError("Omission diagnostics are in-sample only; no holdout parameter exploration.")
        settings = replace(settings, start=config.OOS_START, end=config.OOS_END, final=True)
        selection = json.loads(args.selection.read_text())
        selected = selection["selected"]
        if args.variant != selected["variant"]:
            raise ValueError("Final variant must match the frozen in-sample selection record.")
        for path, expected in selected["identity"]["files"].items():
            if (Path(path).suffix == ".py" or Path(path) in [args.mapping, ROOT / "HYPOTHESIS.md"]) and sha256(path) != expected:
                raise ValueError("Strategy/accounting code, hypothesis or mapping changed after in-sample selection.")
    cache = args.cache or ROOT / "data/raw/prices" / ("oos" if args.final else "is")
    sources = [args.events_source, args.suppliers_source, args.mapping, ROOT / "HYPOTHESIS.md"]
    # Data-only preparation can happen before any prices are acquired.
    if args.prepare_only:
        out = ROOT / "data/processed/backfill" / args.variant
        prepare(*sources[:3], out, variant=args.variant, status_path=args.status_source)
        print(f"Prepared evidence and attrition: {out}. No prices loaded or backtest run.")
        return
    code = [p for p in [ROOT / "config.py", *sorted((ROOT / "backfill").glob("*.py")),
            *sorted((ROOT / "strategies").glob("*.py")), ROOT / "src/03_parse_main.py"]
            if p.exists()]
    identity = fingerprint(ROOT, sources + [cache / "manifest.json", args.status_source] + code
                           + ([args.factors] if args.factors else [])
                           + ([args.selection] if args.final else []), settings)
    identity.update(selected_variant=args.variant, diagnostic_leave_out=args.leave_out)
    final_lock = ROOT / "results/backfill_oos_attempt.json"
    # A selected secondary and the registered primary are evaluated together,
    # once, with all outputs disclosed. This never replaces the fixed hypothesis.
    variants = ["primary", args.variant] if args.final and args.variant != "primary" else [args.variant]
    if args.final:
        reserve_holdout(final_lock, identity)
    bundle_id = uuid.uuid4().hex[:12]
    bundle = args.output / bundle_id
    bundle.mkdir(parents=True, exist_ok=False)
    (bundle / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    (bundle / "status.json").write_text(json.dumps({"status": "started"}) + "\n")
    try:
        factors = pd.read_csv(args.factors, index_col="date") if args.factors else None
        for variant in variants:
            variant_settings = replace(settings, hold_days=VARIANTS[variant].get("hold_days", settings.hold_days))
            ledger = prepare(*sources[:3], bundle / variant / "inputs", variant=variant, final=args.final,
                             status_path=args.status_source)
            if ledger.empty or not (ledger.role == "winner").any():
                raise ValueError("No winner candidates. Inspect attrition; do not report an empty strategy.")
            calendar_symbols = set(config.MARKET_INDEX.values()) & set(
                json.loads((cache / "manifest.json").read_text())["symbols"])
            prices, manifest = load_cache(cache, sorted(set(required_symbols(ledger)) | calendar_symbols),
                                          evaluation_end=settings.end)
            exclusions = manifest.get("exclusions", {})
            requests = {role: select(ledger, settings=variant_settings, role=role)
                        for role in ["winner", "placebo"]}
            if args.leave_out:
                requests = {role: frame[frame.ticker != args.leave_out].copy() for role, frame in requests.items()}
            role_results = {}
            for multiplier in [1.0, 2.0]:
                cost_settings = replace(variant_settings, cost_multiplier=multiplier)
                for role in ["winner", "placebo"]:
                    label = f"{variant}/{role}/costs{int(multiplier)}"
                    run_id = f"{bundle_id}:{label}"
                    log_run(ROOT / "results/variants_log.csv", run_id, label, cost_settings,
                            bundle / variant / "inputs/events.csv", prices.keys(), "started", identity=identity)
                    try:
                        result = run_portfolio(requests[role], prices, cost_settings, exclusions=exclusions)
                        summary = write_report(result, prices, bundle / label, cost_settings, factors=factors)
                        role_results[(role, multiplier)] = result
                        log_run(ROOT / "results/variants_log.csv", run_id, label, cost_settings,
                                bundle / variant / "inputs/events.csv", prices.keys(), "completed",
                                summary=summary, identity=identity)
                    except Exception as exc:
                        log_run(ROOT / "results/variants_log.csv", run_id, label, cost_settings,
                                bundle / variant / "inputs/events.csv", prices.keys(), "failed",
                                summary={"error": str(exc)}, identity=identity)
                        raise
            for multiplier in [1.0, 2.0]:
                winner = role_results[("winner", multiplier)].equity.daily_return
                placebo = role_results[("placebo", multiplier)].equity.daily_return
                if not winner.index.equals(placebo.index):
                    raise ValueError("Winner/control calendar mismatch; missing days cannot be filled with returns.")
                paired = pd.concat([winner.rename("winner"), placebo.rename("placebo")], axis=1)
                paired["difference"] = paired.winner - paired.placebo
                paired.to_csv(bundle / variant / f"winner_minus_placebo_costs{int(multiplier)}.csv")
                inference = mean_inference(paired.difference, lags=max(60, variant_settings.hold_days))
                inference["control_warning"] = "unmatched FDA-page nonlisted controls; not a causal estimate"
                (bundle / variant / f"comparison_costs{int(multiplier)}.json").write_text(
                    json.dumps(inference, indent=2, allow_nan=False) + "\n")
        (bundle / "status.json").write_text(json.dumps({"status": "completed"}) + "\n")
        if args.final:
            finish_holdout(final_lock, "completed", {"bundle": str(bundle)})
    except Exception as exc:
        (bundle / "status.json").write_text(json.dumps({"status": "failed", "error": str(exc)}) + "\n")
        if args.final:
            finish_holdout(final_lock, "failed", {"error": str(exc), "bundle": str(bundle)})
        raise
    print(f"Saved logged offline bundle: {bundle}")


if __name__ == "__main__":
    main()
