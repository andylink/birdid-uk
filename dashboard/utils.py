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
    Only used on the SQLite path; PostgreSQL uses IANA-aware AT TIME ZONE instead.
    """
    tz = _local_tz()
    offset_secs = int(datetime.now(tz).utcoffset().total_seconds())
    hours, rem = divmod(abs(offset_secs), 3600)
    mins = rem // 60
    sign = "+" if offset_secs >= 0 else "-"
    if mins:
        return f"'{sign}{hours} hours {mins} minutes'"
    return f"'{sign}{hours} hours'"


# ── Dialect-aware timestamp SQL expression helpers ────────────────────────────
# Each function returns a SQL fragment that produces the requested value in the
# configured local timezone.
#
# SQLite path: uses datetime() + the current UTC offset string (DST-correct at
#              query time via Python; the offset is baked into the SQL string).
# PostgreSQL path: uses AT TIME ZONE with the IANA zone name, which the
#              PostgreSQL server resolves correctly for all DST transitions
#              without any Python-side offset calculation.

def local_datetime_expr(col: str) -> str:
    """SQL expression that returns the local datetime for a UTC timestamp column.

    SQLite:     ``datetime(col, '+1 hours')``
    PostgreSQL: ``(col AT TIME ZONE 'Europe/London')``
    """
    from dashboard.config import DB_TYPE, TIMEZONE
    if DB_TYPE == "postgresql":
        return f"({col} AT TIME ZONE '{TIMEZONE}')"
    return f"datetime({col}, {utc_offset_str()})"


def local_hour_expr(col: str) -> str:
    """SQL expression that returns the local hour (0–23 integer).

    SQLite:     ``CAST(strftime('%H', datetime(col, '+1 hours')) AS INTEGER)``
    PostgreSQL: ``EXTRACT(HOUR FROM (col AT TIME ZONE 'Europe/London'))::INTEGER``
    """
    from dashboard.config import DB_TYPE, TIMEZONE
    if DB_TYPE == "postgresql":
        return f"EXTRACT(HOUR FROM ({col} AT TIME ZONE '{TIMEZONE}'))::INTEGER"
    return f"CAST(strftime('%H', datetime({col}, {utc_offset_str()})) AS INTEGER)"


def local_date_expr(col: str) -> str:
    """SQL expression that returns the local calendar date.

    SQLite:     ``DATE(datetime(col, '+1 hours'))``
    PostgreSQL: ``(col AT TIME ZONE 'Europe/London')::DATE``
    """
    from dashboard.config import DB_TYPE, TIMEZONE
    if DB_TYPE == "postgresql":
        return f"({col} AT TIME ZONE '{TIMEZONE}')::DATE"
    return f"DATE(datetime({col}, {utc_offset_str()}))"


def local_time_expr(col: str) -> str:
    """SQL expression that returns the local time-of-day.

    SQLite:     ``TIME(datetime(col, '+1 hours'))``
    PostgreSQL: ``(col AT TIME ZONE 'Europe/London')::TIME``
    """
    from dashboard.config import DB_TYPE, TIMEZONE
    if DB_TYPE == "postgresql":
        return f"({col} AT TIME ZONE '{TIMEZONE}')::TIME"
    return f"TIME(datetime({col}, {utc_offset_str()}))"


def to_utc_iso(ts: str | datetime | None) -> str | None:
    """Normalise a timestamp value to ISO 8601 with a ``+00:00`` UTC suffix.

    Handles two forms depending on the database backend:

    * **SQLite / aiosqlite**: timestamps are returned as bare strings in the
      form ``'YYYY-MM-DD HH:MM:SS'`` (space separator, no timezone marker).
      JavaScript's ``new Date()`` requires the ``T`` separator and an explicit
      UTC offset to parse correctly across all browsers.

    * **PostgreSQL / asyncpg**: timestamps are returned as Python
      ``datetime`` objects (timezone-aware, UTC).  These are converted to an
      ISO 8601 string with explicit ``+00:00``.
    """
    if ts is None:
        return None
    if isinstance(ts, datetime):
        # asyncpg returns tz-aware datetimes; normalise to UTC ISO string.
        return ts.astimezone(timezone.utc).isoformat()
    # SQLite string: no T separator, no timezone marker.
    if "+" not in ts and "Z" not in ts:
        return ts.replace(" ", "T") + "+00:00"
    return ts


def period_clause(
    period: str,
    col: str = "timestamp",
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[str, dict]:
    """Return a (WHERE-fragment, params-dict) pair for a named time period.

    All comparisons are against UTC-stored timestamps.  The configured local
    timezone is used to determine day boundaries so that e.g. ``'today'`` means
    today in ``Europe/London``, not UTC.

    Uses ``:start`` / ``:end`` named parameters compatible with SQLAlchemy
    ``text()`` queries on both SQLite and PostgreSQL.

    period   — one of: today, 7d, 30d, 90d, 365d, all, custom
    col      — the timestamp column to filter on (default: "timestamp")
    date_from / date_to — YYYY-MM-DD *local* dates used when period == "custom"
    """
    tz = _local_tz()
    today = _local_today()

    if period == "today":
        start, end = _day_utc_bounds(today, tz)
        return f"{col} >= :start AND {col} < :end", {"start": start, "end": end}
    elif period == "7d":
        start, _ = _day_utc_bounds(today - timedelta(days=6), tz)
        return f"{col} >= :start", {"start": start}
    elif period == "30d":
        start, _ = _day_utc_bounds(today - timedelta(days=29), tz)
        return f"{col} >= :start", {"start": start}
    elif period == "90d":
        start, _ = _day_utc_bounds(today - timedelta(days=89), tz)
        return f"{col} >= :start", {"start": start}
    elif period == "365d":
        start, _ = _day_utc_bounds(today - timedelta(days=364), tz)
        return f"{col} >= :start", {"start": start}
    elif period == "custom" and date_from and date_to:
        start, _ = _day_utc_bounds(date.fromisoformat(date_from), tz)
        _, end = _day_utc_bounds(date.fromisoformat(date_to), tz)
        return f"{col} >= :start AND {col} < :end", {"start": start, "end": end}
    else:  # "all" or unrecognised
        return "1=1", {}
