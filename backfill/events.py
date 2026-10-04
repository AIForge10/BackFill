"""Turn archived supplier evidence into candidates, never into backdated fills.

The FDA-page nonlisted controls are explicitly weaker than verified nonmakers.
No price or return data is needed here.
"""
import json
import re

import pandas as pd

import config

FLAGS = ["date_uncertain", "left_censored", "rename_window", "spike_week", "rename_suspect"]
POSITION_COLUMNS = ["event_id", "product", "ai_key", "ticker", "country", "benchmark",
                    "public_date", "capture_date", "capture_ts", "trade_ready_date", "known_at",
                    "role", "company", "evidence", "control_definition", "winner_count", *FLAGS]


def truth(value):
    return str(value).strip().lower() in {"true", "1", "yes"}


def active_mapping(mapping, date):
    date = pd.Timestamp(date)
    start = pd.to_datetime(mapping.listed_from, errors="coerce")
    end = pd.to_datetime(mapping.listed_to, errors="coerce")
    return mapping[(start.isna() | (start <= date)) & (end.isna() | (end >= date))]


def map_company(company, mapping, date):
    """An unmatched/ambiguous mapping is an audit failure, never a guessed ticker."""
    matches = active_mapping(mapping, date)
    matches = matches[matches.company_pattern.map(lambda p: bool(re.search(p, company, re.I)))]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous dated owner mapping for {company!r} on {date}")
    return None if matches.empty else matches.iloc[0]


