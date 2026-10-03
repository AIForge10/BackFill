"""Registered baseline: available suppliers, equal event capital, 60 sessions.

Edit signal selection here. Risk limits/costs live in Settings; fills and P&L
live in backfill.engine. This module never evaluates returns.
"""
import pandas as pd

from backfill.settings import Settings

NAME = "backfill_primary"


def select(events, suppliers=None, prices=None, *, settings=None, role="winner"):
    """Return independent lot requests. Dates are scheduled by the engine.

    events is the evidence ledger produced by 05_events.py. The unused suppliers
    and prices arguments preserve the repository's strategy interface.
    """
    settings = settings or Settings()
    if role not in {"winner", "placebo"}:
        raise ValueError("The baseline supports winner/control longs only; shorts are separate research.")
    selected = events[events.role == role].copy()
    selected = selected.drop_duplicates(["event_id", "ticker"])
    if selected.empty:
        return selected.assign(weight=pd.Series(dtype=float), hold_days=pd.Series(dtype=int),
                               hedge=pd.Series(dtype=str), trade_date=pd.Series(dtype="datetime64[ns]"))
    denominator = (selected.winner_count.astype(int) if role == "winner"
                   else selected.groupby("event_id").ticker.transform("nunique"))
    selected["weight"] = settings.event_weight / denominator
    selected["hold_days"] = settings.hold_days
    selected["hedge"] = selected.benchmark
    # trade_date is filled only when a separately cached local calendar is available.
    selected["trade_date"] = pd.NaT
    return selected.reset_index(drop=True)
