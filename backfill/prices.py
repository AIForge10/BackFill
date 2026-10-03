"""Immutable CSV price caches. Fetching is explicit; loading never uses a network.

Vendor policy (vendor="webull", the default): US stocks/ETFs come from the sponsor's
Webull OpenAPI; yfinance is used only where Webull cannot serve a symbol (indices,
FX, non-US listings, or a recorded Webull failure) and as a per-symbol cross-check.
Every symbol's source and cross-check result is written to the manifest.

Adjusted close is a total-return valuation unit, not a raw execution share price.
Keep raw OHLC/actions alongside it for audits and dollar-volume estimates.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd

import config
from backfill.settings import FX_SYMBOL

COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume", "dividends", "splits"]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def symbol_path(directory, symbol):
    return Path(directory) / (quote(symbol, safe="._-") + ".csv")


def normalize_yahoo(frame, symbol):
    """Normalize explicit auto_adjust=False/actions=True output; no repair guessing."""
    if frame.empty:
        raise ValueError(f"No history returned for {symbol}.")
    frame = frame.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    index = pd.to_datetime(frame.index)
    if index.tz is not None:
        index = index.tz_localize(None)  # preserve local session date, not a UTC shift
    names = {"Open": "open", "High": "high", "Low": "low", "Close": "close",
             "Adj Close": "adj_close", "Volume": "volume", "Dividends": "dividends",
             "Stock Splits": "splits"}
    frame = frame.rename(columns=names)
    if "adj_close" not in frame:
        if symbol.startswith("^") or symbol.endswith("=X"):
            frame["adj_close"] = frame["close"]
        else:
            raise ValueError(f"{symbol}: adjusted close missing; dividend handling is unverified.")
    for name in ["dividends", "splits"]:
        if name not in frame:
            frame[name] = 0.0
    frame["date"] = index.normalize()
    # Yahoo LSE equity/ETF prices use pence; local accounting uses pounds.
    if symbol.endswith(".L"):
        for name in ["open", "high", "low", "close", "adj_close", "dividends"]:
            frame[name] = frame[name] / 100.0
    frame = frame[COLUMNS].sort_values("date").reset_index(drop=True)
    validate_bars(frame, symbol)
    return frame


def validate_bars(frame, symbol):
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"{symbol}: missing columns {sorted(missing)}")
    if frame.empty:
        raise ValueError(f"{symbol}: empty price cache")
    dates = pd.to_datetime(frame.date)
    if dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError(f"{symbol}: duplicate or unsorted session dates")
    for col in ["open", "high", "low", "close", "adj_close"]:
        values = pd.to_numeric(frame[col], errors="coerce")
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError(f"{symbol}: invalid {col}; missing bars must be audited, not filled")
    if not np.isfinite(pd.to_numeric(frame.volume, errors="coerce")).all() or (frame.high < frame.low).any() or (frame.volume < 0).any():
        raise ValueError(f"{symbol}: invalid high/low or volume")


WEBULL_ENV = Path(__file__).resolve().parents[1] / "examples/backtest/.env"
CROSS_CHECK_MIN = dict(date_overlap=0.95, return_correlation=0.95)


def webull_eligible(symbol):
    """Webull's market-data API covers US listings: no exchange suffix, index or FX pair."""
    return not (symbol.startswith("^") or "=" in symbol or "." in symbol)


def webull_client():
    """DataClient from the sponsor kit's gitignored credentials file (never logged)."""
    import os

    from dotenv import load_dotenv
    from webull.core.client import ApiClient
    from webull.data.data_client import DataClient

    load_dotenv(WEBULL_ENV)
    key, secret = os.environ.get("WEBULL_APP_KEY"), os.environ.get("WEBULL_APP_SECRET")
    if not key or not secret:
        raise ValueError(f"Webull credentials missing in {WEBULL_ENV}.")
    region = os.environ.get("WEBULL_REGION_ID", "us")
    api = ApiClient(key, secret, region)
    api.add_endpoint(region, os.environ.get("WEBULL_API_ENDPOINT", "api.webull.com"))
    return DataClient(api)


