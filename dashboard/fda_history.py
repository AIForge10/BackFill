"""FDA Time Machine: point-in-time FDA shortage pages from Tiger Data (read-only).

/api/fda/asof?date=YYYY-MM-DD  each drug's latest archived snapshot on or before that date (UTC),
                               with that snapshot's timestamp, status and manufacturers
/api/fda/timeline?drug=...     one drug's status changes across its archived snapshots

Loaded by scripts/load_tiger.py. Never raises for database problems: returns a state and a
message (not_configured, driver_missing, schema_missing, error) without driver details.
"""
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone

CACHE_SECONDS = 60
CACHE_ENTRIES = 64
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

RANGE_SQL = """SELECT min(snapshot_ts) AS first, max(snapshot_ts) AS last, count(DISTINCT drug) AS drugs
               FROM backfill_live.fda_snapshots"""
ASOF_SQL = """
    SELECT s.drug, s.snapshot_ts, s.manufacturer, s.status, s.source_url
    FROM backfill_live.fda_snapshots s
    JOIN (SELECT drug, max(snapshot_ts) AS snapshot_ts
          FROM backfill_live.fda_snapshots WHERE snapshot_ts < %s GROUP BY drug) latest
      USING (drug, snapshot_ts)
    ORDER BY s.drug, s.manufacturer"""
TIMELINE_SQL = """
    SELECT snapshot_ts, status, count(*) AS manufacturers, max(source_url) AS source_url
    FROM backfill_live.fda_snapshots WHERE drug = %s
    GROUP BY snapshot_ts, status ORDER BY snapshot_ts"""


def parse_date(value):
    if not value or not DATE.fullmatch(value):
        raise ValueError("date must be YYYY-MM-DD")
    parsed = date.fromisoformat(value)
    if not date(2000, 1, 1) <= parsed <= date(2100, 1, 1):
        raise ValueError("date out of range")
    return parsed


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def group_asof(rows):
    """Rows (one per manufacturer) -> one record per drug, newest snapshot first."""
    drugs = {}
    for r in rows:
        item = drugs.setdefault(r["drug"], dict(drug=r["drug"], snapshot_ts=_iso(r["snapshot_ts"]),
                                                status=r["status"], source_url=r["source_url"], manufacturers=[]))
        item["manufacturers"].append(r["manufacturer"])
    return sorted(drugs.values(), key=lambda d: (d["snapshot_ts"], d["drug"]), reverse=True)


def status_changes(rows):
    """Status changes per UTC day. FDA can list one drug on several tabs at once (e.g. shortage and
    discontinued presentations) and the archive captures each tab separately, so same-day captures
    are merged ("Currently in Shortage + Discontinuation") instead of flip-flopping."""
    days = {}
    for r in rows:
        day = _iso(r["snapshot_ts"])[:10]
        item = days.setdefault(day, dict(snapshot_ts=_iso(r["snapshot_ts"]), statuses=set(), manufacturers=0,
                                         source_url=r["source_url"]))
        item["statuses"].add(r["status"])
        item["manufacturers"] = max(item["manufacturers"], r["manufacturers"])
    changes, previous = [], None
    for day in sorted(days):
        item = days[day]
        status = " + ".join(sorted(item.pop("statuses")))
        if status != previous:
            changes.append(dict(item, status=status, from_status=previous))
            previous = status
    return changes


class FdaHistory:
    def __init__(self, environ=os.environ, clock=time.monotonic, connect=None):
        self.environ = environ
        self.clock = clock
        self._connect = connect
        self._cache = {}
        self._lock = threading.Lock()

    def asof(self, value):
        day = parse_date(value)
        return self._cached(("asof", day), lambda: self._asof(day))

    def timeline(self, drug):
        drug = (drug or "").strip()
        if not drug or len(drug) > 300:
            raise ValueError("drug is required")
        return self._cached(("timeline", drug), lambda: self._timeline(drug))

    # ---- internals ----

    def _cached(self, key, compute):
        with self._lock:
            now = self.clock()
            hit = self._cache.get(key)
            if hit and now - hit[0] < CACHE_SECONDS:
                return hit[1]
        result = compute()
        if result.get("state") == "connected":  # never cache an outage
            with self._lock:
                if len(self._cache) >= CACHE_ENTRIES:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[key] = (self.clock(), result)
        return result

    def _query(self, statements):
        """Run (sql, params) pairs on one read-only session; returns (state, message, results)."""
        dsn = self.environ.get("TIGER_DATABASE_URL", "")
        if not dsn:
            return "not_configured", "Tiger Data is not configured on the server.", None
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            return "driver_missing", "Install the dashboard extra (psycopg) to read Tiger Data.", None
        connect = self._connect or psycopg.connect
        try:
            with connect(dsn, connect_timeout=5, row_factory=dict_row,
                         sslmode=self.environ.get("TIGER_SSLMODE", "require")) as conn:
                conn.read_only = True
                conn.execute("SET LOCAL statement_timeout = '8000ms'")
                return "connected", None, [conn.execute(sql, params).fetchall() for sql, params in statements]
        except getattr(psycopg.errors, "UndefinedTable", ()):
            return "schema_missing", "The FDA snapshot table is missing. Run scripts/load_tiger.py.", None
        except Exception:
            # Driver messages can contain connection strings: never return them.
            return "error", "Tiger Data is unreachable right now. Try again shortly.", None

    def _asof(self, day):
        end = datetime.combine(day + timedelta(days=1), datetime.min.time(), timezone.utc)
        state, message, results = self._query([(RANGE_SQL, None), (ASOF_SQL, (end,))])
        base = dict(date=day.isoformat(), state=state, message=message, drugs=[], counts={}, range=None,
                    latest_snapshot_ts=None, before_first_snapshot=False)
        if state != "connected":
            return base
        span, rows = results[0][0] if results[0] else {}, results[1]
        drugs = group_asof(rows)
        counts = {}
        for d in drugs:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        first = span.get("first")
        return dict(base, drugs=drugs, counts=counts,
                    range=dict(first=_iso(first), last=_iso(span.get("last")), drugs=span.get("drugs")),
                    latest_snapshot_ts=drugs[0]["snapshot_ts"] if drugs else None,
                    before_first_snapshot=bool(first and end <= first),
                    message=f"{len(drugs)} drugs; each row is that drug's latest archived FDA page on or before "
                            f"{day.isoformat()} (UTC).")

    def _timeline(self, drug):
        state, message, results = self._query([(TIMELINE_SQL, (drug,))])
        base = dict(drug=drug, state=state, message=message, changes=[], snapshots=0, first=None, last=None)
        if state != "connected":
            return base
        rows = results[0]
        if not rows:
            return dict(base, message="No archived snapshots for this drug.")
        return dict(base, changes=status_changes(rows), snapshots=len({_iso(r["snapshot_ts"]) for r in rows}),
                    first=_iso(rows[0]["snapshot_ts"]), last=_iso(rows[-1]["snapshot_ts"]))
