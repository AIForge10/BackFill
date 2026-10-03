"""Small calendar-time lot engine with next-close fills and no vendor imports.

Accounting uses adjusted-close total-return units for BOTH legs. Cash has a
zero return; hedge carry is charged separately. Positions are USD-valued using
daily FX marks. These are daily closing-mark assumptions, not intraday FX fills.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

import config
from backfill.settings import FX_SYMBOL, SECURITY_START, Settings


@dataclass
class Result:
    equity: pd.DataFrame
    trades: pd.DataFrame
    lots: pd.DataFrame
    eligibility: pd.DataFrame


def _calendar(prices, country):
    symbol = config.MARKET_INDEX[country]
    if symbol not in prices:
        raise ValueError(f"Local session reference missing: {symbol}")
    return prices[symbol].index


def _price(prices, symbol, day):
    if symbol not in prices or day not in prices[symbol].index:
        raise ValueError(f"Missing {symbol} bar on local session {day.date()}; cannot fill or shorten hold.")
    return float(prices[symbol].at[day, "adj_close"])


def _fx(prices, country, day):
    symbol = FX_SYMBOL[country]
    if symbol is None:
        return 1.0
    if symbol not in prices:
        raise ValueError(f"FX cache missing: {symbol}")
    quotes = prices[symbol].loc[:day, "close"]
    if quotes.empty or (day - quotes.index[-1]).days > 4:
        raise ValueError(f"FX quote missing/stale for {country} on {day.date()}")
    value = float(quotes.iloc[-1])
    return 1 / value if country == "IN" else value


def _mark(prices, symbol, country, day):
    """Carry a last mark over market holidays only; never over a missing session."""
    calendar = _calendar(prices, country)
    past = calendar[calendar <= day]
    if past.empty:
        raise ValueError(f"No {country} session before {day}")
    return _price(prices, symbol, past[-1]) * _fx(prices, country, day)


def schedule_lots(requests, prices, settings, exclusions=None):
    """Eligibility uses entry-known history; incomplete future bars fail the run.

    The registered end boundary determines which holds can mature; it is never
    inferred from a particular stock's last available quote.
    """
    exclusions = exclusions or {}
    scheduled, audit = [], []
    for request in requests.to_dict("records"):
        ticker, country = request["ticker"], request["country"]
        key = f"{request['event_id']}:{ticker}:{request.get('role', 'winner')}"
        base = dict(lot_id=key, event_id=request["event_id"], ticker=ticker)
        if ticker in exclusions:
            audit.append(dict(**base, reason="explicit_price_exclusion", detail=exclusions[ticker]))
            continue
        if ticker not in prices:
            raise ValueError(f"{ticker}: cache miss without an explicit disclosed exclusion")
        calendar = _calendar(prices, country)
        ready = pd.Timestamp(request["trade_ready_date"]).normalize()
        for source_date in ["public_date", "capture_date"]:
            if source_date in request and pd.Timestamp(request[source_date]).normalize() > ready:
                raise ValueError("Trade-ready date predates its evidence.")
        entry_index = int(calendar.searchsorted(ready, side="right"))
        if entry_index >= len(calendar):
            audit.append(dict(**base, reason="no_entry_inside_period"))
            continue
        entry = calendar[entry_index]
        if "known_at" in request:
            from backfill.settings import TIMEZONE
            close_hour, close_minute = {"US": (16, 0), "UK": (16, 30), "DE": (17, 30),
                                       "CH": (17, 30), "IN": (15, 30)}[country]
            close = (entry + pd.Timedelta(hours=close_hour, minutes=close_minute)).tz_localize(TIMEZONE[country])
            if pd.Timestamp(request["known_at"]) >= close.tz_convert("UTC"):
                raise ValueError("Entry is before information is known in the local market.")
        if entry < pd.Timestamp(settings.start):
            audit.append(dict(**base, reason="entry_before_period"))
            continue
        hold = int(request["hold_days"])
        if entry_index + hold >= len(calendar) or calendar[entry_index + hold] > pd.Timestamp(settings.end):
            audit.append(dict(**base, reason="hold_crosses_end_boundary"))
            continue
        exit_day = calendar[entry_index + hold]
        # Beta ends before entry, using exactly lookback paired return observations.
        history_dates = calendar[max(0, entry_index - settings.beta_lookback - 1):entry_index]
        hedge = request["hedge"]
        if len(history_dates) < settings.beta_lookback + 1:
            audit.append(dict(**base, reason="insufficient_beta_history"))
            continue
        if ticker in SECURITY_START and history_dates[0] < pd.Timestamp(SECURITY_START[ticker]):
            audit.append(dict(**base, reason="insufficient_security_history"))
            continue
        stock_history = prices[ticker].reindex(history_dates).adj_close
        hedge_history = prices[hedge].reindex(history_dates).adj_close
        if stock_history.isna().any():
            # IPO/predecessor history is never invented or spliced.
            audit.append(dict(**base, reason="insufficient_beta_history"))
            continue
        if hedge_history.isna().any():
            raise ValueError(f"{hedge}: incomplete benchmark history before {entry.date()}")
        stock_returns = stock_history.pct_change(fill_method=None).dropna()
        hedge_returns = hedge_history.pct_change(fill_method=None).dropna()
        variance = hedge_returns.var(ddof=1)
        if not np.isfinite(variance) or variance <= 0:
            audit.append(dict(**base, reason="undefined_beta"))
            continue
        beta = float(stock_returns.cov(hedge_returns) / variance)
        # Preflight future coverage without dropping affected positions: missing
        # exit/suspension data aborts accounting and needs a corporate-action audit.
        for symbol in [ticker, hedge]:
            required = calendar[entry_index:entry_index + hold + 1]
            if not required.isin(prices[symbol].index).all():
                raise ValueError(f"{symbol}: missing bar during required hold; cannot discard the lot")
        scheduled.append({**request, "lot_id": key, "trade_date": entry, "exit_date": exit_day, "beta": beta})
        audit.append(dict(**base, reason="eligible", trade_date=entry, exit_date=exit_day))
    return scheduled, pd.DataFrame(audit)


def run_portfolio(requests, prices, settings=None, *, exclusions=None):
    settings = settings or Settings()
    scheduled, eligibility = schedule_lots(requests, prices, settings, exclusions)
    if not scheduled:
        raise ValueError("No eligible lots. Inspect event/price eligibility; do not report an empty strategy.")
    # The same cached market-calendar union is used for winners and controls,
    # including inactive days. Never select a calendar from successful lots.
    countries = sorted(c for c, symbol in config.MARKET_INDEX.items() if symbol in prices)
    days = pd.DatetimeIndex(sorted(set().union(*[set(_calendar(prices, c)) for c in countries])))
    days = days[(days >= pd.Timestamp(settings.start)) & (days <= pd.Timestamp(settings.end))]
    arrivals = {}
    for lot in scheduled:
        arrivals.setdefault(lot["trade_date"], []).append(lot)
    active, lot_records, trades, equity = [], [], [], []
    cash = nav = peak = settings.initial_nav
    risk_scale, risk_age = 1.0, 0
    pending_risk = None
    previous_day = None

    def transaction(lot, leg, quantity, day, reason):
        nonlocal cash
        symbol = lot["ticker"] if leg == "stock" else lot["hedge"]
        mark = _price(prices, symbol, day) * _fx(prices, lot["country"], day)
        notional = quantity * mark
        bps = settings.costs_bps[lot["country"]] if leg == "stock" else settings.hedge_cost_bps
        cost = abs(notional) * bps * settings.cost_multiplier / 10_000
        cash -= notional + cost
        trades.append(dict(date=day, lot_id=lot["lot_id"], event_id=lot["event_id"],
                           ticker=symbol, country=lot["country"], leg=leg, reason=reason,
                           units=quantity, usd_notional=notional, cost=cost))

    def values(lot, day):
        return (lot["stock_units"] * _mark(prices, lot["ticker"], lot["country"], day),
                lot["hedge_units"] * _mark(prices, lot["hedge"], lot["country"], day))

    for day in days:
        prior_nav = nav
        carry_cost = 0.0
        # All decisions today use the PRIOR portfolio close. Today's marks fill
        # predetermined orders and account for P&L; they never select a signal.
        if previous_day is not None:
            prior_values = [values(lot, previous_day) for lot in active]
            hedge_notional = sum(abs(h) for _, h in prior_values)
            carry_cost = hedge_notional * settings.hedge_carry_bps_year * settings.cost_multiplier / 10_000 * (
                day - previous_day).days / 365.25
            cash -= carry_cost
        # Risk change orders wait until each lot's next actual local session.
        for lot in active[:]:
            if day not in _calendar(prices, lot["country"]):
                continue
            if day == lot["exit_date"]:
                transaction(lot, "stock", -lot["stock_units"], day, "expiry")
                transaction(lot, "hedge", -lot["hedge_units"], day, "expiry")
                active.remove(lot)
                continue
            if pending_risk is not None and lot["risk_scale"] != risk_scale:
                ratio = risk_scale / lot["risk_scale"]
                for leg in ["stock", "hedge"]:
                    delta = lot[f"{leg}_units"] * (ratio - 1)
                    transaction(lot, leg, delta, day, "de_risk" if ratio < 1 else "restore")
                    lot[f"{leg}_units"] *= ratio
                lot["risk_scale"] = risk_scale
        if pending_risk is not None and all(l["risk_scale"] == risk_scale for l in active):
            pending_risk = None
        # Enforce drifted caps with reductions only. Restored lots are also clipped.
        # Decisions use lagged prices; orders execute at the next local close.
        lag_day = previous_day if previous_day is not None else day
        name_values, country_values = {}, {}
        for lot in active:
            stock, _ = values(lot, lag_day)
            name_values[lot["ticker"]] = name_values.get(lot["ticker"], 0) + stock
            country_values[lot["country"]] = country_values.get(lot["country"], 0) + stock
        name_factors = {t: min(1.0, settings.name_cap * prior_nav / v) for t, v in name_values.items()}
        country_factors = {c: min(1.0, settings.country_cap * prior_nav / v) for c, v in country_values.items()}
        cap_values = []
        for lot in active:
            factor = min(name_factors[lot["ticker"]], country_factors[lot["country"]])
            s, h = values(lot, lag_day)
            cap_values.append((lot, factor, s * factor, h * factor))
        long = sum(s for _, _, s, _ in cap_values)
        gross = sum(abs(s) + abs(h) for _, _, s, h in cap_values)
        net = abs(sum(s + h for _, _, s, h in cap_values))
        foreign = sum(s for l, _, s, _ in cap_values if l["country"] != "US")
        global_factor = min([1.0] + [limit * prior_nav / value for limit, value in
                                    [(settings.sector_cap, long), (settings.gross_cap, gross),
                                     (settings.net_cap, net), (settings.foreign_long_cap, foreign)] if value > 0])
        for lot, factor, _, _ in cap_values:
            factor *= global_factor
            if factor < 1 - 1e-12 and day in _calendar(prices, lot["country"]):
                for leg in ["stock", "hedge"]:
                    transaction(lot, leg, lot[f"{leg}_units"] * (factor - 1), day, "cap_reduction")
                    lot[f"{leg}_units"] *= factor
        # Entry allocations are simultaneous, avoiding ticker-order bias in caps.
        new = [dict(lot) for lot in arrivals.get(day, [])]
        if new:
            existing = [(lot, *values(lot, lag_day)) for lot in active]
            desired = {l["lot_id"]: l["weight"] * prior_nav * risk_scale for l in new}
            for field, cap in [("ticker", settings.name_cap), ("country", settings.country_cap)]:
                for value in {l[field] for l in new}:
                    present = sum(s for l, s, _ in existing if l[field] == value)
                    wanted = sum(desired[l["lot_id"]] for l in new if l[field] == value)
                    factor = min(1.0, max(0, cap * prior_nav - present) / wanted) if wanted else 0
                    for lot in new:
                        if lot[field] == value:
                            desired[lot["lot_id"]] *= factor
            existing_long = sum(s for _, s, _ in existing)
            existing_gross = sum(abs(s) + abs(h) for _, s, h in existing)
            existing_net = sum(s + h for _, s, h in existing)
            existing_foreign = sum(s for l, s, _ in existing if l["country"] != "US")
            new_long = sum(desired.values())
            new_gross = sum(desired[l["lot_id"]] * (1 + abs(l["beta"])) for l in new)
            new_net = sum(desired[l["lot_id"]] * (1 - l["beta"]) for l in new)
            new_foreign = sum(desired[l["lot_id"]] for l in new if l["country"] != "US")
            factors = [1.0]
            for limit, present, wanted in [(settings.sector_cap, existing_long, new_long),
                                          (settings.gross_cap, existing_gross, new_gross),
                                          (settings.foreign_long_cap, existing_foreign, new_foreign)]:
                if wanted > 0:
                    factors.append(max(0, limit * prior_nav - present) / wanted)
            if new_net > 0:
                factors.append(max(0, settings.net_cap * prior_nav - existing_net) / new_net)
            elif new_net < 0:
                factors.append(max(0, settings.net_cap * prior_nav + existing_net) / -new_net)
            factor = min(factors)
            for lot in new:
                amount = desired[lot["lot_id"]] * factor
                lot_records.append({**lot, "entry_usd": amount, "requested_usd": lot["weight"] * prior_nav,
                                    "entry_risk_scale": risk_scale})
                if amount <= 1e-10:
                    continue
                fx = _fx(prices, lot["country"], day)
                lot["stock_units"] = amount / (_price(prices, lot["ticker"], day) * fx)
                lot["hedge_units"] = -lot["beta"] * amount / (_price(prices, lot["hedge"], day) * fx)
                lot["risk_scale"] = risk_scale
                transaction(lot, "stock", lot["stock_units"], day, "entry")
                transaction(lot, "hedge", lot["hedge_units"], day, "entry")
                active.append(lot)
        marks = [values(lot, day) for lot in active]
        nav = cash + sum(s + h for s, h in marks)
        if not np.isfinite(nav) or nav <= 0:
            raise ValueError("Nonpositive/invalid NAV: stop and inspect accounting.")
        peak = max(peak, nav)
        equity.append(dict(date=day, nav=nav, daily_return=nav / prior_nav - 1,
                           cash=cash, long_usd=sum(s for s, _ in marks),
                           gross_usd=sum(abs(s) + abs(h) for s, h in marks),
                           net_usd=sum(s + h for s, h in marks), active_lots=len(active), risk_scale=risk_scale,
                           hedge_carry_cost=carry_cost))
        if risk_scale == 1 and nav <= peak * (1 - settings.drawdown_trigger):
            risk_scale, risk_age, pending_risk = 0.5, 0, "reduce"
        elif risk_scale == 0.5:
            risk_age += 1
            if risk_age >= settings.recovery_sessions:
                # Restore after the fixed cooldown. If still below the threshold,
                # it can retrigger only at a later close, never using future recovery.
                risk_scale, pending_risk = 1.0, "restore"
        previous_day = day
    if active:
        raise ValueError("Unclosed lots at period end: expiry/calendar accounting failed.")
    return Result(pd.DataFrame(equity).set_index("date"), pd.DataFrame(trades),
                  pd.DataFrame(lot_records), eligibility)
