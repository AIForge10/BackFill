"""Export existing Helene evidence and derived chart data. Never runs a backtest.

python -m dashboard.export_case --case-dir ... --webull-cache ... --accounting-cache ...
Only indexed daily movements are bundled; licensed raw price files stay private.
"""
import argparse
import json
import math
from pathlib import Path

from dashboard.repository import digest, document, rows


def verified_prices(folder):
    manifest = document(folder / "manifest.json")
    prices, provenance = {}, {}
    for ticker in ("FMS", "ICUI", "SPY"):
        item = manifest["symbols"][ticker]
        path = folder / item["file"]
        if digest(path) != item["sha256"]:
            raise ValueError(f"Price hash mismatch: {ticker}")
        prices[ticker] = {r["date"]: float(r["adj_close"]) for r in rows(path)}
        if not all(math.isfinite(v) and v > 0 for v in prices[ticker].values()):
            raise ValueError(f"Invalid price: {ticker}")
        provenance[ticker] = {k: item.get(k) for k in
                              ("vendor", "sha256", "retrieved_at", "fallback_reason", "actual_start", "actual_end")}
    return prices, provenance, manifest.get("adjustments", {})


def export(case_dir, webull_cache, accounting_cache):
    case = document(case_dir / "case.json")
    entry, exit_date = case["actual"][0]["entry_date"], case["actual"][0]["exit_date"]
    bundle = dict(schema_version=1, case=case, entry_date=entry, exit_date=exit_date,
                  chart_start="2024-10-10", chart_end="2024-11-22", prices={}, accounting={}, sources=[])

    def source(path):
        bundle["sources"].append(dict(file=path.name, sha256=digest(path)))

    source(case_dir / "case.json")
    timings_path = case_dir / "beneficiary_basket_all_timings.csv"
    bundle["previously_inspected_timings"] = rows(timings_path)
    source(timings_path)
    for policy, folder in (("webull_only", webull_cache), ("reference_mix", accounting_cache)):
        prices, provenance, adjustments = verified_prices(folder)
        if policy == "webull_only" and any(p["vendor"] != "webull" for p in provenance.values()):
            raise ValueError("Webull-only chart cannot contain fallback prices")
        dates = sorted(d for d in prices["SPY"] if bundle["chart_start"] <= d <= bundle["chart_end"])
        if not dates or any(d not in prices[t] for d in dates for t in prices):
            raise ValueError("Incomplete common-session coverage")
        points = []
        for date in dates:
            point = {"date": date}
            for ticker in prices:
                point[ticker] = prices[ticker][date] / prices[ticker][entry] - 1
            point["basket"] = (point["FMS"] + point["ICUI"]) / 2
            points.append(point)
        bundle["prices"][policy] = dict(provenance=provenance, adjustments=adjustments, points=points)

    for costs in (1, 2):
        breakdown, curves = [], {}
        for ticker in ("FMS", "ICUI"):
            lot_path = case_dir / f"{ticker}_costs{costs}_lots.csv"
            trade_path = case_dir / f"{ticker}_costs{costs}_trades.csv"
            equity_path = case_dir / f"{ticker}_costs{costs}_equity.csv"
            lot = rows(lot_path)[0]
            capital = float(lot["entry_usd"])
            trades = rows(trade_path)
            cashflow = lambda leg: -sum(float(t["usd_notional"]) for t in trades if t["leg"] == leg) / capital
            stock, hedge = cashflow("stock"), cashflow("hedge")
            fees = -(float(lot["transaction_cost"]) + float(lot["hedge_carry_cost"])) / capital
            net = float(lot["net_lot_return"])
            if not math.isclose(stock + hedge + fees, net, abs_tol=1e-10):
                raise ValueError(f"Cashflow reconciliation failed: {ticker}")
            breakdown.append(dict(ticker=ticker, stock=stock, hedge=hedge, fees=fees,
                                  net=net, beta=float(lot["beta"])))
            equity = rows(equity_path)
            nav_before = float(next(r["nav"] for r in reversed(equity) if r["date"] < entry))
            curves[ticker] = {r["date"]: (float(r["nav"]) - nav_before) / capital for r in equity
                             if bundle["chart_start"] <= r["date"] <= bundle["chart_end"]}
            for path in (lot_path, trade_path, equity_path):
                source(path)
        dates = sorted(curves["FMS"])
        curve = [{"date": d, "FMS": curves["FMS"][d], "ICUI": curves["ICUI"][d],
                  "basket": (curves["FMS"][d] + curves["ICUI"][d]) / 2} for d in dates]
        basket = dict(ticker="basket", **{k: sum(r[k] for r in breakdown) / 2 for k in
                                          ("stock", "hedge", "fees", "net", "beta")})
        saved = next(r for r in case["actual"] if r["ticker"] == "beneficiary_basket")
        expected = saved["net_hedged_lot_return" if costs == 1 else "doubled_cost_net_hedged_lot_return"]
        endpoint = next(r["basket"] for r in curve if r["date"] == exit_date)
        if not math.isclose(endpoint, expected, abs_tol=1e-10):
            raise ValueError("Saved basket result does not reconcile")
        bundle["accounting"][str(costs)] = dict(breakdown=[*breakdown, basket], points=curve,
                                               vendor_policy="reference_mix", basket_weight=.05)
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--webull-cache", type=Path, required=True)
    parser.add_argument("--accounting-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "data/helene_case.json")
    args = parser.parse_args()
    bundle = export(args.case_dir, args.webull_cache, args.accounting_cache)
    args.output.write_text(json.dumps(bundle, indent=2, allow_nan=False) + "\n")
    print(f"Exported {len(bundle['sources'])} source hashes; existing results only.")


if __name__ == "__main__":
    main()
