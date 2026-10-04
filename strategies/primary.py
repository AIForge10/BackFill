"""Registered baseline: available suppliers, equal event capital, 60 sessions.

Edit signal selection here. Risk limits/costs live in Settings; fills and P&L
live in backfill.engine. This module never evaluates returns.
"""
import pandas as pd

import config
from backfill.settings import Settings

NAME = "backfill_primary"


def expand_specialist_basket(ledger, mapping):
    """Trade the US specialist complex on events that already have an available supplier.

    The archived FDA parent is often a diversified company, or a specialist that
    later delisted and has no price history. The hypothesis is about listed
    sterile-injectable specialists, for whom a shortage is material. Each event
    therefore goes long every US name flagged specialist and listed on the
    trade-ready date, except a specialist the same page marks disrupted.
    The placebo is the other US generic makers: not specialists, and not named
    on that page. Event capital is split across the long names.

    ADRs are left out. A diversified foreign parent (Dr. Reddy's) does not
    behave like a US sterile-injectable specialist when one US product is short.
    """
    from backfill.events import active_mapping, truth

    if "specialist" not in mapping.columns:
        raise ValueError("The specialist basket needs a mapping with a 'specialist' column.")
    eligible = set(ledger.loc[ledger.role == "winner", "event_id"])
    rows = []
    for event_id, group in ledger[ledger.event_id.isin(eligible)].groupby("event_id", sort=True):
        template = group.iloc[0]
        # Placebo rows are other generics, not companies named on the FDA page.
        on_page = set(group.loc[group.role != "placebo", "ticker"])
        disrupted = set(group.loc[group.role == "disrupted", "ticker"])
        active = active_mapping(mapping, template.trade_ready_date)
        active = active[(active.country == "US") & ~active.ticker.isin(["PRIVATE", "UNVERIFIED", ""])]
        is_spec = active.specialist.map(lambda value: str(value).strip() == "1")
        specialists = active[is_spec].drop_duplicates("ticker")
        specialists = specialists[~specialists.ticker.isin(disrupted)]
        if "notes" in specialists.columns:
            adr = specialists.notes.fillna("").str.contains(r"\bADR\b", case=False, regex=True)
            specialists = specialists[~adr]
        placebo = active[active.is_generic_maker.map(truth) & ~is_spec
                         & ~active.ticker.isin(on_page)].drop_duplicates("ticker")
        if specialists.empty:
            continue
        base = template.to_dict()
        n = int(len(specialists))
        for _, owner in specialists.sort_values("ticker").iterrows():
            rec = dict(base)
            rec.update(ticker=owner.ticker, country="US", benchmark=config.BENCHMARK["US"],
                       role="winner", company=owner.ticker, evidence="[]", control_definition="",
                       winner_count=n)
            rows.append(rec)
        for _, owner in placebo.sort_values("ticker").iterrows():
            rec = dict(base)
            rec.update(ticker=owner.ticker, country="US", benchmark=config.BENCHMARK["US"],
                       role="placebo", company="", evidence="[]", winner_count=n,
                       control_definition="US non-specialist generic maker, not named on the FDA page")
            rows.append(rec)
    return pd.DataFrame(rows, columns=list(ledger.columns))


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
