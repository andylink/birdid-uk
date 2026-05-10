"""
dashboard/utils.py — shared helpers used across dashboard routes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def _local_tz() -> ZoneInfo:
    from dashboard.config import LOCAL_TZ
    return LOCAL_TZ


def _local_today() -> date:
    """Today's date in the configured local timezone."""
    return datetime.now(_local_tz()).date()


def _day_utc_bounds(d: date, tz: ZoneInfo) -> tuple[str, str]:
    """Return (start_utc, end_utc) as naive ISO strings for a local calendar day.

    The bounds are the UTC equivalents of midnight-to-midnight in the given
    local timezone, so that filtering ``timestamp >= start AND timestamp < end``
    selects exactly the detections that occurred during that local calendar day.
    """
    start_local = datetime(d.year, d.month, d.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc.isoformat(sep=" "), end_utc.isoformat(sep=" ")


def utc_offset_str() -> str:
    """SQLite datetime() modifier string for the configured timezone's current UTC offset.

    Examples: ``'+1 hours'`` during BST, ``'+0 hours'`` during GMT.
    For non-integer-hour offsets (e.g. India +5:30) the minutes are included.
    Used to shift stored UTC timestamps into local time inside SQL queries, e.g.::

        DATE(datetime(timestamp, '+1 hours'))
        strftime('%H', datetime(timestamp, '+1 hours'))
    """
    tz = _local_tz()
    offset_secs = int(datetime.now(tz).utcoffset().total_seconds())
    hours, rem = divmod(abs(offset_secs), 3600)
    mins = rem // 60
    sign = "+" if offset_secs >= 0 else "-"
    if mins:
        return f"'{sign}{hours} hours {mins} minutes'"
    return f"'{sign}{hours} hours'"


def to_utc_iso(ts: str | None) -> str | None:
    """Normalise a raw SQLite UTC timestamp string to ISO 8601 with ``+00:00`` suffix.

    SQLite stores timestamps as ``'YYYY-MM-DD HH:MM:SS'`` (space separator, no
    offset marker).  JavaScript's ``new Date()`` needs the ``T`` separator and
    an explicit UTC offset to parse correctly across all browsers.
    """
    if not ts:
        return ts
    if "+" not in ts and "Z" not in ts:
        return ts.replace(" ", "T") + "+00:00"
    return ts


def period_clause(
    period: str,
    col: str = "timestamp",
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[str, list]:
    """Return a (WHERE-fragment, params) pair for a named time period.

    All comparisons are against UTC-stored timestamps.  The configured local
    timezone is used to determine day boundaries so that e.g. ``'today'`` means
    today in ``Europe/London``, not UTC.

    period   — one of: today, 7d, 30d, 90d, 365d, all, custom
    col      — the timestamp column to filter on (default: "timestamp")
    date_from / date_to — YYYY-MM-DD *local* dates used when period == "custom"
    """
    tz = _local_tz()
    today = _local_today()

    if period == "today":
        start, end = _day_utc_bounds(today, tz)
        return f"{col} >= ? AND {col} < ?", [start, end]
    elif period == "7d":
        start, _ = _day_utc_bounds(today - timedelta(days=6), tz)
        return f"{col} >= ?", [start]
    elif period == "30d":
        start, _ = _day_utc_bounds(today - timedelta(days=29), tz)
        return f"{col} >= ?", [start]
    elif period == "90d":
        start, _ = _day_utc_bounds(today - timedelta(days=89), tz)
        return f"{col} >= ?", [start]
    elif period == "365d":
        start, _ = _day_utc_bounds(today - timedelta(days=364), tz)
        return f"{col} >= ?", [start]
    elif period == "custom" and date_from and date_to:
        start, _ = _day_utc_bounds(date.fromisoformat(date_from), tz)
        _, end = _day_utc_bounds(date.fromisoformat(date_to), tz)
        return f"{col} >= ? AND {col} < ?", [start, end]
    else:  # "all" or unrecognised
        return "1=1", []
