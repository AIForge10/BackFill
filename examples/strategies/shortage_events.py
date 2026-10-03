"""
Drug Shortage Winners - event-driven strategy for the Webull backtrader starter.

Put this file in examples/strategies/ and set WEBULL_STRATEGY=shortage_events in .env.
WEBULL_SYMBOLS must include every ticker in the events file, plus the hedge ETF (XLV).

Reads data/events.csv (from build_events.py): event_date, drug, ticker, side

Rules (must match HYPOTHESIS.md):
    - On the first bar on/after the event date, open the position; it fills at the NEXT bar.
    - Winners (side +1) are bought, companies in shortage (side -1) are shorted.
    - Each event gets PER_EVENT of equity; one name is capped at MAX_PER_NAME.
    - Each position is held HOLD_DAYS trading bars, then closed.
    - Net exposure is hedged with the health-care ETF so we measure the drug effect,
      not the sector or the market.
"""
import os

import backtrader as bt
import pandas as pd

EVENTS_FILE = os.getenv("SHORTAGE_EVENTS_FILE", "data/events.csv")
STALE_DAYS = 5  # ignore events older than this when first seen (e.g. before the backtest start)


class ShortageEvents(bt.Strategy):
    params = dict(
        hold_days=int(os.getenv("HOLD_DAYS", 40)),
        per_event=0.10,
        max_per_name=0.20,
        hedge="XLV",
    )

    def __init__(self):
        self.names = {d._name: d for d in self.datas}
        ev = pd.read_csv(EVENTS_FILE, parse_dates=["event_date"])
        ev = ev[ev["ticker"].isin(self.names)].sort_values("event_date")
        self.pending = ev.to_dict("records")
        self.active = []
        self.prev_targets = None

    def prenext(self):
        # Some tickers list later (e.g. AMRX in 2018); trade the ones that have data.
        self.next()

    def next(self):
        today = pd.Timestamp(self.datetime.date(0))

        for a in self.active:
            a["bars_left"] -= 1
        self.active = [a for a in self.active if a["bars_left"] > 0]

        while self.pending and self.pending[0]["event_date"] <= today:
            e = self.pending.pop(0)
            if (today - e["event_date"]).days > STALE_DAYS:
                continue
            self.active.append(dict(ticker=e["ticker"], side=e["side"],
                                    bars_left=self.p.hold_days))

        targets = {}
        for a in self.active:
            targets[a["ticker"]] = targets.get(a["ticker"], 0.0) + a["side"] * self.p.per_event
        cap = self.p.max_per_name
        targets = {t: max(-cap, min(cap, w)) for t, w in targets.items()}
        if self.p.hedge in self.names:
            targets[self.p.hedge] = -sum(targets.values())

        if targets == self.prev_targets:
            return
        for name, d in self.names.items():
            if len(d) == 0:
                continue  # no data yet for this ticker
            self.order_target_percent(data=d, target=targets.get(name, 0.0))
        self.prev_targets = targets


STRATEGY_CLASS = ShortageEvents
