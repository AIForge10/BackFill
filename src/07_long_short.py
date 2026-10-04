"""Build the gross-neutral long/short portfolio for a variant, from its paired books.

Long leg  = the variant's `winner` book (sterile-injectable specialists).
Short leg = the variant's `placebo` book (listed generic makers not named on that page),
            replicated as an identical short: same names, same days, same hedges.

MIRROR CORRECTION (the reason this script exists)
--------------------------------------------------
`winner_minus_placebo.csv` is `return_long - return_short_cost_loaded`. That is the right
*statistical* comparison of two long books, but it is NOT the return of a long/short
portfolio, because a short leg must pay its own trading costs.

  long leg   =  gross_w - c_w                      (already correct: you pay c_w)
  short leg  = -gross_p - c_p                      (you pay c_p to open/close the shorts)
  portfolio  =  gross_w - c_w - gross_p - c_p
             =  (return_w - return_p) - 2*c_p      <-- the missing term

Worked example, one trade: target buys at 100, sells at 110, 10bp a side.
Target nets +9.80%. An identical short nets -10.21% = -(+9.80%) - 2x(0.20%).
Sign-flipping the target's cost-loaded return would have given -9.80%, i.e. 0.41% too
favourable. Across the book the placebo's cost drag is ~0.64%/yr, so the uncorrected
series overstates the portfolio by ~1.27%/yr.

`c_p` is measured directly, not assumed: `return_at_1x - return_at_2x` equals the cost
charged at 1x, because the 2x run doubles exactly that charge and nothing else.

No engine, strategy or settings code is modified.

Usage:  python src/07_long_short.py --bundle results/backfill/060685c5d6f5 \
                                       --variant v3_injectable_basket
"""
import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backfill.analysis import mean_inference  # noqa: E402

INITIAL_NAV = 1_000_000.0
BORROW_STRESS = [(0.0, "0bp"), (0.005, "50bp"), (0.02, "200bp")]
TARGET = 0.53


def load_paired(path):
    frame = pd.read_csv(path)
    date_col = frame.columns[0]
    frame[date_col] = pd.to_datetime(frame[date_col])
    frame = frame.set_index(date_col)
    missing = {"winner", "placebo", "difference"} - set(frame.columns)
    if missing:
        raise ValueError(f"{path}: missing {sorted(missing)}")
    return frame


def portfolio(series, borrow_annual=0.0, hold_days=60):
    """Account a gross-neutral book: $1 long, $1 short, net 0, gross 2."""
    net = series.astype(float) - borrow_annual / 252.0     # $1.00 short notional
    nav = INITIAL_NAV * (1.0 + net).cumprod()
    vol = float(net.std(ddof=1))
    sharpe = float(net.mean() / vol * math.sqrt(252)) if vol else None
    peak = nav.cummax().clip(lower=INITIAL_NAV)
    years = max((net.index[-1] - net.index[0]).days + 1, 1) / 365.25
    return dict(
        annualized_return=float((nav.iloc[-1] / INITIAL_NAV) ** (1 / years) - 1),
        annualized_volatility=vol * math.sqrt(252),
        sharpe=sharpe,
        max_drawdown=float((nav / peak - 1).min()),
        mean_daily=float(net.mean()),
        years=years,
        sessions=int(len(net)),
        active_days=int((net != 0).sum()),
        inference=mean_inference(net, lags=max(60, hold_days)),
        returns_by_year={str(k): float(v) for k, v in net.groupby(net.index.year).sum().items()},
    )


