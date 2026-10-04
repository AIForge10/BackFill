"""Pure entry rules for the frozen exploratory candidate; no performance selection."""
import json

import pandas as pd


RULES = ("delay20_hold5", "below_sma60_hold5", "below_sma60_disrupted_hold5")


def strict_presentations(evidence):
    """Every recorded presentation, including nonempty labels, must qualify."""
    rows = json.loads(evidence) if isinstance(evidence, str) else evidence
    return bool(rows) and all(
        bool(str(row.get("presentation", "")).strip())
        and row.get("availability") == "available"
        and not row.get("on_allocation", False)
        for row in rows
    )


def counterpart_audit(winners, ledger):
    """Require another listed owner on the exact archived formulation capture.

    This is an evidence match, not proof of substitutable strength, route or SKU.
    The frozen ledger contains mapped listed owners only.
    """
    output = []
    for row in winners.to_dict("records"):
        peers = ledger[
            (ledger.event_id == row["event_id"])
            & (ledger.ai_key == row["ai_key"])
            & (ledger.capture_ts.astype(str) == str(row["capture_ts"]))
            & (ledger.role == "disrupted")
            & (ledger.ticker != row["ticker"])
        ]
        output.append(dict(event_id=row["event_id"], ticker=row["ticker"],
            exact_capture_listed_disrupted=not peers.empty,
            disrupted_owners=";".join(sorted(peers.ticker.unique())),
            evidence_scope="same formulation capture; exact SKU substitutability unverified"))
    return pd.DataFrame(output)


def build_requests(rows, prices, calendar, rule, event_weight=0.05, *, counterparts=None,
                   exclusions=None):
    """Size first, then filter using only bars before the first eligible close."""
    if rule not in RULES:
        raise ValueError(f"Unknown frozen rule: {rule}")
    exclusions = exclusions or {}
    data = rows[rows.country == "US"].drop_duplicates(["event_id", "ticker"]).copy()
    data["weight"] = event_weight / data.groupby("event_id").ticker.transform("nunique")
    data["hold_days"] = 5
    data["hedge"] = "SPY"
    data["evidence_ready_date"] = data.trade_ready_date
    selected, audit = [], []
    for row in data.to_dict("records"):
        first = int(calendar.searchsorted(pd.Timestamp(row["trade_ready_date"]), side="right"))
        record = dict(event_id=row["event_id"], ticker=row["ticker"], weight=row["weight"],
                      rule=rule, evidence_ready_date=row["evidence_ready_date"])
        if first >= len(calendar):
            audit.append({**record, "reason": "no_first_eligible_session"})
            continue
        row["first_eligible_date"] = calendar[first].date().isoformat()
        if "disrupted" in rule:
            match = counterparts[(counterparts.event_id == row["event_id"])
                                 & (counterparts.ticker == row["ticker"])]
            if match.empty or not bool(match.iloc[0].exact_capture_listed_disrupted):
                audit.append({**record, "reason": "no_other_listed_disrupted_on_exact_capture"})
                continue
        if rule != "delay20_hold5" and row["ticker"] not in exclusions:
            if row["ticker"] not in prices:
                raise ValueError(f"Unexplained price cache miss: {row['ticker']}")
            dates = calendar[max(0, first - 60):first]
            history = prices[row["ticker"]].adj_close.reindex(dates)
            if len(history) != 60 or history.isna().any():
                audit.append({**record, "reason": "insufficient_SMA60_history"})
                continue
            row["signal_close"] = float(history.iloc[-1])
            row["signal_sma60"] = float(history.mean())
            row["signal_date"] = dates[-1].date().isoformat()
            if row["signal_close"] >= row["signal_sma60"]:
                audit.append({**record, "reason": "preceding_close_not_below_SMA60",
                              "signal_close": row["signal_close"], "signal_sma60": row["signal_sma60"]})
                continue
        if rule == "delay20_hold5":
            # The engine fills strictly AFTER ready; do not shift by calendar days.
            row["trade_ready_date"] = calendar[min(first + 19, len(calendar) - 1)].date().isoformat()
        selected.append(row)
        audit.append({**record, "reason": "request_selected"})
    return pd.DataFrame(selected, columns=list(data.columns) + [
        "first_eligible_date", "signal_close", "signal_sma60", "signal_date"]), pd.DataFrame(audit)
