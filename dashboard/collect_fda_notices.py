"""Write archived FDA shortage notices as the supplier_updates CSV that dashboard.ingest expects.

    uv run python -m dashboard.collect_fda_notices --out notices.csv
    uv run python -m dashboard.ingest --kind supplier_updates --file notices.csv --dry-run

Reads parsed Wayback captures of FDA drug-shortage detail pages (default
results/forward_oct2024/suppliers.csv) and keeps the newest snapshot of each drug captured in
the last --days days before the newest capture. Each row is one supplier on that snapshot:
drug, page status, supplier, availability, the snapshot time (observed_at) and the exact
Wayback URL from data/processed/index_detail.csv. These are point-in-time archive records,
not live signals. Nothing is written to a database; research files are only read.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dashboard.archive import archive_index, wayback_url

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "results/forward_oct2024/suppliers.csv"
ARCHIVE_INDEX = ROOT / "data/processed/index_detail.csv"
SOURCE = "fda_archive"
COLUMNS = ("observed_at", "event_key", "product", "company", "ticker", "availability", "source", "source_url", "status")


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def snapshot_time(capture_ts):
    """Wayback timestamps are UTC: 20260923054500 -> 2026-09-23T05:45:00+00:00."""
    return datetime.strptime(capture_ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def product_name(page_product):
    return page_product.replace("| Back to Previous Screen", "").strip(" |")


def company_availability(rows):
    """Collapse a supplier's presentations into the schema's four classes."""
    if any(r.get("on_allocation") == "True" for r in rows):
        return "allocation"
    values = {r.get("availability") for r in rows}
    if values == {"available"}:
        return "available"
    if values <= {"unknown", "", None}:
        return "unknown"
    return "disrupted"  # disrupted or discontinued presentations


def notices(supplier_rows, archive, days=30):
    """supplier_updates rows for the newest snapshot of each drug in the window; also returns skips."""
    newest = max(r["capture_ts"] for r in supplier_rows)
    cutoff = (snapshot_time(newest) - timedelta(days=days)).strftime("%Y%m%d%H%M%S")
    latest = {}
    for row in supplier_rows:
        if row["capture_ts"] >= cutoff and row["capture_ts"] >= latest.get(row["ai_key"], ""):
            latest[row["ai_key"]] = row["capture_ts"]
    grouped = {}
    for row in supplier_rows:
        if latest.get(row["ai_key"]) == row["capture_ts"] and row.get("company"):
            grouped.setdefault((row["capture_ts"], row["ai_key"], row["company"]), []).append(row)
    output, skipped = [], 0
    for (capture_ts, ai_key, company), rows in sorted(grouped.items()):
        url = wayback_url(archive, capture_ts, ai_key)
        if not url:
            skipped += 1  # ingest requires a public source URL; never invent one
            continue
        first = rows[0]
        output.append(dict(observed_at=snapshot_time(capture_ts).isoformat(), event_key=ai_key,
                           product=product_name(first["page_product"]), company=company, ticker="",
                           availability=company_availability(rows), source=SOURCE,
                           source_url=url,
                           status=first.get("page_status", "").strip()))
    return output, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="parsed detail-page captures")
    ap.add_argument("--days", type=int, default=30, help="window before the newest capture")
    args = ap.parse_args()
    archive = archive_index(read_csv(ARCHIVE_INDEX))
    rows, skipped = notices(read_csv(args.source), archive, args.days)
    with args.out.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    drugs = {(r["observed_at"], r["event_key"]) for r in rows}
    print(f"Wrote {len(rows)} supplier rows for {len(drugs)} archived drug notices to {args.out}"
          + (f" ({skipped} skipped: no archive URL)" if skipped else ""))
    if rows:
        print(f"Snapshots from {min(r['observed_at'] for r in rows)[:10]} to {max(r['observed_at'] for r in rows)[:10]}")


if __name__ == "__main__":
    main()