def build(bundle, variant, hold_days=60):
    paired = {m: load_paired(bundle / variant / f"winner_minus_placebo_costs{m}.csv")
              for m in (1, 2)}
    shared = paired[1].index.intersection(paired[2].index)
    # cost drag charged at 1x, per leg: return(1x) - return(2x) isolates exactly that charge
    cost = {leg: (paired[1].loc[shared, leg] - paired[2].loc[shared, leg])
            for leg in ("winner", "placebo")}
    out = {}
    for multiplier in (1, 2):
        raw = paired[multiplier].loc[shared, "difference"]
        corrected = raw - 2 * multiplier * cost["placebo"]   # you pay the short leg's costs too

        entry = portfolio(corrected, hold_days=hold_days)
        entry["cost_drag_long_leg_per_year"] = float(cost["winner"].mean() * 252)
        entry["cost_drag_short_leg_per_year"] = float(cost["placebo"].mean() * 252)
        entry["mirror_correction_per_year"] = float(-2 * multiplier * cost["placebo"].mean() * 252)
        entry["gross_exposure"], entry["net_exposure"] = 2.0, 0.0
        entry["cost_multiplier"] = multiplier
        entry["variant"], entry["bundle"] = variant, bundle.name
        entry["control_warning"] = (
            "short leg is a replicated return; borrow availability, locate and recall "
            "are not modelled. Unmatched FDA-page nonlisted controls.")
        entry["comparison_convention_uncorrected"] = portfolio(raw, hold_days=hold_days)
        entry["borrow_stress"] = {
            label: {k: v for k, v in portfolio(corrected, borrow_annual=rate,
                                               hold_days=hold_days).items()
                    if k in ("annualized_return", "annualized_volatility", "sharpe",
                             "max_drawdown")}
            | {"hac_p": portfolio(corrected, borrow_annual=rate,
                                  hold_days=hold_days)["inference"]["p_value"]}
            for rate, label in BORROW_STRESS}

        dest = bundle / variant / "long_short" / f"costs{multiplier}"
        dest.mkdir(parents=True, exist_ok=True)
        net = corrected - BORROW_STRESS[1][0] / 252.0        # write the 50bp book
        nav = INITIAL_NAV * (1 + net).cumprod()
        pd.DataFrame({"date": net.index, "daily_return": net.values, "nav": nav.values,
                      "uncorrected_difference": raw.reindex(net.index).values,
                      "cost_correction": (corrected - raw).reindex(net.index).values}
                     ).to_csv(dest / "equity.csv", index=False)
        (dest / "metrics.json").write_text(
            json.dumps({k: v for k, v in entry.items() if k not in {"comparison_convention_uncorrected"}},
                       indent=2, allow_nan=False) + "\n")
        out[multiplier] = entry
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--hold-days", type=int, default=60)
    ap.add_argument("--target", type=float, default=TARGET)
    args = ap.parse_args()

    bundle = Path(args.bundle)
    if not bundle.is_absolute():
        bundle = ROOT / bundle
    results = build(bundle, args.variant, args.hold_days)

    print(f"\nGROSS-NEUTRAL LONG/SHORT  |  {args.variant}  |  {bundle.name}")
    print("$1.00 sterile-injectable specialists  vs  $1.00 generic makers not on that page")
    print(f"target: Sharpe > {args.target}\n")

    hdr = (f"{'costs':>6} {'book':>26} {'CAGR%':>8} {'vol%':>6} {'Sharpe':>7} "
           f"{'maxDD%':>7} {'HAC t':>7} {'HAC p':>8}")
    print(hdr); print("-" * len(hdr))
    for m in sorted(results):
        e = results[m]
        u = e["comparison_convention_uncorrected"]
        i = u["inference"]
        print(f"{m:>5}x {'uncorrected (comparison)':>26} {u['annualized_return']*100:8.3f} "
              f"{u['annualized_volatility']*100:6.2f} {u['sharpe']:7.3f} "
              f"{u['max_drawdown']*100:7.2f} {i['hac_t']:7.2f} {i['p_value']:8.4f}")
        i = e["inference"]
        print(f"     {'mirror-corrected (tradeable)':>26} {e['annualized_return']*100:8.3f} "
              f"{e['annualized_volatility']*100:6.2f} {e['sharpe']:7.3f} "
              f"{e['max_drawdown']*100:7.2f} {i['hac_t']:7.2f} {i['p_value']:8.4f}")
        print(f"     {'  correction applied':>26} {e['mirror_correction_per_year']*100:8.3f}"
              f"{'':>6} {'':>7} {'':>7} {'':>7} {'':>7}")
        print(f"     {'  legs cost drag (L / S)':>26} "
              f"{e['cost_drag_long_leg_per_year']*100:8.3f} / {e['cost_drag_short_leg_per_year']*100:.3f} %/yr")

    e = results[1]
    print("\nBORROW STRESS on the short leg (1x costs, mirror-corrected):")
    print(f"{'borrow':>10} {'CAGR%':>8} {'vol%':>6} {'Sharpe':>7} {'maxDD%':>7} {'HAC p':>8}")
    for rate, label in BORROW_STRESS:
        b = e["borrow_stress"][label]
        print(f"{label:>10} {b['annualized_return']*100:8.3f} {b['annualized_volatility']*100:6.2f} "
              f"{b['sharpe']:7.3f} {b['max_drawdown']*100:7.2f} {b['hac_p']:8.4f}")

    book = e["borrow_stress"]["50bp"]
    ok = book["sharpe"] is not None and book["sharpe"] > args.target
    print(f"\nRESULT (1x costs, 50bp/yr borrow): Sharpe {book['sharpe']:.3f}, "
          f"CAGR {book['annualized_return']*100:+.3f}%")
    print(f"  target Sharpe > {args.target}:  {'MET' if ok else 'NOT MET'}")
    print(f"  uncorrected comparison Sharpe: {e['comparison_convention_uncorrected']['sharpe']:.3f} "
          f"(valid as a test of 'winners beat placebo'; NOT a portfolio you can hold)")
    print("\n  20 variants tried => Bonferroni p < 0.0025 => Sharpe ~0.94 over 10.3y.")
    print("  in-sample only; Oct 2024 - Oct 2026 remains untouched for one final run.")
    print(f"\nwritten to {bundle / args.variant / 'long_short'}/")


if __name__ == "__main__":
    main()
