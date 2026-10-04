"""Recent Webull daily closes for the four US injectable specialists, cached on the server.

/api/prices/specialists -> AMPH, AMRX, ANIP, ICUI, the last ~30 sessions, each indexed to 100.

Uses the research pipeline's Webull client (keys from the server .env, never sent to the
browser). One fetch per hour at most; a failure is cached for 5 minutes so an outage is not
retried on every page view. Never raises: on any problem it returns state "unavailable" and the
page hides the chart. Display only; nothing here feeds the research or the backtest.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timedelta, timezone

TICKERS = ("AMPH", "AMRX", "ANIP", "ICUI")  # US-listed specialists flagged in the pre-registered v3 basket
CACHE_SECONDS = 3600
FAILURE_SECONDS = 300
LOOKBACK_DAYS = 45      # calendar days, about 30 sessions
TIMEOUT_SECONDS = 25


def _default_fetch(tickers, start, end):
    """{ticker: [(date, close), ...]} via the existing Webull helpers; skips tickers that fail."""
    from backfill.prices import fetch_webull, webull_client
    client = webull_client()
    result = {}
    for ticker in tickers:
        try:
            frame = fetch_webull(client, ticker, start, end)
            result[ticker] = [(d.date().isoformat(), float(c)) for d, c in zip(frame["date"], frame["close"])]
        except Exception:
            continue  # one bad symbol must not hide the others
    return result


def to_series(raw):
    """Index each ticker's closes to 100 at its first session."""
    series = []
    for ticker in TICKERS:
        points = [(d, c) for d, c in raw.get(ticker, []) if c and c > 0]
        if len(points) < 2:
            continue
        base = points[0][1]
        series.append(dict(ticker=ticker, points=[dict(date=d, close=round(c, 4), index=round(c / base * 100, 3))
                                                  for d, c in points],
                           change=round(points[-1][1] / base - 1, 5), last_close=round(points[-1][1], 4),
                           last_date=points[-1][0]))
    return series


class SpecialistPrices:
    def __init__(self, fetch=None, clock=time.monotonic, today=None):
        self.fetch = fetch or _default_fetch
        self.clock = clock
        self.today = today or (lambda: datetime.now(timezone.utc).date())
        self._cached = None  # (time, ttl, result)
        self._lock = threading.Lock()

    def snapshot(self):
        with self._lock:
            now = self.clock()
            if self._cached and now - self._cached[0] < self._cached[1]:
                return dict(self._cached[2], cached=True)
            result = self._load()
            ttl = CACHE_SECONDS if result["state"] == "ok" else FAILURE_SECONDS
            self._cached = (now, ttl, result)
            return dict(result, cached=False)

    def _load(self):
        today = self.today()
        start, end = (today - timedelta(days=LOOKBACK_DAYS)).isoformat(), (today + timedelta(days=1)).isoformat()
        base = dict(source="Webull daily closes", tickers=list(TICKERS), series=[], missing=list(TICKERS),
                    fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            raw = executor.submit(self.fetch, TICKERS, start, end).result(timeout=TIMEOUT_SECONDS)
        except FutureTimeout:
            return dict(base, state="unavailable", message="Webull did not answer in time.")
        except Exception:
            # Client errors can mention credentials or endpoints: never pass them on.
            return dict(base, state="unavailable", message="Webull prices are unavailable right now.")
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        series = to_series(raw or {})
        if not series:
            return dict(base, state="unavailable", message="Webull returned no recent prices.")
        got = {s["ticker"] for s in series}
        return dict(base, state="ok", series=series, missing=[t for t in TICKERS if t not in got],
                    message="Display only: recent daily closes, indexed to 100 at the first session shown.")
