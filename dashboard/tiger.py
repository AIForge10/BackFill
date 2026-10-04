"""Bounded, read-only SQL queries. Tiger Data stores updates; vendors supply them."""
import os
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal


def serialized(row):
    return {key: value.isoformat() if isinstance(value, datetime) else
            float(value) if isinstance(value, Decimal) else value for key, value in row.items()}


class TigerMonitor:
    def __init__(self):
        self._lock = threading.Lock()
        self._checked = 0
        self._snapshot = None
        self._history_cache = {}

    def snapshot(self, force=False):
        with self._lock:
            if not force and self._snapshot and time.monotonic() - self._checked < 10:
                return self._snapshot
            self._snapshot = self._read()
            self._checked = time.monotonic()
            return self._snapshot

    def history(self, ticker="ICUI"):
        if ticker not in {"FMS", "ICUI", "SPY"}:
            raise ValueError("Unknown history instrument")
        with self._lock:
            cached = self._history_cache.get(ticker)
            if cached and time.monotonic() - cached[0] < 10:
                return cached[1]
            result = self._read_history(ticker)
            self._history_cache[ticker] = (time.monotonic(), result)
            return result

    def _read_history(self, ticker):
        now = datetime.now(timezone.utc)
        base = dict(ticker=ticker, checked_at=now.isoformat(), source=None, points=[],
                    truncated=False, latest_observation_at=None, stale=True)
        dsn = os.environ.get("TIGER_DATABASE_URL", "")
        if not dsn:
            return dict(base, state="not_configured", message="Connect Tiger Data and ingest real vendor quotes to enable this chart.")
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            return dict(base, state="driver_missing", message="Install the dashboard extra to read stored history.")
        try:
            with psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row,
                                 sslmode=os.environ.get("TIGER_SSLMODE", "require")) as conn:
                conn.read_only = True
                conn.execute("SET LOCAL statement_timeout = '4000ms'")
                source = conn.execute("""
                    SELECT source FROM backfill_live.quotes
                    WHERE ticker = %s AND time <= now() AND time > now() - interval '7 days'
                    ORDER BY time DESC, received_at DESC LIMIT 1
                """, (ticker,)).fetchone()
                if not source:
                    return dict(base, state="empty", message="No stored quotes for this instrument in the last seven days.")
                result = conn.execute("""
                    SELECT DISTINCT ON (time) time, received_at, price, source
                    FROM backfill_live.quotes
                    WHERE ticker = %s AND source = %s AND time <= now()
                      AND time > now() - interval '7 days'
                    ORDER BY time DESC, received_at DESC LIMIT 2001
                """, (ticker, source["source"])).fetchall()
            latest = result[0]["time"] if result else None
            return dict(base, state="connected" if result else "empty", source=source["source"],
                        points=[serialized(r) for r in reversed(result[:2000])],
                        truncated=len(result) > 2000,
                        latest_observation_at=latest.isoformat() if latest else None,
                        stale=not latest or (now - latest).total_seconds() > 300,
                        message="Actual stored quotes; one vendor per series.")
        except psycopg.errors.UndefinedTable:
            return dict(base, state="schema_missing", message="The documented live quote table is missing.")
        except Exception:
            return dict(base, state="error", message="Stored market history is unavailable. Check the server connection.")

    def _read(self):
        now = datetime.now(timezone.utc)
        base = dict(checked_at=now.isoformat(), provider="Tiger Data", quotes=[], events=[],
                    refresh_seconds=15, latest_received_at=None)
        dsn = os.environ.get("TIGER_DATABASE_URL", "")
        if not dsn:
            return dict(base, state="not_configured", message="Tiger Data connection has not been configured.")
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            return dict(base, state="driver_missing", message="Install the dashboard extra to enable Tiger Data.")
        try:
            with psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row,
                                 sslmode=os.environ.get("TIGER_SSLMODE", "require")) as conn:
                conn.read_only = True
                conn.execute("SET LOCAL statement_timeout = '4000ms'")
                quotes = conn.execute("""
                    SELECT DISTINCT ON (ticker) time, received_at, ticker, price, previous_close, volume, source
                    FROM backfill_live.quotes WHERE time <= now() AND time > now() - interval '7 days'
                    ORDER BY ticker, time DESC, received_at DESC LIMIT 50
                """).fetchall()
                events = conn.execute("""
                    SELECT observed_at, received_at, event_key, product, company, ticker,
                           availability, source, source_url
                    FROM backfill_live.supplier_updates WHERE observed_at <= now()
                    ORDER BY observed_at DESC LIMIT 25
                """).fetchall()
            all_rows = quotes + events
            latest = max((r["received_at"] for r in all_rows), default=None)
            age = (now - latest).total_seconds() if latest else None
            for row in quotes:
                row["age_seconds"] = max(0, (now - row["time"]).total_seconds())
                row["stale"] = row["age_seconds"] > 300
            return dict(base, state="connected" if all_rows else "empty",
                        message="Read-only connection established." if all_rows else "Connected; no observations are available.",
                        quotes=[serialized(r) for r in quotes], events=[serialized(r) for r in events],
                        latest_received_at=latest.isoformat() if latest else None, ingest_age_seconds=age)
        except psycopg.errors.UndefinedTable:
            return dict(base, state="schema_missing", message="Connected; the documented backfill_live tables are missing.")
        except Exception:
            # Driver exceptions can contain credentials/DSNs: never send them to the browser.
            return dict(base, state="error", message="Tiger Data is unavailable. Check the server connection settings.")
