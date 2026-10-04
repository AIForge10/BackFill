"""v3 (docs/PREREG_v3_injectable_basket.md): shortage-date events, no supplier page.

Each qualifying sterile-injectable shortage goes long every US-listed specialist
listed on the trade-ready date; the placebo is the US non-specialist generic
makers listed that day. Delisted specialists stay in the event's name count, so
their share is held as cash by the engine's price exclusions, never reallocated.
"""
import re

import pandas as pd

import config
from backfill.events import FLAGS, POSITION_COLUMNS, active_mapping, truth


def build_date_events(events, mapping, *, pattern, max_gap_days=60, final=False):
    events = events.copy()
    mapping = mapping.fillna("").copy()
    events["public_date"] = pd.to_datetime(events.public_date)
    start = pd.Timestamp(config.OOS_START if final else config.IS_START)
    end = pd.Timestamp(config.OOS_END) if final else pd.Timestamp(config.OOS_START) - pd.Timedelta(days=1)
    events = events[events.public_date.between(start, end)]
    if "specialist" not in mapping.columns:
        raise ValueError("v3 needs a mapping with a 'specialist' column.")
    records, audit = [], []
    for event_id, group in events.groupby("event_id", sort=True):
        event = group.iloc[0]
        public = event.public_date
        flags = {f: any(group.get(f, pd.Series(False, index=group.index)).map(truth)) for f in FLAGS}
        gap = pd.to_numeric(group.get("prev_snapshot_gap_days"), errors="coerce").max()
        if flags["left_censored"]:
            reason = "left_censored"
        elif any(flags[f] for f in ["rename_window", "spike_week", "rename_suspect"]):
            reason = "artifact_flag"
        elif not re.search(pattern, str(event["product"]), re.I):
            reason = "not_injectable"
        elif pd.notna(gap) and gap > max_gap_days:
            reason = "archive_gap"
        else:
            reason = None
        if reason:
            audit.append(dict(event_id=event_id, ticker="", stage="event", reason=reason))
            continue
        active = active_mapping(mapping, public)
        active = active[(active.country == "US") & ~active.ticker.isin(["PRIVATE", "UNVERIFIED", ""])]
        is_spec = active.specialist.map(lambda v: str(v).strip() == "1")
        adr = active.notes.str.contains(r"\bADR\b", case=False, regex=True)
        longs = active[is_spec & ~adr].drop_duplicates("ticker")
        controls = active[active.is_generic_maker.map(truth) & ~is_spec].drop_duplicates("ticker")
        if longs.empty:
            audit.append(dict(event_id=event_id, ticker="", stage="event", reason="no_listed_specialist"))
            continue
        known = public.tz_localize("UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        common = dict(event_id=event_id, product=event["product"], ai_key=event.get("ai_key", ""),
                      public_date=public.date(), capture_date=public.date(), capture_ts="",
                      trade_ready_date=public.date(), known_at=known.isoformat(), **flags)
        for _, owner in longs.sort_values("ticker").iterrows():
            records.append(dict(**common, ticker=owner.ticker, country="US", benchmark=config.BENCHMARK["US"],
                                role="winner", company=owner.ticker, evidence="[]", control_definition="",
                                winner_count=len(longs)))
        for _, owner in controls.sort_values("ticker").iterrows():
            records.append(dict(**common, ticker=owner.ticker, country="US", benchmark=config.BENCHMARK["US"],
                                role="placebo", company="", evidence="[]", winner_count=len(longs),
                                control_definition="US non-specialist generic maker listed on the trade date"))
        audit.append(dict(event_id=event_id, ticker="", stage="event", reason="included",
                          winners=len(longs), controls=len(controls)))
    return pd.DataFrame(records, columns=POSITION_COLUMNS), pd.DataFrame(audit)


def build_disrupted_book(ledger, suppliers, mapping):
    """v4 (docs/PREREG_v4_disrupted_short.md): the disrupted parents on each event's chosen page.

    Re-reads the same page the primary chose, so page selection is unchanged. A
    parent counts when at least one presentation is disrupted and none is available.
    """
    from backfill.events import map_company

    mapping = mapping.fillna("").copy()
    sup = suppliers.copy()
    sup["capture_ts"] = sup.capture_ts.astype(str).str.replace(r"\.0$", "", regex=True)
    pages = ledger.drop_duplicates("event_id")
    records, audit = [], []
    for _, ev in pages.iterrows():
        page = sup[(sup.capture_ts == str(ev.capture_ts)) & (sup.ai_key == ev.ai_key)]
        states, on_page = {}, set()
        for _, row in page.iterrows():
            owner = map_company(str(row.company), mapping, ev.trade_ready_date)
            if owner is None or owner.ticker in {"PRIVATE", "UNVERIFIED"}:
                continue
            on_page.add(owner.ticker)
            if owner.country == "US":
                states.setdefault(owner.ticker, set()).add(row.availability)
        book = sorted(t for t, s in states.items() if "disrupted" in s and "available" not in s)
        if not book:
            audit.append(dict(event_id=ev.event_id, ticker="", stage="event", reason="no_listed_disrupted"))
            continue
        common = {c: ev[c] for c in POSITION_COLUMNS if c not in
                  {"ticker", "country", "benchmark", "role", "company", "evidence", "control_definition", "winner_count"}}
        for ticker in book:
            records.append(dict(**common, ticker=ticker, country="US", benchmark=config.BENCHMARK["US"],
                                role="winner", company=ticker, evidence="[]", winner_count=len(book),
                                control_definition="v4 disrupted parent (measured long; short = negative)"))
        peers = active_mapping(mapping, ev.trade_ready_date)
        peers = peers[peers.is_generic_maker.map(truth) & (peers.country == "US")
                      & ~peers.ticker.isin(on_page | {"PRIVATE", "UNVERIFIED", ""})]
        for _, peer in peers.drop_duplicates("ticker").sort_values("ticker").iterrows():
            records.append(dict(**common, ticker=peer.ticker, country="US", benchmark=config.BENCHMARK["US"],
                                role="placebo", company="", evidence="[]", winner_count=len(book),
                                control_definition="US generic maker not named on the FDA page"))
        audit.append(dict(event_id=ev.event_id, ticker="", stage="event", reason="included", winners=len(book)))
    return pd.DataFrame(records, columns=POSITION_COLUMNS), pd.DataFrame(audit)
