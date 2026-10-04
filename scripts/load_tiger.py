"""Load point-in-time FDA shortage snapshots into Tiger Data (TimescaleDB) for the FDA Time Machine.

    uv run --extra dashboard python scripts/load_tiger.py              # create, hypertable, bulk load
    uv run --extra dashboard python scripts/load_tiger.py --dry-run    # build rows only, no database

Creates backfill_live.fda_snapshots(snapshot_ts, drug, manufacturer, status, source_url), makes it a
hypertable on snapshot_ts, and bulk-loads one row per (archived detail-page capture, drug,
manufacturer) from results/forward_oct2024/suppliers.csv. status is the FDA page status at that
capture. drug is one canonical name per FDA drug key (its most recent display name), so renamed
pages keep one history. source_url is the exact Wayback page (matched on time and drug).
Re-running is safe: existing rows are kept (ON CONFLICT DO NOTHING).

Connection: TIGER_INGEST_DATABASE_URL if set (the writer), else TIGER_DATABASE_URL, from the
repo-root .env. Nothing about the connection is printed.
"""
import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard.archive import archive_index, wayback_url  # noqa: E402

SOURCE = ROOT / "results/forward_oct2024/suppliers.csv"
ARCHIVE_INDEX = ROOT / "data/processed/index_detail.csv"
DDL = """
CREATE SCHEMA IF NOT EXISTS backfill_live;
CREATE TABLE IF NOT EXISTS backfill_live.fda_snapshots (
    snapshot_ts timestamptz NOT NULL,
    drug text NOT NULL,
    manufacturer text NOT NULL,
    status text NOT NULL,
    source_url text,
    PRIMARY KEY (snapshot_ts, drug, manufacturer)
);
CREATE INDEX IF NOT EXISTS fda_snapshots_drug_time ON backfill_live.fda_snapshots (drug, snapshot_ts DESC);
"""
HYPERTABLE = "SELECT create_hypertable('backfill_live.fda_snapshots', by_range('snapshot_ts'), if_not_exists => TRUE)"


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def display_name(page_product):
    return page_product.replace("| Back to Previous Screen", "").strip(" |")


def snapshot_time(capture_ts):
    """Wayback timestamps are UTC: 20260923054500 -> 2026-09-23 05:45:00+00:00."""
    return datetime.strptime(capture_ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def build_rows(supplier_rows, archive):
    """One row per (capture, drug, manufacturer); canonical drug name per FDA drug key."""
    latest_name = {}
    for row in supplier_rows:
        key = row["ai_key"]
        if row["capture_ts"] >= latest_name.get(key, ("", ""))[0]:
            latest_name[key] = (row["capture_ts"], display_name(row["page_product"]))
    seen, rows = set(), []
    for row in supplier_rows:
        company = (row.get("company") or "").strip()
        identity = (row["capture_ts"], row["ai_key"], company)
        if not company or identity in seen:
            continue
        seen.add(identity)
        rows.append((snapshot_time(row["capture_ts"]), latest_name[row["ai_key"]][1], company,
                     row["page_status"].strip(), wayback_url(archive, row["capture_ts"], row["ai_key"])))
    return rows


def connect():
    import psycopg
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    dsn = os.environ.get("TIGER_INGEST_DATABASE_URL") or os.environ.get("TIGER_DATABASE_URL")
    if not dsn:
        raise SystemExit("Set TIGER_DATABASE_URL (or TIGER_INGEST_DATABASE_URL) in the repo-root .env.")
    return psycopg.connect(dsn, connect_timeout=10, sslmode=os.environ.get("TIGER_SSLMODE", "require"))


def load(conn, rows):
    """Create the hypertable and bulk-load via COPY into a temp table, then insert new rows."""
    conn.execute(DDL)
    conn.execute(HYPERTABLE)
    conn.execute("CREATE TEMP TABLE fda_load (LIKE backfill_live.fda_snapshots) ON COMMIT DROP")
    with conn.cursor() as cursor:
        with cursor.copy("COPY fda_load (snapshot_ts, drug, manufacturer, status, source_url) FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)
        cursor.execute("INSERT INTO backfill_live.fda_snapshots SELECT * FROM fda_load ON CONFLICT DO NOTHING")
        inserted = cursor.rowcount
    total = conn.execute("SELECT count(*), count(DISTINCT drug), min(snapshot_ts), max(snapshot_ts) "
                         "FROM backfill_live.fda_snapshots").fetchone()
    conn.commit()
    return inserted, total


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", type=Path, default=SOURCE)
    ap.add_argument("--dry-run", action="store_true", help="build rows only; no database connection")
    args = ap.parse_args()
    rows = build_rows(read_csv(args.source), archive_index(read_csv(ARCHIVE_INDEX)))
    drugs = {r[1] for r in rows}
    linked = sum(1 for r in rows if r[4])
    print(f"Built {len(rows)} rows: {len(drugs)} drugs, {len({r[0] for r in rows})} snapshots, "
          f"{min(r[0] for r in rows):%Y-%m-%d} to {max(r[0] for r in rows):%Y-%m-%d}, {linked} with archive links")
    if args.dry_run:
        return
    try:
        with connect() as conn:
            inserted, (count, drug_count, first, last) = load(conn, rows)
    except SystemExit:
        raise
    except Exception as exc:
        raise SystemExit(f"Tiger load failed ({type(exc).__name__}); connection details are not printed.") from None
    print(f"Inserted {inserted} new rows. fda_snapshots now holds {count} rows, {drug_count} drugs, "
          f"{first:%Y-%m-%d} to {last:%Y-%m-%d}.")


if __name__ == "__main__":
    main()