def build_candidates(events, suppliers, mapping, *, window_days=30,
                     include_allocation=False, exclude_uncertain=False,
                     include_flags=False, final=False):
    """Return position candidates and a reasoned event/supplier audit.

    Multi-key events use ONE page: latest prior capture, otherwise earliest
    subsequent capture. Ties use ai_key, avoiding future knowledge of winners
    on other pages. ai_key retains formulation; coarse_key is never a supplier join.
    """
    if window_days not in (30, 60, 180):
        raise ValueError("Only predeclared 30/60/180-day supplier windows are supported.")
    events, suppliers = events.copy(), suppliers.copy()
    mapping = mapping.fillna("").copy()
    events["public_date"] = pd.to_datetime(events.public_date)
    suppliers["capture_date"] = pd.to_datetime(suppliers.capture_date)
    if "capture_ts" not in suppliers:
        raise ValueError("Supplier capture timestamps are required for provenance.")
    suppliers["capture_ts"] = suppliers.capture_ts.astype(str).str.replace(r"\.0$", "", regex=True)
    suppliers["company_update_date"] = pd.to_datetime(
        suppliers.get("company_update_date", pd.Series(index=suppliers.index, dtype=str)), errors="coerce")
    start = pd.Timestamp(config.OOS_START if final else config.IS_START)
    end = pd.Timestamp(config.OOS_END) if final else pd.Timestamp(config.OOS_START) - pd.Timedelta(days=1)
    events = events[events.public_date.between(start, end)]
    suppliers = suppliers[suppliers.capture_date <= end]
    records, audit = [], []
    for event_id, group in events.groupby("event_id", sort=True):
        event = group.iloc[0]
        public = event.public_date
        flags = {f: any(group.get(f, pd.Series(False, index=group.index)).map(truth)) for f in FLAGS}
        reason = None
        if flags["left_censored"]:
            reason = "left_censored"
        elif not include_flags and any(flags[f] for f in ["rename_window", "spike_week", "rename_suspect"]):
            reason = "artifact_flag"
        elif exclude_uncertain and flags["date_uncertain"]:
            reason = "date_uncertain"
        if reason:
            audit.append(dict(event_id=event_id, ticker="", stage="event", reason=reason))
            continue
        pages = suppliers[suppliers.ai_key.isin(group.ai_key)]
        pages = pages[pages.capture_date.between(public - pd.Timedelta(days=30),
                                               public + pd.Timedelta(days=window_days))]
        captures = pages[["capture_date", "capture_ts", "ai_key"]].drop_duplicates()
        prior = captures[captures.capture_date <= public]
        if not prior.empty:
            chosen = prior.sort_values(["capture_ts", "ai_key"], ascending=[False, True]).iloc[0]
        elif not captures.empty:
            chosen = captures.sort_values(["capture_ts", "ai_key"]).iloc[0]
        else:
            audit.append(dict(event_id=event_id, ticker="", stage="event", reason="no_capture_in_window"))
            continue
        page = pages[(pages.capture_ts == chosen.capture_ts) & (pages.ai_key == chosen.ai_key)]
        if (page.company_update_date > chosen.capture_date).any():
            audit.append(dict(event_id=event_id, ticker="", stage="event", reason="future_revision_in_capture"))
            continue
        # A resolved/discontinued page cannot establish supply in a current shortage.
        if "page_status" in page and not page.page_status.fillna("").str.contains(
                "Currently in Shortage", case=False).all():
            audit.append(dict(event_id=event_id, ticker="", stage="event", reason="capture_not_current_shortage"))
            continue
        ready = max(public, chosen.capture_date)
        known = max(public.tz_localize("UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1),
                    pd.to_datetime(chosen.capture_ts, format="%Y%m%d%H%M%S", utc=True))
        common = dict(event_id=event_id, product=event["product"], ai_key=chosen.ai_key,
                      public_date=public.date(), capture_date=chosen.capture_date.date(),
                      capture_ts=chosen.capture_ts, trade_ready_date=ready.date(),
                      known_at=known.isoformat(), **flags)
        mapped = []
        for _, row in page.iterrows():
            owner = map_company(str(row.company), mapping, ready)
            if owner is None or owner.ticker in {"PRIVATE", "UNVERIFIED"}:
                reason = "unmapped" if owner is None else owner.ticker.lower()
                audit.append(dict(event_id=event_id, ticker="" if owner is None else owner.ticker,
                                  company=row.company, stage="supplier", reason=reason))
                continue
            allocation = truth(row.get("on_allocation", False))
            role = ("winner" if row.availability == "available" and (include_allocation or not allocation)
                    else "disrupted" if row.availability == "disrupted" else "nonwinner")
            mapped.append(dict(**common, ticker=owner.ticker, country=owner.country,
                               benchmark=config.BENCHMARK[owner.country], role=role,
                               company=row.company, control_definition="",
                               evidence=json.dumps({"presentation": row.presentation,
                                                    "availability": row.availability_raw,
                                                    "on_allocation": allocation}, ensure_ascii=False)))
        # Keep all mapped supplier roles so controls cannot accidentally include nonwinners.
        present = {r["ticker"] for r in mapped}
        winner_tickers = {r["ticker"] for r in mapped if r["role"] == "winner"}
        # One parent can have mixed presentation states: winner takes precedence for
        # selection, while all presentation evidence remains in the evidence JSON.
        for ticker in sorted(present):
            rows = [r for r in mapped if r["ticker"] == ticker]
            representative = next((r for r in rows if r["role"] == "winner"), rows[0]).copy()
            representative["evidence"] = json.dumps([json.loads(r["evidence"]) for r in rows])
            representative["winner_count"] = len(winner_tickers)
            records.append(representative)
        if not winner_tickers:
            audit.append(dict(event_id=event_id, ticker="", stage="event", reason="no_listed_available_winner"))
            continue
        markets = {r["country"] for r in mapped if r["role"] == "winner"}
        peers = active_mapping(mapping, ready)
        peers = peers[peers.is_generic_maker.map(truth) & peers.country.isin(markets)
                      & ~peers.ticker.isin(present | {"PRIVATE", "UNVERIFIED"})]
        for _, peer in peers.drop_duplicates("ticker").sort_values("ticker").iterrows():
            records.append(dict(**common, ticker=peer.ticker, country=peer.country,
                                benchmark=config.BENCHMARK[peer.country], role="placebo",
                                company="", evidence="[]", winner_count=len(winner_tickers),
                                control_definition="FDA-page nonlisted generic-maker control; manufacture absence unverified"))
        audit.append(dict(event_id=event_id, ticker="", stage="event", reason="included",
                          winners=len(winner_tickers), controls=peers.ticker.nunique()))
    return pd.DataFrame(records, columns=POSITION_COLUMNS), pd.DataFrame(audit)
