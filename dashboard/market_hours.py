"""US equity market calendar for explaining stale quotes (NYSE full-day holidays; no network).

Only used to decide whether a quote is old *because the market is closed* (weekend or holiday).
Early-close days and unscheduled closures are not modelled; the note always shows the real
timestamp of the stored quote, never an assumed one.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
SESSION_CLOSE = time(16)


def _easter(year):
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year, month, weekday, n):
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year, month, weekday):
    last = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day):
    """Saturday holidays move to Friday, Sunday holidays to Monday."""
    return day - timedelta(days=1) if day.weekday() == 5 else day + timedelta(days=1) if day.weekday() == 6 else day


def holidays(year):
    """{date: name} of NYSE full-day closures in `year`."""
    result = {
        _nth_weekday(year, 1, 0, 3): "Martin Luther King Jr. Day",
        _nth_weekday(year, 2, 0, 3): "Washington's Birthday",
        _easter(year) - timedelta(days=2): "Good Friday",
        _last_weekday(year, 5, 0): "Memorial Day",
        _observed(date(year, 7, 4)): "Independence Day",
        _nth_weekday(year, 9, 0, 1): "Labor Day",
        _nth_weekday(year, 11, 3, 4): "Thanksgiving Day",
        _observed(date(year, 12, 25)): "Christmas Day",
    }
    new_year = date(year, 1, 1)
    if new_year.weekday() != 5:  # NYSE does not close the preceding Friday for a Saturday New Year
        result[_observed(new_year)] = "New Year's Day"
    if year >= 2022:
        result[_observed(date(year, 6, 19))] = "Juneteenth"
    return result


def closure(day):
    """None on a trading day, else 'weekend' or the holiday name."""
    if day.weekday() >= 5:
        return "weekend"
    return holidays(day.year).get(day)


def last_session_close(now):
    """The most recent regular-session close at or before `now` (aware datetime)."""
    local = now.astimezone(NEW_YORK)
    day = local.date()
    if closure(day) is None and local.time() >= SESSION_CLOSE:
        return datetime.combine(day, SESSION_CLOSE, NEW_YORK)
    day -= timedelta(days=1)
    while closure(day) is not None:
        day -= timedelta(days=1)
    return datetime.combine(day, SESSION_CLOSE, NEW_YORK)


def eastern_label(moment):
    """'Fri Oct 2, 4:00 PM ET' from an aware datetime."""
    local = moment.astimezone(NEW_YORK)
    hour = local.hour % 12 or 12
    return f"{local:%a %b} {local.day}, {hour}:{local:%M} {'AM' if local.hour < 12 else 'PM'} ET"


def market_context(now, latest_quote_at):
    """Explain staleness only when the market being closed is the actual reason.

    The note appears when today (New York) is a weekend or holiday AND the newest stored
    quote is at or after the last regular-session close. On a trading day, or when the
    stored data is older than the last close, no note: the normal stale warning stands.
    """
    reason = closure(now.astimezone(NEW_YORK).date())
    last_close = last_session_close(now)
    has_last_close = latest_quote_at is not None and latest_quote_at >= last_close
    note = (f"Markets closed - showing last close ({eastern_label(latest_quote_at)})"
            if reason and has_last_close else None)
    return dict(closed_today=reason is not None, closure=reason, last_session_close=last_close.isoformat(),
                has_last_close=has_last_close, note=note)
