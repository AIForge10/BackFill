"""Prepare an exploratory all-presentations-available supplier ledger, without prices.

Use one point-in-time FDA page per event and the existing dated owner map.
Never treat the FDA presentation list as a complete manufacturer's catalogue.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backfill.events import build_candidates, map_company, truth


def all_presentations_available(rows):
    if rows.empty:
        return False
    return bool((rows.availability.eq("available") &
                 ~rows.on_allocation.map(truth) &
                 rows.presentation.fillna("").str.strip().ne("")).all())


def audit_winners(ledger, suppliers, mapping):
    records = []
    owner_cache = {}
    for winner in ledger[ledger.role == "winner"].itertuples():
        page = suppliers[(suppliers.capture_ts == str(winner.capture_ts)) &
                         (suppliers.ai_key == winner.ai_key)].copy()
        def ticker(company):
            key = (str(company), str(winner.trade_ready_date))
            if key not in owner_cache:
                owner = map_company(key[0], mapping, winner.trade_ready_date)
                owner_cache[key] = None if owner is None else owner.ticker
            return owner_cache[key]
        parent = page[page.company.map(ticker).eq(winner.ticker)]
        if len(parent) != len(json.loads(winner.evidence)):
            raise ValueError("Ledger evidence does not match all parent rows on selected page.")
        qualifies = all_presentations_available(parent)
        evidence = parent[["company", "presentation", "availability", "availability_raw", "on_allocation"]].to_dict("records")
        records.append(dict(event_id=winner.event_id, ticker=winner.ticker, country=winner.country,
                            company=winner.company, product=winner.product, public_date=winner.public_date,
                            capture_date=winner.capture_date, capture_ts=winner.capture_ts,
                            trade_ready_date=winner.trade_ready_date, ai_key=winner.ai_key,
                            all_presentations_available=qualifies, presentation_rows=len(parent),
                            unique_presentations=parent.presentation.nunique(),
                            evidence=json.dumps(evidence, ensure_ascii=False)))
    return pd.DataFrame(records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source = args.data_root.resolve()
    files = {"events": source / "data/processed/shortage_events.csv",
             "suppliers": source / "data/processed/suppliers.csv",
             "mapping": source / "data/company_ticker_map.csv"}
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files.values()}
    events = pd.read_csv(files["events"])
    suppliers = pd.read_csv(files["suppliers"], dtype={"capture_ts": str})
    mapping = pd.read_csv(files["mapping"], keep_default_na=False)
    output = args.output or ROOT / "data/processed/full_availability"
    output.mkdir(parents=True, exist_ok=False)
    summaries = {}
    for window in (30, 60):
        ledger, _ = build_candidates(events, suppliers, mapping, window_days=window)
        audit = audit_winners(ledger, suppliers, mapping)
        qualified = audit[audit.all_presentations_available]
        keys = set(zip(qualified.event_id, qualified.ticker))
        strict = ledger[ledger.role.eq("winner") &
                        pd.Series([(e, t) in keys for e, t in zip(ledger.event_id, ledger.ticker)], index=ledger.index)]
        directory = output / f"capture{window}"
        directory.mkdir()
        audit.to_csv(directory / "audit.csv", index=False)
        strict.to_csv(directory / "winners.csv", index=False)
        qualified.to_csv(directory / "qualified_evidence.csv", index=False)
        summary = dict(original_positions=len(audit), original_events=audit.event_id.nunique(),
                       strict_positions=len(qualified), strict_events=qualified.event_id.nunique(),
                       strict_tickers=qualified.ticker.nunique(),
                       by_country=qualified.groupby("country").size().to_dict(),
                       by_ticker=qualified.groupby("ticker").size().to_dict())
        summaries[f"capture{window}"] = summary
        print(f"CAPTURE{window}", json.dumps(summary), flush=True)
        print(qualified[["ticker", "country", "event_id", "product", "unique_presentations"]].to_string(index=False), flush=True)
    for path, expected in hashes.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Concurrent source change: {path}")
    (output / "preparation.json").write_text(json.dumps(dict(
        classification="post-primary exploratory supplier-definition variant; data preparation only",
        source_hashes=hashes, summaries=summaries,
        rule="Every parent-owned row on the chosen archived formulation page is available, not on allocation, and has a nonempty presentation.",
        caveat="FDA-listed presentations only; not a complete product catalogue or verified spare production capacity."), indent=2) + "\n")
    print("OUTPUT", output, flush=True)


if __name__ == "__main__":
    main()
