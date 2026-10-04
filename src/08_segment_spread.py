"""Segment spread: long the v3 winner book, short a constant generic-pharma basket.

Declared in `docs/DECL_v6_specialist_vs_generic_spread.md` before this file was written.

Long leg  = v3's winner book, read as-is from the bundle (its own fills, hedge, costs).
Short leg = $1.00 opened into BAX/PRGO/TEVA/VTRS, equal weight, rebalanced at the last
            session of each month, beta-hedged long SPY, its own costs charged once.

Accounting, in one pass:
  basket book   fully invested long; stock commission deducted on rebalance sessions
  hedge overlay funded by the short proceeds; P&L taken from the units actually held,
                commission deducted on the sessions the hedge is resized
  leg return    = -(basket return) + hedge P&L / previous NAV - hedge commission / NAV

Why not mirror the placebo book: it churns 7.70 x/yr over 711 lots and a short leg pays
its own costs, so `winner - placebo` overstates the portfolio by 2 x c_p. v5 measured
that correction (DECL_v5 Amendment A): corrected Sharpe 0.300 / 0.203.

This is a *segment spread*, not an event-timed trade: the winner book is invested 92 %
of days, so the shortage listing adds almost no time variation but all of the turnover.
Any edge here may be the secular decline of generic pharma over 2014-2024 rather than a
shortage signal. v5 remains the answer to the event-timed question. Variant #21,
designed after v5 failed its target, so an in-sample pass is descriptive only.

Usage:  python src/08_segment_spread.py --bundle results/backfill/060685c5d6f5 \
                                        --variant v3_injectable_basket
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backfill.analysis import mean_inference  # noqa: E402

BASKET = ["BAX", "PRGO", "TEVA", "VTRS"]   # HSP excluded: no reachable price history
BETA_WINDOW, BETA_MIN, BETA_CLIP = 250, 60, (0.0, 3.0)
STOCK_BPS, HEDGE_BPS = 10.0, 2.0
BORROW = [(0.0, "0bp"), (0.005, "50bp"), (0.02, "200bp")]


def load_prices(cache, names):
    out = {}
    for name in names:
        frame = pd.read_csv(cache / f"{name}.csv", parse_dates=["date"]).set_index("date")
        out[name] = frame["adj_close"].astype(float)
    return pd.DataFrame(out).sort_index().dropna(how="any")


def trailing_beta(px, basket):
    """Trailing OLS beta of the equal-weight basket vs SPY; month-end value used next month."""
    spy_ret = px["SPY"].pct_change()
    proxy = px[basket].pct_change().mean(axis=1)
    daily = (proxy.rolling(BETA_WINDOW, min_periods=BETA_MIN).cov(spy_ret)
             / spy_ret.rolling(BETA_WINDOW, min_periods=BETA_MIN).var())
    daily = daily.reindex(px.index).ffill().bfill().clip(*BETA_CLIP)
    period = px.index.to_period("M")
    month_end = daily.groupby(period).last()
    # use month M-1's beta during month M, so no look-ahead; only the very first
    # calendar month of the price file (outside every test window) falls back to itself
    used = month_end.shift(1).fillna(month_end).reindex(period)
    used.index = px.index                       # one beta per session, in file order
    return used


def short_leg(px, start, multiplier, basket=BASKET):
    stock_rate, hedge_rate = STOCK_BPS * multiplier / 1e4, HEDGE_BPS * multiplier / 1e4
    beta = trailing_beta(px, basket)
    basket_px, spy_px = px[basket], px["SPY"]
    index = px.index[px.index >= pd.Timestamp(start)]
    periods = index.to_period("M")
    last_of_month = set(pd.Series(index, index=index).groupby(periods).max())
    rebalance = np.array([t in last_of_month for t in index])

    # entry: buy $1.00 of basket less its commission; hedge sized on that NAV.
    # Entry commission falls on day 0, which is not necessarily a month-end.
    entry_nav = 1.0 - stock_rate
    units = (entry_nav / len(basket)) / basket_px.loc[index[0]].to_numpy()
    nav, prev_nav = entry_nav, 1.0
    hedge_units = float(beta.loc[index[0]]) * nav / float(spy_px.loc[index[0]])
    hedge_entry = float(beta.loc[index[0]]) * hedge_rate
    stock_paid, hedge_paid = stock_rate, hedge_entry
    day_stock, day_hedge = [stock_rate], [hedge_entry]
    basket_ret, hedge_ret = [-stock_rate], [-hedge_entry]

    for i, t in enumerate(index):
        if i == 0:
            continue
        pxs = basket_px.loc[t].to_numpy()
        spy = float(spy_px.loc[t])
        if rebalance[i]:                              # resize basket to equal weights
            holdings = float((units * pxs).sum())
            new_units = (holdings / len(basket)) / pxs
            cost = float((np.abs(new_units - units) * pxs).sum()) * stock_rate
            new_units = ((holdings - cost) / len(basket)) / pxs
            cost = float((np.abs(new_units - units) * pxs).sum()) * stock_rate
            units = new_units
            nav = holdings - cost
            stock_paid += cost
            day_stock.append(cost)
            want = float(beta.loc[t]) * nav / spy
            h = abs(want - hedge_units) * spy * hedge_rate
            hedge_units, hedge_paid = want, hedge_paid + h
            day_hedge.append(h)
            hedge_ret.append(-h / prev_nav)
        else:
            nav = float((units * pxs).sum())
            day_stock.append(0.0)
            day_hedge.append(0.0)
            hedge_ret.append(hedge_units * (spy - float(spy_px.loc[index[i - 1]])) / prev_nav)
        basket_ret.append(nav / prev_nav - 1.0)
        prev_nav = nav

    leg = -pd.Series(basket_ret, index=index) + pd.Series(hedge_ret, index=index)
    day_cost = pd.Series(np.array(day_stock) + np.array(day_hedge), index=index)

    years = max((index[-1] - index[0]).days + 1, 1) / 365.25
    info = dict(
        rebalances=int(rebalance.sum()),
        stock_cost_per_year=stock_paid / years,
        hedge_cost_per_year=hedge_paid / years,
        basket_cost_drag_per_year=day_cost.sum() / years,
        beta_mean=float(beta.loc[index].mean()),
        beta_min=float(beta.loc[index].min()),
        beta_max=float(beta.loc[index].max()),
        hedge_notional_end=float(hedge_units * spy_px.loc[index[-1]]),
        short_notional_end=float(nav),
        years=years,
    )
    return leg, day_cost, info


def metrics(net, hold_days=60):
    net = net.dropna()
    nav = (1.0 + net).cumprod()
    vol = float(net.std(ddof=1))
    peak = nav.cummax().clip(lower=1.0)
    years = max((net.index[-1] - net.index[0]).days + 1, 1) / 365.25
    return dict(
        annualized_return=float(nav.iloc[-1] ** (1 / years) - 1),
        annualized_volatility=vol * math.sqrt(252),
        sharpe=float(net.mean() / vol * math.sqrt(252)) if vol else None,
        max_drawdown=float((nav / peak - 1).min()),
        mean_daily=float(net.mean()), years=years, sessions=int(len(net)),
        inference=mean_inference(net, lags=max(60, hold_days)),
        returns_by_year={str(k): float(v)
                         for k, v in net.groupby(net.index.year).sum().items()},
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--cache", default="data/raw/prices/is-v6")
    ap.add_argument("--hold-days", type=int, default=60)
    ap.add_argument("--target", type=float, default=0.53)
    args = ap.parse_args()

    bundle = ROOT / args.bundle if not Path(args.bundle).is_absolute() else Path(args.bundle)
    cache = ROOT / args.cache
    first = pd.read_csv(bundle / args.variant / "winner" / "costs1/equity.csv",
                        parse_dates=["date"])["date"].min()
    px = load_prices(cache, BASKET + ["SPY"])
    warmup = int((px.index < pd.Timestamp(first)).sum())
    if warmup < BETA_WINDOW:
        raise ValueError(f"only {warmup} sessions before {first}, need {BETA_WINDOW}")

    out = {}
    for multiplier in (1, 2):
        leg, day_cost, info = short_leg(px, first, multiplier)
        winner = pd.read_csv(bundle / args.variant / "winner" / f"costs{multiplier}/equity.csv",
                             parse_dates=["date"]).set_index("date")["daily_return"]
        idx = winner.index.intersection(leg.index)
        if len(idx) != len(winner):
            raise ValueError(f"calendar mismatch: {len(winner)} winner days vs {len(idx)} common")
        combined = winner.reindex(idx) + leg.reindex(idx)

        entry = metrics(combined, args.hold_days)
        entry.update(
            cost_multiplier=multiplier, variant=args.variant, bundle=bundle.name,
            long_leg="v3_injectable_basket winner book, unmodified",
            short_leg="BAX/PRGO/TEVA/VTRS equal weight, monthly rebalance, beta-hedged long SPY",
            gross_exposure=2.0, net_exposure=0.0, fraction_days_short=1.0,
            short_leg_stats=metrics(leg.reindex(idx), args.hold_days),
            short_leg_costs=info,
            borrow_stress={
                label: {k: v for k, v in metrics(combined - rate / 252.0,
                                                 args.hold_days).items()
                        if k in ("annualized_return", "annualized_volatility",
                                 "sharpe", "max_drawdown")}
                | {"hac_p": metrics(combined - rate / 252.0,
                                    args.hold_days)["inference"]["p_value"]}
                for rate, label in BORROW})
        dest = bundle / args.variant / "segment_spread" / f"costs{multiplier}"
        dest.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"date": idx, "daily_return": combined.values,
                      "nav": (1 + combined).cumprod().values,
                      "long_leg": winner.reindex(idx).values,
                      "short_leg": leg.reindex(idx).values,
                      "short_leg_cost": day_cost.reindex(idx).values}).to_csv(
            dest / "equity.csv", index=False)
        (dest / "metrics.json").write_text(json.dumps(entry, indent=2, allow_nan=False) + "\n")
        out[multiplier] = entry

    print(f"\nSEGMENT SPREAD  |  {args.variant}  |  {bundle.name}")
    print("$1 long sterile-injectable specialists   vs   $1 short BAX/PRGO/TEVA/VTRS (beta-hedged)")
    print(f"target: Sharpe > {args.target}\n")
    hdr = (f"{'costs':>6} {'book':>26} {'CAGR%':>8} {'vol%':>6} {'Sharpe':>7} "
           f"{'maxDD%':>7} {'HAC t':>7} {'HAC p':>8}")
    print(hdr); print("-" * len(hdr))
    for m in sorted(out):
        e = out[m]
        for name, s in (("segment spread (L+S)", e), ("  short leg alone",
                                                      e["short_leg_stats"])):
            i = s["inference"]
            print(f"{m:>5}x {name:>26} {s['annualized_return']*100:8.3f} "
                  f"{s['annualized_volatility']*100:6.2f} {s['sharpe']:7.3f} "
                  f"{s['max_drawdown']*100:7.2f} {i['hac_t']:7.2f} {i['p_value']:8.4f}")

    e, info = out[1], out[1]["short_leg_costs"]
    print(f"\nshort leg: basket cost {info['stock_cost_per_year']*100:.3f}%/yr + hedge "
          f"{info['hedge_cost_per_year']*100:.3f}%/yr, {info['rebalances']} rebalances, "
          f"beta {info['beta_mean']:.2f} [{info['beta_min']:.2f}, {info['beta_max']:.2f}], "
          f"short notional end ${info['short_notional_end']:.3f}")
    print("\nBORROW STRESS (1x costs):")
    print(f"{'borrow':>8} {'CAGR%':>8} {'vol%':>6} {'Sharpe':>7} {'maxDD%':>7} {'HAC p':>8}")
    for rate, label in BORROW:
        x = e["borrow_stress"][label]
        print(f"{label:>8} {x['annualized_return']*100:8.3f} "
              f"{x['annualized_volatility']*100:6.2f} {x['sharpe']:7.3f} "
              f"{x['max_drawdown']*100:7.2f} {x['hac_p']:8.4f}")

    book = e["borrow_stress"]["50bp"]
    ok = book["sharpe"] is not None and book["sharpe"] > args.target
    print(f"\nRESULT (1x costs, 50bp/yr borrow): Sharpe {book['sharpe']:.3f}, "
          f"CAGR {book['annualized_return']*100:+.3f}%")
    print(f"  target Sharpe > {args.target}:  {'MET' if ok else 'NOT MET'}")
    print("\n  variant #21, designed after v5's corrected 0.300 failed the same target.")
    print("  event-timed answer remains v5: corrected Sharpe 0.300 / 0.203 (0bp borrow).")
    print("  20 variants logged => Bonferroni p < 0.0024 => Sharpe ~0.96 over 10.3y.")
    print("  a segment spread: any edge may be secular generic-pharma decline, not the")
    print("  shortage listing. in-sample descriptive only; OOS untouched.")
    print(f"\nwritten to {bundle / args.variant / 'segment_spread'}/")


if __name__ == "__main__":
    main()
