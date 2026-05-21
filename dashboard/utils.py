"""
Shared helpers used across dashboard routes.

Covers timestamp normalisation, UTC day-boundary calculation, and
dialect-aware SQL expression builders for SQLite and PostgreSQL.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

# Valid named period values accepted by all period-filtered endpoints.
Period = Literal["today", "7d", "30d", "90d", "365d", "all", "custom"]
VALID_PERIODS: frozenset[str] = frozenset(Period.__args__)  # type: ignore[attr-defined]


def _local_tz() -> ZoneInfo:
    from dashboard.config import LOCAL_TZ
    return LOCAL_TZ


def _local_today() -> date:
    """Today's date in the configured local timezone."""
    return datetime.now(_local_tz()).date()


def _day_utc_bounds(d: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Return the UTC start and end of a local calendar day as naive datetime objects.

    Converts local midnight-to-midnight to UTC so that queries like
    `timestamp >= start AND timestamp < end` correctly select all detections
    for that local date, accounting for DST shifts.

    Returns naive datetime objects (no tzinfo) as asyncpg and aiosqlite both
    expect datetime instances, not strings, for bound query parameters.
    """
    start_local = datetime(d.year, d.month, d.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


def utc_offset_str() -> str:
    """Return the current UTC offset as a SQLite datetime() modifier string.

    Examples: '+1 hours' during BST, '+0 hours' during GMT.
    Half-hour offsets (e.g. India +5:30) include minutes.
    Only used on the SQLite path; PostgreSQL uses AT TIME ZONE instead.
    """
    tz = _local_tz()
    offset_secs = int(datetime.now(tz).utcoffset().total_seconds())
    hours, rem = divmod(abs(offset_secs), 3600)
    mins = rem // 60
    sign = "+" if offset_secs >= 0 else "-"
    if mins:
        return f"'{sign}{hours} hours {mins} minutes'"
    return f"'{sign}{hours} hours'"


# ── Dialect-aware SQL expression helpers ──────────────────────────────────────
# These return SQL fragments that convert a UTC timestamp column to local time.
#
# SQLite: uses datetime() + a Python-computed UTC offset string (correct for
#         the current DST state at query time).
# PostgreSQL: uses AT TIME ZONE with the IANA zone name, which the server
#             handles correctly for all DST transitions.

def local_datetime_expr(col: str) -> str:
    """SQL expression that converts a UTC timestamp column to local datetime.

    SQLite:     datetime(col, '+1 hours')
    PostgreSQL: (col AT TIME ZONE 'Europe/London')
    """
    from dashboard.config import DB_TYPE, TIMEZONE
    if DB_TYPE == "postgresql":
        return f"({col} AT TIME ZONE '{TIMEZONE}')"
    return f"datetime({col}, {utc_offset_str()})"


def local_hour_expr(col: str) -> str:
    """SQL expression that extracts the local hour (0–23) from a UTC timestamp.

    SQLite:     CAST(strftime('%H', datetime(col, '+1 hours')) AS INTEGER)
    PostgreSQL: EXTRACT(HOUR FROM (col AT TIME ZONE 'Europe/London'))::INTEGER
    """
    from dashboard.config import DB_TYPE, TIMEZONE
    if DB_TYPE == "postgresql":
        return f"EXTRACT(HOUR FROM ({col} AT TIME ZONE '{TIMEZONE}'))::INTEGER"
    return f"CAST(strftime('%H', datetime({col}, {utc_offset_str()})) AS INTEGER)"


def local_date_expr(col: str) -> str:
    """SQL expression that extracts the local calendar date from a UTC timestamp.

    SQLite:     DATE(datetime(col, '+1 hours'))
    PostgreSQL: (col AT TIME ZONE 'Europe/London')::DATE
    """
    from dashboard.config import DB_TYPE, TIMEZONE
    if DB_TYPE == "postgresql":
        return f"({col} AT TIME ZONE '{TIMEZONE}')::DATE"
    return f"DATE(datetime({col}, {utc_offset_str()}))"


def local_time_expr(col: str) -> str:
    """SQL expression that extracts the local time-of-day from a UTC timestamp.

    SQLite:     TIME(datetime(col, '+1 hours'))
    PostgreSQL: (col AT TIME ZONE 'Europe/London')::TIME
    """
    from dashboard.config import DB_TYPE, TIMEZONE
    if DB_TYPE == "postgresql":
        return f"({col} AT TIME ZONE '{TIMEZONE}')::TIME"
    return f"TIME(datetime({col}, {utc_offset_str()}))"


def to_utc_iso(ts: str | datetime | None) -> str | None:
    """Normalise a timestamp to ISO 8601 with an explicit +00:00 UTC suffix.

    SQLite/aiosqlite returns timestamps as plain strings ('YYYY-MM-DD HH:MM:SS').
    PostgreSQL/asyncpg returns timezone-aware datetime objects.
    Both are converted to a consistent format that JavaScript's Date() can parse
    correctly across all browsers.
    """
    if ts is None:
        return None
    if not ts:
        return ts
    if isinstance(ts, datetime):
        return ts.astimezone(timezone.utc).isoformat()
    # SQLite string — add T separator and UTC marker
    if "+" not in ts and "Z" not in ts:
        return ts.replace(" ", "T") + "+00:00"
    return ts


def period_clause(
    period: str,
    col: str = "timestamp",
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[str, dict]:
    """Return a (WHERE fragment, params dict) pair for a named time period.

    Day boundaries are calculated in the configured local timezone so that
    e.g. 'today' means today in Europe/London, not UTC midnight.
    Compatible with SQLAlchemy text() queries on both SQLite and PostgreSQL.

    period   — one of: today, 7d, 30d, 90d, 365d, all, custom
    col      — the timestamp column to filter (default: "timestamp")
    date_from / date_to — YYYY-MM-DD local dates, used when period == "custom"
    """
    if period not in VALID_PERIODS:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail=f"Invalid period {period!r}. Must be one of: {', '.join(sorted(VALID_PERIODS))}",
        )
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


def normalise_bools(d: dict) -> dict:
    """Coerce cross-validation boolean fields to integers.

    SQLite returns 0/1; PostgreSQL returns Python bools. The frontend uses
    strict equality (=== 1), so we normalise to integers for both backends.
    """
    for key in ("cross_validated", "cv_agree"):
        if key in d and isinstance(d[key], bool):
            d[key] = int(d[key])
    return d
