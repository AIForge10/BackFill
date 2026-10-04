"""Post-screen concentration diagnostics, never deployable outcome-based filters."""
import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backfill.analysis import metrics
from backfill.engine import run_portfolio
from backfill.guardrails import fingerprint, log_run
from backfill.prices import load_cache
from backfill.settings import Settings
from strict_timing import CACHE, lot_net_pnl


def main():
    source = ROOT / "results/strict_timing/1b141b2d696b"
    table = pd.read_csv(source / "summary.csv")
    fresh = table[(table.vintage == "refreshed") & (table.cost_multiplier == 1)]
    picks = fresh.loc[[fresh.sharpe.idxmax(), fresh.annualized_return.idxmax()]].drop_duplicates(
        ["entry_delay_sessions", "hold_days"])
    settings = Settings()
    manifest = json.loads((CACHE / "manifest.json").read_text())
    prices, manifest = load_cache(CACHE, sorted(manifest["symbols"]), evaluation_end=settings.end)
    identity = fingerprint(ROOT, [Path(__file__), source / "identity.json", source / "summary.csv",
                                  ROOT / "research/strict_timing.py", CACHE / "manifest.json"], settings)
    identity["classification"] = "post-grid omission attribution for selected positive cells; not a new signal"
    output = source / "diagnostics"
    output.mkdir(exist_ok=False)
    (output / "identity.json").write_text(json.dumps(identity, indent=2)+"\n")
    rows = []
    for pick in picks.itertuples():
        delay, hold = int(pick.entry_delay_sessions), int(pick.hold_days)
        base = source / f"refreshed/delay{delay}/hold{hold}/costs1/winners"
        requests = pd.read_csv(base / "requests.csv")
        lots = pd.read_csv(base / "lots.csv", parse_dates=["trade_date"])
        omissions = [("company", ticker) for ticker in sorted(lots.ticker.unique())]
        omissions += [("entry_year", int(year)) for year in sorted(lots.trade_date.dt.year.unique())]
        for kind, value in omissions:
            if kind == "company":
                retained = requests[requests.ticker != value].copy()
            else:
                removed = lots[lots.trade_date.dt.year == value]
                keys = set(zip(removed.event_id, removed.ticker))
                retained = requests[[(e,t) not in keys for e,t in zip(requests.event_id,requests.ticker)]].copy()
            # Preserve original weights: omitted capital stays cash; no upweighting.
            for cost in (1, 2):
                s = replace(settings, hold_days=hold, cost_multiplier=float(cost))
                label = f"delay{delay}/hold{hold}/omit_{kind}_{value}/costs{cost}"
                dest = output / label
                dest.mkdir(parents=True)
                retained.to_csv(dest / "requests.csv", index=False)
                run_id = f"1b141b2d696b:diagnostic:{label}"
                log = ROOT / "results/variants_log.csv"
                log_run(log,run_id,f"strict_timing_diagnostic/{label}",s,dest/'requests.csv',prices.keys(),'started',identity=identity)
                try:
                    result = run_portfolio(retained,prices,s,exclusions=manifest.get('exclusions',{}))
                    summary = metrics(result,s)
                    net = lot_net_pnl(result,prices,s)
                    result.equity.to_csv(dest/'equity.csv')
                    net.to_csv(dest/'lots.csv',index=False)
                    result.trades.to_csv(dest/'trades.csv',index=False)
                    result.eligibility.to_csv(dest/'eligibility.csv',index=False)
                    (dest/'metrics.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
                    log_run(log,run_id,f"strict_timing_diagnostic/{label}",s,dest/'requests.csv',prices.keys(),'completed',summary=summary,identity=identity)
                    rows.append(dict(entry_delay_sessions=delay,hold_days=hold,omission_type=kind,omitted=value,cost_multiplier=cost,
                        lots=summary['positions'],events=summary['events'],sharpe=summary['sharpe'],annualized_return=summary['annualized_return'],
                        average_net_lot_return=net.net_lot_return.mean(),total_net_pnl=net.net_pnl.sum()))
                except Exception as exc:
                    log_run(log,run_id,f"strict_timing_diagnostic/{label}",s,dest/'requests.csv',prices.keys(),'failed',summary={'error':str(exc)},identity=identity)
                    raise
            print(label,'normal-cost Sharpe',round(rows[-2]['sharpe'],3),'net lot mean',round(rows[-2]['average_net_lot_return'],4),flush=True)
    pd.DataFrame(rows).to_csv(output/'summary.csv',index=False)
    print('OUTPUT',output,flush=True)


if __name__ == '__main__':
    main()
