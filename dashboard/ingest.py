"""Explicit operator-only ingestion of vendor/FDA observations into Tiger Data."""
import argparse
import csv
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Observation timestamps must include a timezone")
    if parsed > datetime.now(timezone.utc):
        raise ValueError("Observation timestamps cannot be in the future")
    return parsed


def positive(value, optional=False):
    if not value and optional:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid numeric price") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError("Prices must be positive finite numbers")
    return parsed


def validate(kind, row):
    source = row.get("source", "").strip()
    if not source:
        raise ValueError("A vendor/source identifier is required")
    ticker = row.get("ticker", "").strip().upper()
    if ticker and not re.fullmatch(r"[A-Z0-9.^=:-]{1,32}", ticker):
        raise ValueError("Invalid ticker")
    if kind == "quotes":
        if not ticker:
            raise ValueError("Quotes require a ticker")
        volume = int(row["volume"]) if row.get("volume") else None
        if volume is not None and volume < 0:
            raise ValueError("Volume must be nonnegative")
        return (timestamp(row["time"]), ticker, positive(row["price"]),
                positive(row.get("previous_close", ""), optional=True), volume, source)
    availability = row.get("availability", "")
    if availability not in {"available", "allocation", "disrupted", "unknown"}:
        raise ValueError("Unknown availability class")
    for field in ("event_key", "product", "company"):
        if not row.get(field, "").strip():
            raise ValueError(f"Supplier updates require {field}")
    url = row.get("source_url", "")
    if not url or urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).hostname:
        raise ValueError("Supplier updates require a public source URL")
    return (timestamp(row["observed_at"]), row["event_key"], row["product"], row["company"],
            ticker or None, availability, source, url)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("quotes", "supplier_updates"), required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not connect or write")
    args = parser.parse_args()
    with args.file.open(newline="", encoding="utf-8") as stream:
        records = [validate(args.kind, row) for row in csv.DictReader(stream)]
    if not records:
        raise ValueError("No observations supplied")
    if args.dry_run:
        print(f"Validated {len(records)} observations; no database connection or write.")
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    except ImportError:
        pass
    dsn = os.environ.get("TIGER_INGEST_DATABASE_URL")
    if not dsn:
        raise ValueError("Set TIGER_INGEST_DATABASE_URL for the explicit writer; the reader URL is not reused")
    import psycopg
    statements = {
        "quotes": """INSERT INTO backfill_live.quotes
            (time,ticker,price,previous_close,volume,source) VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (time,ticker,source) DO NOTHING""",
        "supplier_updates": """INSERT INTO backfill_live.supplier_updates
            (observed_at,event_key,product,company,ticker,availability,source,source_url)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (observed_at,event_key,company) DO NOTHING""",
    }
    try:
        with psycopg.connect(dsn, connect_timeout=5, sslmode=os.environ.get("TIGER_SSLMODE", "require")) as conn:
            with conn.cursor() as cursor:
                cursor.executemany(statements[args.kind], records)
                inserted = cursor.rowcount
    except Exception:
        raise SystemExit("Tiger Data ingestion failed. Check connection settings and schema; credentials are not logged.") from None
    print(f"Accepted {len(records)} observations; inserted {inserted}; duplicates kept unchanged.")


if __name__ == "__main__":
    main()
