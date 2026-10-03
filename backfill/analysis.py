"""Basic reporting from completed offline accounting, without strategy selection."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backfill.settings import Settings


def mean_inference(returns, lags=60):
    """Intercept-only HAC inference; no independent-event t-statistic."""
    import statsmodels.api as sm

    values = pd.Series(returns).dropna().astype(float)
    if len(values) < 3 or values.std() == 0:
        return dict(mean_daily=float(values.mean()) if len(values) else None,
                    hac_t=None, p_value=None, ci_daily=[None, None], hac_lags=lags)
    fit = sm.OLS(values.to_numpy(), np.ones((len(values), 1))).fit(
        cov_type="HAC", cov_kwds={"maxlags": min(lags, len(values) - 1)}, use_t=True)
    return dict(mean_daily=float(fit.params[0]), hac_t=float(fit.tvalues[0]),
                p_value=float(fit.pvalues[0]), ci_daily=fit.conf_int()[0].tolist(),
                hac_lags=min(lags, len(values) - 1))


def metrics(result, settings=None):
    settings = settings or Settings()
    eq, trades = result.equity, result.trades
    returns = eq.daily_return
    volatility = float(returns.std(ddof=1))
    years = max((eq.index[-1] - pd.Timestamp(settings.start)).days + 1, 1) / 365.25
    running_peak = eq.nav.cummax().clip(lower=settings.initial_nav)
    traded = float(trades.usd_notional.abs().sum()) if not trades.empty else 0.0
    output = dict(annualized_return=float((eq.nav.iloc[-1] / settings.initial_nav) ** (1 / years) - 1),
                  annualized_volatility=volatility * np.sqrt(252),
                  sharpe=float(returns.mean() / volatility * np.sqrt(252)) if volatility > 0 else None,
                  max_drawdown=float((eq.nav / running_peak - 1).min()),
                  annualized_turnover=traded / float(eq.nav.mean()) / years,
                  turnover_definition="both-leg absolute buys+sells / average NAV / elapsed years",
                  skew=float(returns.skew()) if len(returns) >= 3 else None,
                  active_days=int((eq.active_lots > 0).sum()), sessions=len(eq),
                  events=int(result.lots.event_id.nunique()), positions=len(result.lots),
                  transaction_cost=float(trades.cost.sum()) if not trades.empty else 0.0,
                  hedge_carry_cost=float(eq.hedge_carry_cost.sum()),
                  risk_free_assumption="zero cash return; Sharpe above zero; explicit hedge carry separate",
                  accounting_currency="USD; unhedged daily closing FX marks",
                  inference=mean_inference(returns, lags=max(60, settings.hold_days)))
    monthly = (1 + returns).resample("ME").prod() - 1
    output["worst_month"] = float(monthly.min())
    output["returns_by_year"] = {str(y): float((1 + r).prod() - 1)
                                 for y, r in returns.groupby(returns.index.year)}
    return output


def corwin_schultz(bars):
    """Two-day full-spread estimate with overnight-gap adjustment.

    Only inputs ending before the order date are passed by capacity(). A zero
    estimate is retained and does not establish that execution is free.
    """
    high, low, close = bars.high.astype(float), bars.low.astype(float), bars.close.astype(float)
    overnight = pd.Series(np.where(low > close.shift(), low - close.shift(),
                                   np.where(high < close.shift(), high - close.shift(), 0)), index=bars.index)
    h2, l2 = high - overnight, low - overnight
    gamma = np.log(pd.concat([high.shift(), h2], axis=1).max(axis=1)
                   / pd.concat([low.shift(), l2], axis=1).min(axis=1)) ** 2
    # beta pairs previous day's range with today's overnight-adjusted range.
    beta = (np.log(high.shift() / low.shift()) ** 2 + np.log(h2 / l2) ** 2)
    denominator = 3 - 2 * np.sqrt(2)
    alpha = ((np.sqrt(2 * beta) - np.sqrt(beta)) / denominator
             - np.sqrt(gamma / denominator)).clip(lower=0, upper=20)
    spread = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    spread.iloc[0] = np.nan
    # Split dates create artificial overnight discontinuities; discard that pair.
    if "splits" in bars:
        split = bars.splits.fillna(0).ne(0)
        spread[split | split.shift(fill_value=False)] = np.nan
    return spread


def capacity(result, prices, settings=None):
    """Report order-based ADV capacity; no claim of profitable AUM capacity."""
    from backfill.engine import _fx

    settings = settings or Settings()
    rows = []
    # Cross-lot netting is not used in the simple engine: it conservatively
    # charges each lot transaction and sums absolute same-symbol order volume.
    if result.trades.empty:
        return pd.DataFrame()
    for (day, symbol, country), orders in result.trades.groupby(["date", "ticker", "country"]):
        bars = prices[symbol].loc[prices[symbol].index < day].tail(settings.adv_lookback)
        if len(bars) < settings.adv_lookback:
            rows.append(dict(date=day, ticker=symbol, status="insufficient_lagged_ADV"))
            continue
        dollar_volume = [float(row.close * row.volume) * _fx(prices, country, date)
                         for date, row in bars.iterrows()]
        adv = float(np.mean(dollar_volume))
        prior_equity = result.equity.loc[result.equity.index < day, "nav"]
        nav = float(prior_equity.iloc[-1]) if len(prior_equity) else settings.initial_nav
        order = float(orders.usd_notional.abs().sum())
        fraction = order / nav
        spread = corwin_schultz(bars)
        valid = spread.dropna()
        spread_estimate = float(valid.median()) if len(valid) else np.nan
        rows.append(dict(date=day, ticker=symbol, status="ok" if adv > 0 else "invalid_ADV",
                         adv_usd=adv, order_usd=order, participation=order / adv if adv > 0 else np.nan,
                         capacity_usd_1pct=0.01 * adv / fraction if fraction > 0 else np.nan,
                         capacity_usd_5pct=0.05 * adv / fraction if fraction > 0 else np.nan,
                         full_spread_bps=spread_estimate * 10_000,
                         assumption="participation bound only; impact model not yet calibrated"))
    return pd.DataFrame(rows)


def pre_drift(lots, prices, sessions=20):
    """Descriptive pre-entry abnormal returns; overlapping CARs are not independent."""
    from backfill.engine import _calendar

    rows = []
    for lot in lots.to_dict("records"):
        prior = _calendar(prices, lot["country"])
        prior = prior[prior < pd.Timestamp(lot["trade_date"])][-sessions - 1:]
        if len(prior) != sessions + 1:
            continue
        stock = prices[lot["ticker"]].reindex(prior).adj_close.pct_change(fill_method=None)
        hedge = prices[lot["hedge"]].reindex(prior).adj_close.pct_change(fill_method=None)
        rows.append(dict(lot_id=lot["lot_id"], event_id=lot["event_id"], ticker=lot["ticker"],
                         pre_trade_car=float((stock - lot["beta"] * hedge).sum()),
                         note="descriptive; may include post-listing days; no independent-event t-test"))
    return pd.DataFrame(rows)


def factor_regression(equity, factors):
    """Optional USD monthly factor check. Inputs are decimal returns, never filled."""
    import statsmodels.api as sm

    required = ["Mkt-RF", "HML", "Mom", "RF"]
    if not set(required).issubset(factors):
        raise ValueError("Factor CSV needs USD decimal Mkt-RF, HML, Mom and RF, indexed by month.")
    monthly = ((1 + equity.daily_return).resample("ME").prod() - 1)
    monthly.index = monthly.index.to_period("M")
    factors = factors.copy()
    factors.index = pd.to_datetime(factors.index).to_period("M")
    if factors.index.duplicated().any():
        raise ValueError("Duplicate factor months.")
    sample = pd.concat([monthly.rename("portfolio"), factors[required]], axis=1).dropna()
    if len(sample) < 12:
        raise ValueError("Fewer than 12 paired monthly factor observations.")
    fit = sm.OLS(sample.portfolio - sample.RF, sm.add_constant(sample[["Mkt-RF", "HML", "Mom"]])).fit(
        cov_type="HAC", cov_kwds={"maxlags": 3}, use_t=True)
    return dict(months=len(sample), first_month=str(sample.index.min()), last_month=str(sample.index.max()),
                coefficients=fit.params.to_dict(), t_stats=fit.tvalues.to_dict(),
                note="provided USD factor proxy; regional/currency suitability must be disclosed")


def write_report(result, prices, directory, settings, *, factors=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, frame in [("equity", result.equity), ("trades", result.trades),
                        ("lots", result.lots), ("eligibility", result.eligibility)]:
        frame.to_csv(directory / f"{name}.csv", index=name == "equity")
    capacity(result, prices, settings).to_csv(directory / "capacity.csv", index=False)
    pre_drift(result.lots, prices).to_csv(directory / "pre_drift.csv", index=False)
    summary = metrics(result, settings)
    if factors is not None:
        summary["factor_regression"] = factor_regression(result.equity, factors)
    (directory / "metrics.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    import os
    import tempfile
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "backfill-matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 3))
    ax.plot(result.equity.index, result.equity.nav / settings.initial_nav)
    ax.set(ylabel="NAV / initial capital", title="Backfill: net USD portfolio")
    fig.tight_layout()
    fig.savefig(directory / "equity.png", dpi=150)
    plt.close(fig)
    return summary