def fetch_webull(client, symbol, start, end):
    """Daily bars through the sponsor kit's paging feed.

    The SDK serves daily bars only forward-adjusted ("previous weight"); whether that
    includes dividends is not documented, so cross_check() measures it per symbol.
    Raw dividends/splits are not provided and are stored as zero.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from webull_bt.feed import WebullData

    ny = ZoneInfo("America/New_York")
    fromdate = datetime.fromisoformat(start).replace(tzinfo=ny)
    todate = (pd.Timestamp(end) - pd.Timedelta(seconds=1)).to_pydatetime().replace(tzinfo=ny)  # end is exclusive
    bars, errors = [], []
    for category in ("US_STOCK", "US_ETF"):
        feed = WebullData(dataname=symbol, data_client=client, category=category, timespan="D",
                          count=5000, fromdate=fromdate, todate=todate, trading_sessions="RTH")
        feed._data_client = client  # what WebullData.start() does, without a backtrader run
        try:
            feed._start_backtest()
        except Exception as exc:  # wrong category or no permission: try the next, report both
            errors.append(f"{category}: {exc}")
            continue
        while not feed._q.empty():
            bars.append(feed._q.get())
        if bars:
            break
    if not bars:
        raise ValueError(f"Webull returned no daily bars for {symbol} ({'; '.join(errors) or 'empty'})")
    local = [b.datetime.astimezone(ny) for b in bars]
    # A daily bar stamped at UTC midnight reads as the previous New York evening; move it forward.
    dates = [(t + pd.Timedelta(days=1) if t.hour >= 18 else t).date() for t in local]
    frame = pd.DataFrame(dict(date=pd.to_datetime(dates), open=[b.open for b in bars], high=[b.high for b in bars],
                              low=[b.low for b in bars], close=[b.close for b in bars],
                              adj_close=[b.close for b in bars], volume=[b.volume for b in bars],
                              dividends=0.0, splits=0.0))
    frame = frame[(frame.date >= pd.Timestamp(start)) & (frame.date < pd.Timestamp(end))]
    frame = frame.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    validate_bars(frame, symbol)
    return frame[COLUMNS]


def fetch_yahoo(symbol, start, end):
    import yfinance as yf

    raw = yf.download(symbol, start=start, end=end, interval="1d", auto_adjust=False,
                      actions=True, repair=False, keepna=True, progress=False,
                      threads=False, ignore_tz=False)
    return normalize_yahoo(raw, symbol)


def cross_check(primary, reference):
    """Compare a Webull series with Yahoo's adjusted close on shared sessions.

    Date overlap and return correlation catch misaligned or wrong series. The
    annualized return gap measures dividend treatment: a gap near the dividend
    yield means Webull's adjustment omits dividends.
    """
    a = primary.set_index("date").adj_close
    b = reference.set_index("date").adj_close
    common = a.index.intersection(b.index)
    overlap = len(common) / max(len(a), len(b))
    ra, rb = a.loc[common].pct_change().dropna(), b.loc[common].pct_change().dropna()
    years = max((common[-1] - common[0]).days, 1) / 365.25 if len(common) > 1 else np.nan
    gap = float((np.log1p(ra).sum() - np.log1p(rb).sum()) / years) if len(ra) else np.nan
    result = dict(sessions_primary=len(a), sessions_reference=len(b), date_overlap=round(overlap, 4),
                  return_correlation=round(float(ra.corr(rb)), 4) if len(ra) > 2 else None,
                  annualized_log_return_gap=round(gap, 4) if np.isfinite(gap) else None)
    result["ok"] = bool(overlap >= CROSS_CHECK_MIN["date_overlap"] and result["return_correlation"] is not None
                        and result["return_correlation"] >= CROSS_CHECK_MIN["return_correlation"])
    return result


def required_symbols(events):
    countries = sorted(set(events.country.dropna()))
    return sorted(set(events.ticker) | {config.BENCHMARK[c] for c in countries}
                  | {config.MARKET_INDEX[c] for c in countries}
                  | {FX_SYMBOL[c] for c in countries if FX_SYMBOL[c]})


def fetch_cache(events, directory, *, start="2013-01-01", end="2024-10-01", exclusions=None, vendor="webull"):
    """One explicit acquisition stage; existing files are reused only by hash.

    An exclusion is an operator-supplied reason, never an automatic response to
    bad subsequent returns or missing exit prices. Failing downloads abort.
    A Webull series that fails the Yahoo cross-check (missing sessions or
    mismatched daily moves) is replaced by the Yahoo series, with the check
    and reason recorded in the manifest.
    """
    import yfinance as yf

    if vendor not in {"webull", "yfinance"}:
        raise ValueError("vendor must be 'webull' or 'yfinance'.")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    existing = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    exclusions = exclusions or {}
    if existing and (existing["requested_start"] != start or existing["requested_end_exclusive"] != end
                     or existing.get("exclusions", {}) != exclusions
                     or existing.get("vendor_policy", "yfinance") != vendor):
        raise ValueError("Cache request changed. Use a new cache directory; never overwrite a frozen version.")
    old = existing.get("symbols", {}) if existing else {}
    entries, failures = {}, []
    symbols = required_symbols(events)
    infrastructure = set(events.benchmark) | set(config.MARKET_INDEX.values()) | set(FX_SYMBOL.values())
    client, client_error = None, None
    if vendor == "webull" and any(webull_eligible(s) for s in symbols):
        try:
            client = webull_client()
        except Exception as exc:  # recorded per symbol below; yfinance fallback is explicit
            client_error = f"Webull client unavailable: {exc}"
    unknown = set(exclusions) - set(events.ticker)
    if unknown or set(exclusions) & infrastructure:
        raise ValueError("Only identified stock candidates can be explicitly excluded.")
    for symbol in symbols:
        if symbol in exclusions:
            continue
        path = symbol_path(directory, symbol)
        if symbol in old and path.exists():
            if sha256(path) != old[symbol]["sha256"]:
                raise ValueError(f"{symbol}: frozen file hash changed")
            entries[symbol] = old[symbol]
            continue
        if path.exists():
            raise ValueError(f"Unmanifested cache file {path}; move it to a separately reviewed version.")
        try:
            source, fallback_reason, check = "yfinance", None, None
            if vendor == "webull" and webull_eligible(symbol):
                try:
                    if client is None:
                        raise ValueError(client_error)
                    bars, source = fetch_webull(client, symbol, start, end), "webull"
                except Exception as exc:
                    fallback_reason = str(exc)[:300]
            if source == "webull":
                reference = None
                try:
                    reference = fetch_yahoo(symbol, start, end)
                    check = cross_check(bars, reference)
                except Exception as exc:
                    check = dict(ok=None, note=f"no Yahoo reference: {str(exc)[:200]}")
                if check.get("ok") is False:
                    # A Webull series with missing sessions or mismatched moves is replaced by the
                    # reference, and the reason is recorded; it is never silently used or dropped.
                    bars, source = reference, "yfinance"
                    fallback_reason = f"Webull series failed cross-check: {check}"
            else:
                bars = fetch_yahoo(symbol, start, end)
            dates = pd.to_datetime(bars.date)
            if (dates < pd.Timestamp(start)).any() or (dates >= pd.Timestamp(end)).any():
                raise ValueError("Vendor returned data outside the requested period.")
            bars.to_csv(path, index=False, date_format="%Y-%m-%d")
            entries[symbol] = dict(file=path.name, sha256=sha256(path), rows=len(bars), vendor=source,
                                   fallback_reason=fallback_reason, cross_check=check,
                                   actual_start=str(dates.min().date()), actual_end=str(dates.max().date()),
                                   retrieved_at=datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            failures.append(dict(symbol=symbol, error=str(exc)))
    from importlib.metadata import PackageNotFoundError, version

    try:
        webull_version = version("webull-openapi-python-sdk")
    except PackageNotFoundError:
        webull_version = None
    manifest = dict(schema_version=2, vendor_policy=vendor,
                    vendor=("Webull OpenAPI for US listings; yfinance/Yahoo for the rest and as a recorded fallback"
                            if vendor == "webull" else "yfinance/Yahoo"),
                    vendor_versions=dict(yfinance=yf.__version__, webull_sdk=webull_version),
                    requested_start=start, requested_end_exclusive=end,
                    adjustments=dict(yahoo=dict(auto_adjust=False, actions=True, repair=False,
                                                lse_price_unit="GBP converted from GBp",
                                                valuation="adj_close total-return units"),
                                     webull=dict(daily_bars="forward-adjusted ('previous weight' per SDK)",
                                                 valuation="close used as adj_close",
                                                 dividends="inclusion measured by cross_check annualized_log_return_gap",
                                                 actions="not provided; stored as zero")),
                    cross_check_thresholds=CROSS_CHECK_MIN,
                    symbols=entries, exclusions=exclusions, failures=failures)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    if failures:
        raise ValueError("Downloads incomplete; see manifest failures. No backtest is permitted.")
    return manifest


def load_cache(directory, symbols, *, evaluation_end):
    """Return symbol-indexed frames and manifest, verifying every byte first."""
    directory = Path(directory)
    path = directory / "manifest.json"
    if not path.exists():
        raise ValueError("Price manifest missing. Run 06_prices.py explicitly first.")
    manifest = json.loads(path.read_text())
    if manifest.get("failures"):
        raise ValueError("Price acquisition has unresolved failures; backtest stopped.")
    # Prevent even loading the holdout into an ordinary in-sample process.
    expected_end = pd.Timestamp(evaluation_end) + pd.Timedelta(days=1)
    if pd.Timestamp(manifest["requested_end_exclusive"]) != expected_end:
        raise ValueError("Cache request must end exactly after this evaluation period; short/OOS caches are refused.")
    result = {}
    for symbol in symbols:
        if symbol in manifest.get("exclusions", {}):
            continue
        meta = manifest["symbols"].get(symbol)
        if not meta:
            raise ValueError(f"{symbol}: cache miss. Offline runs never fetch a replacement.")
        path = symbol_path(directory, symbol)
        if path.name != meta["file"] or not path.exists() or sha256(path) != meta["sha256"]:
            raise ValueError(f"{symbol}: missing or changed cache file")
        frame = pd.read_csv(path, parse_dates=["date"])
        validate_bars(frame, symbol)
        if (frame.date > pd.Timestamp(evaluation_end)).any():
            raise ValueError(f"{symbol}: out-of-period bars")
        result[symbol] = frame.set_index("date")
    return result, manifest
