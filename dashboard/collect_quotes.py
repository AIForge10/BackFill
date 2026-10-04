"""Write recent Webull daily closes as the quote CSV that dashboard.ingest expects.

    uv run python -m dashboard.collect_quotes --out quotes.csv            # FMS, ICUI, SPY; last 14 days
    uv run python -m dashboard.ingest --kind quotes --file quotes.csv --dry-run

Reuses backfill.prices (the research pipeline's Webull client and daily-bar fetch); credentials
come from the gitignored .env files it already reads. Each row is one session's official close,
stamped at 16:00 New York time, with the prior session's close. Nothing is written to a database.
"""
import argparse
import csv
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backfill.prices import fetch_webull, webull_client

NEW_YORK = ZoneInfo("America/New_York")
TICKERS = ("FMS", "ICUI", "SPY")
SOURCE = "webull_daily_close"
COLUMNS = ("time", "ticker", "price", "previous_close", "volume", "source")


def quote_rows(ticker, bars, today):
    """One row per completed session; previous_close is the prior bar in the same series."""
    rows, previous = [], None
    for bar in bars.itertuples():
        closed_at = datetime.combine(bar.date.date(), time(16), NEW_YORK)
        if bar.date.date() < today or datetime.now(NEW_YORK) >= closed_at:  # never a future timestamp
            rows.append(dict(time=closed_at.isoformat(), ticker=ticker, price=f"{bar.close:.4f}",
                             previous_close="" if previous is None else f"{previous:.4f}",
                             volume=int(bar.volume), source=SOURCE))
        previous = bar.close
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tickers", default=",".join(TICKERS))
    ap.add_argument("--days", type=int, default=14, help="calendar days back (the panel shows the last 7)")
    args = ap.parse_args()
    today = datetime.now(NEW_YORK).date()
    start, end = (today - timedelta(days=args.days)).isoformat(), (today + timedelta(days=1)).isoformat()
    client = webull_client()
    rows = []
    for ticker in args.tickers.split(","):
        found = quote_rows(ticker, fetch_webull(client, ticker, start, end), today)
        rows += found
        print(f"{ticker}: {len(found)} sessions, latest {found[-1]['time'][:10] if found else 'none'}")
    with args.out.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
