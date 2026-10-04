"""Summarize a completed backtest bundle: the headline numbers the note reports.

  python src/analysis.py                 # latest completed bundle in results/backfill/
  python src/analysis.py --bundle <dir>

Prints, for winners and controls at normal and doubled costs: events, positions, annualized return,
volatility, Sharpe, max drawdown, turnover, worst month, HAC t-stat and p-value; then the
winner-minus-control comparison. Writes the same table to <bundle>/summary.md.
Metric definitions: backfill/analysis.py. Per-bundle files: equity.csv/png, trades.csv, lots.csv,
capacity.csv, pre_drift.csv, eligibility.csv, metrics.json.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def latest_bundle():
    done = [p for p in (ROOT / "results/backfill").glob("*/status.json")
            if json.loads(p.read_text()).get("status") == "completed"]
    if not done:
        raise SystemExit("No completed bundle in results/backfill/. Run: python run_all.py")
    return max(done, key=lambda p: p.stat().st_mtime).parent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", type=Path)
    args = ap.parse_args()
    bundle = args.bundle or latest_bundle()
    lines = [f"# Results: {bundle.name}", "",
             "| Variant | Role | Costs | Events | Positions | Ann. return | Vol | Sharpe | Max DD | Turnover | Worst month | HAC t | p |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for metrics in sorted(bundle.glob("*/*/costs*/metrics.json")):
        variant, role, costs = metrics.parts[-4], metrics.parts[-3], metrics.parts[-2]
        m = json.loads(metrics.read_text())
        i = m.get("inference", {})
        lines.append(f"| {variant} | {role} | x{costs[-1]} | {m['events']} | {m['positions']} | "
                     f"{m['annualized_return']:+.2%} | {m['annualized_volatility']:.2%} | "
                     f"{m['sharpe']:+.2f} | {m['max_drawdown']:.1%} | {m['annualized_turnover']:.2f} | "
                     f"{m['worst_month']:.1%} | {i.get('hac_t', float('nan')):+.2f} | {i.get('p_value', float('nan')):.3f} |")
    lines += ["", "| Variant | Comparison | Costs | Mean daily difference | HAC t | p |", "|---|---|---|---|---|---|"]
    for comp in sorted(bundle.glob("*/comparison_costs*.json")):
        c = json.loads(comp.read_text())
        lines.append(f"| {comp.parts[-2]} | winners minus controls | x{comp.stem[-1]} | {c['mean_daily']:+.6f} | "
                     f"{c['hac_t']:+.2f} | {c['p_value']:.3f} |")
    text = "\n".join(lines) + "\n"
    (bundle / "summary.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
