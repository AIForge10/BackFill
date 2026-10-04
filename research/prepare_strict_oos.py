"""FDA-only holdout preparation. Never import vendors or load price returns."""
import argparse
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backfill.events import build_candidates
from backfill.guardrails import require_oos_freeze
from backfill.prices import sha256
from full_availability import audit_winners


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "src" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-root", type=Path, required=True)
    args = ap.parse_args()
    require_oos_freeze(ROOT)
    output = ROOT / "data/raw/oos/signals"
    output.mkdir(parents=True, exist_ok=False)
    pm = module("strict_oos_main", "03_parse_main.py")
    pm.RAW = args.source_root / "data/raw/main"
    with contextlib.redirect_stdout(io.StringIO()):
        status, pages, warnings = pm.parse_all(final=True)
    status = status[~status.duplicated(["snapshot_date", "ai_key", "status"])]
    status = status[status.snapshot_date <= pd.Timestamp("2026-10-01")]
    pages = pages[pages.snapshot_date <= pd.Timestamp("2026-10-01")]
    oos_pages = pages[pages.snapshot_date >= pd.Timestamp("2024-10-01")]
    if not oos_pages.ok.all():
        raise ValueError("Unparseable holdout list page; absence cannot be inferred.")
    events = pm.build_events(status, pages.loc[pages.ok, "snapshot_date"])
    # The existing primary is preserved separately. Exploratory strict winners
    # cannot treat the year-long archival gap as verified product absence.
    gaps = pages.loc[pages.ok].sort_values("snapshot_date").snapshot_date
    gap_dates = set(gaps[gaps.diff().dt.days >= 180].dt.date)
    gap_events = events[events.public_date.isin(gap_dates)]
    gap_events.to_csv(output / "archive_gap_events.csv", index=False)
    status.to_csv(output / "main_status.csv", index=False)
    events.to_csv(output / "shortage_events.csv", index=False)
    pages.to_csv(output / "list_parse_audit.csv", index=False)
    print("Parsed lists; building supplier evidence (no prices).", flush=True)

    pdm = module("strict_oos_detail", "04_parse_details.py")
    pdm.PROC = args.source_root / "data/processed"
    names = pdm.file_index()
    rows, detail_audit = [], []
    for file in sorted((args.source_root / "data/raw/detail").rglob("*.html")):
        cap = pd.to_datetime(file.name[:8], format="%Y%m%d")
        if not pd.Timestamp("2024-09-01") <= cap <= pd.Timestamp("2026-10-01"):
            continue
        ts, original = names.get(file.name, (file.name.split("_")[0], ""))
        payload = file.read_bytes()
        soup = BeautifulSoup(payload, "lxml")
        head = pdm.page_header(soup)
        count = 0
        for heading, body in pdm.company_blocks(soup):
            match = pdm.HEAD_RE.match(heading)
            company, update, updated = ((match.group(1), match.group(2) or "", match.group(3))
                                        if match else (heading, "", None))
            for presentation, available, related, reason in pdm.parse_block(body):
                rows.append(dict(capture_date=cap.date(), capture_ts=ts,
                    ai_key=pm.ai_key(original) if original else "", **head,
                    company=company.strip(), company_update=update,
                    company_update_date=pd.to_datetime(updated, format="%m/%d/%Y").date() if updated else None,
                    presentation=presentation, availability_raw=available,
                    related_info=related, shortage_reason=reason))
                count += 1
        detail_audit.append(dict(file=str(file), sha256=sha256(file), rows=count,
                                 matched=bool(original), page_status=head["page_status"]))
    suppliers = pd.DataFrame(rows)
    suppliers["availability"] = suppliers.availability_raw.map(pdm.classify)
    suppliers.loc[suppliers.page_status.str.contains("Discontinu", case=False), "availability"] = "discontinued"
    suppliers["on_allocation"] = (suppliers.availability_raw + " " + suppliers.related_info).str.contains(pdm.ALLOC_RE)
    suppliers["parsed_by"] = "rule"
    suppliers.to_csv(output / "suppliers.csv", index=False)
    pd.DataFrame(detail_audit).to_csv(output / "detail_parse_audit.csv", index=False)
    mapping = pd.read_csv(ROOT / "data/company_ticker_map.csv", keep_default_na=False)
    # Re-read timestamps with the types required by the exact existing audit.
    suppliers = pd.read_csv(output / "suppliers.csv", dtype={"capture_ts": str})
    ledger, attrition = build_candidates(events, suppliers, mapping, final=True)
    ledger = ledger[ledger.country.eq("US")].copy()
    ledger["winner_count"] = ledger.event_id.map(ledger[ledger.role.eq("winner")].groupby("event_id").ticker.nunique()).fillna(0).astype(int)
    primary = ledger[ledger.winner_count.gt(0)].copy()
    primary.to_csv(output / "primary.csv", index=False)
    strict_candidates = primary[~primary.public_date.isin(gap_dates)].copy()
    audit = audit_winners(strict_candidates, suppliers, mapping)
    strict = audit[audit.all_presentations_available] if not audit.empty else audit
    keys = set(zip(strict.event_id, strict.ticker)) if not strict.empty else set()
    strict_winners = strict_candidates[strict_candidates.role.eq("winner") &
        pd.Series([(e, t) in keys for e, t in zip(strict_candidates.event_id, strict_candidates.ticker)], index=strict_candidates.index)].copy()
    strict_winners.to_csv(output / "strict.csv", index=False)
    audit.to_csv(output / "strict_audit.csv", index=False)
    attrition.to_csv(output / "attrition.csv", index=False)
    report = dict(stage="FDA signal preparation only; no prices or returns loaded",
        oos_list_pages=len(oos_pages), oos_first_list_date=str(oos_pages.snapshot_date.min().date()),
        supplier_pages=len(detail_audit), supplier_rows=len(suppliers),
        primary_events=int(primary[primary.role.eq("winner")].event_id.nunique()),
        primary_positions=int(primary.role.eq("winner").sum()),
        strict_events=int(strict_winners.event_id.nunique()), strict_positions=len(strict_winners),
        strict_by_ticker=strict_winners.groupby("ticker").size().to_dict(),
        strict_gap_exclusion_dates=[str(day) for day in sorted(gap_dates)],
        gap_warning="Primary retains registered date-uncertain events; strict study excludes first observations after >=180-day list gaps.",
        files={str(p): sha256(p) for p in [output / "shortage_events.csv", output / "suppliers.csv",
                    output / "primary.csv", output / "strict.csv", ROOT / "data/company_ticker_map.csv"]})
    (output / "preparation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
