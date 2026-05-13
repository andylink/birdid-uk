"""
dashboard/routes/weather.py — weather analytics endpoints.

All endpoints require at least one detection with weather metadata before
returning meaningful data.  The ``/status`` endpoint is designed to be
called first; the frontend uses its ``with_weather`` field to decide whether
to render charts or a "weather not configured" info card.

Condition normalisation
-----------------------
The ``by-condition`` endpoint maps raw provider condition strings stored in
``detections.weather_condition`` to eight canonical buckets so that results
are comparable across providers (Open-Meteo, yr.no, OpenWeatherMap, Tempest).
Normalisation is done in Python rather than SQL to keep the logic readable
and provider-agnostic.  The buckets are checked in priority order:

    Thunder → Snow/Sleet → Drizzle → Rain → Fog/Mist
    → Overcast → Partly cloudy → Clear → Other

Wind direction rose
-------------------
Sectors are computed with::

    sector = CAST((weather_wind_direction + 11.25) / 22.5 AS INTEGER) % 16

Sector 0 = N, increasing clockwise (N, NNE, NE, … NNW).  The query groups
by sector index; missing sectors are filled with zero so the response always
has exactly 16 entries in compass order.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from dashboard.database import get_db
from dashboard.utils import period_clause as _period_clause

router = APIRouter()

# ── Canonical condition buckets ───────────────────────────────────────────────

_CANONICAL_ORDER = [
    "Clear",
    "Partly cloudy",
    "Overcast",
    "Fog / Mist",
    "Drizzle",
    "Rain",
    "Snow / Sleet",
    "Thunder",
    "Other",
]


def _normalise_condition(raw: str) -> str:
    """Map a raw provider condition string to a canonical bucket.

    Rules are checked in priority order so composite descriptions (e.g.
    "Snow with thunder", "Thunderstorm with heavy hail") always resolve to
    the most meteorologically significant bucket.
    """
    s = raw.lower()
    if "thunder" in s or ("storm" in s and "snow" not in s):
        return "Thunder"
    if "snow" in s or "sleet" in s or "blizzard" in s or "hail" in s:
        return "Snow / Sleet"
    if "drizzle" in s:
        return "Drizzle"
    if "rain" in s or "shower" in s:
        return "Rain"
    if "fog" in s or "mist" in s or "haze" in s or "smoke" in s or "rime" in s:
        return "Fog / Mist"
    if "overcast" in s or "broken" in s or "mostly cloud" in s:
        return "Overcast"
    if "partly" in s or "scattered" in s or "few cloud" in s:
        return "Partly cloudy"
    if "clear" in s or "fair" in s or "sunny" in s or "mainly" in s:
        return "Clear"
    return "Other"


# ── Wind direction labels (sector 0 = N, clockwise) ──────────────────────────

_WIND_DIRECTIONS = [
    "N", "NNE", "NE", "ENE",
    "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW",
    "W", "WNW", "NW", "NNW",
]

# ── Wind speed bins (fixed order for display) ─────────────────────────────────

_WIND_BINS: list[tuple[str, str]] = [
    ("calm",     "Calm (<2 m/s)"),
    ("light",    "Light (2–5 m/s)"),
    ("moderate", "Moderate (5–10 m/s)"),
    ("strong",   "Strong (>10 m/s)"),
]

# ── Temperature bins (fixed order for display) ────────────────────────────────

_TEMP_BINS: list[tuple[str, str]] = [
    ("sub_zero",       "Below 0°C"),
    ("zero_five",      "0–5°C"),
    ("five_ten",       "5–10°C"),
    ("ten_fifteen",    "10–15°C"),
    ("fifteen_twenty", "15–20°C"),
    ("above_twenty",   "Above 20°C"),
]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/v1/weather/status")
async def weather_status(
    period: str = Query("30d"),
    db: AsyncConnection = Depends(get_db),
):
    """Return detection counts and weather coverage for the given period.

    The frontend calls this first.  When ``with_weather`` is zero the page
    renders an informational card instead of charts.
    """
    where, params = _period_clause(period)
    row = (
        await db.execute(
            text(f"""
            SELECT
                COUNT(*)              AS total_detections,
                COUNT(weather_temp)   AS with_weather
            FROM detections
            WHERE {where}
            """),
            params,
        )
    ).mappings().one()

    total        = row["total_detections"] or 0
    with_weather = row["with_weather"]     or 0
    coverage_pct = round(with_weather / total * 100, 1) if total else 0.0

    return {
        "total_detections": total,
        "with_weather":     with_weather,
        "coverage_pct":     coverage_pct,
    }


@router.get("/api/v1/weather/summary")
async def weather_summary(
    period: str = Query("30d"),
    db: AsyncConnection = Depends(get_db),
):
    """Aggregate weather statistics (averages + most common condition).

    All fields are ``null`` when no weather data exists for the period.
    """
    where, params = _period_clause(period)

    agg = (
        await db.execute(
            text(f"""
            SELECT
                AVG(weather_temp)        AS avg_temp,
                AVG(weather_humidity)    AS avg_humidity,
                AVG(weather_wind_speed)  AS avg_wind_speed,
                AVG(weather_pressure)    AS avg_pressure
            FROM detections
            WHERE weather_temp IS NOT NULL AND {where}
            """),
            params,
        )
    ).mappings().one()

    # Most common condition — normalise first, then find the modal bucket.
    cond_rows = (
        await db.execute(
            text(f"""
            SELECT weather_condition, COUNT(*) AS cnt
            FROM detections
            WHERE weather_condition IS NOT NULL AND {where}
            GROUP BY weather_condition
            """),
            params,
        )
    ).mappings().all()

    bucket_counts: dict[str, int] = defaultdict(int)
    for r in cond_rows:
        bucket = _normalise_condition(r["weather_condition"])
        bucket_counts[bucket] += r["cnt"]

    most_common = max(bucket_counts, key=lambda k: bucket_counts[k]) if bucket_counts else None

    def _r(v: object) -> float | None:
        return round(float(v), 1) if v is not None else None  # type: ignore[arg-type]

    return {
        "avg_temp":              _r(agg["avg_temp"]),
        "avg_humidity":          _r(agg["avg_humidity"]),
        "avg_wind_speed":        _r(agg["avg_wind_speed"]),
        "avg_pressure":          _r(agg["avg_pressure"]),
        "most_common_condition": most_common,
    }


@router.get("/api/v1/weather/by-condition")
async def weather_by_condition(
    period: str = Query("30d"),
    db: AsyncConnection = Depends(get_db),
):
    """Detection counts grouped by normalised weather condition.

    Raw provider strings from ``detections.weather_condition`` are mapped to
    eight canonical buckets before aggregation, so results are comparable
    across providers.  Buckets with zero detections are omitted.
    """
    where, params = _period_clause(period)

    rows = (
        await db.execute(
            text(f"""
            SELECT weather_condition, COUNT(*) AS count
            FROM detections
            WHERE weather_condition IS NOT NULL AND {where}
            GROUP BY weather_condition
            """),
            params,
        )
    ).mappings().all()

    bucket_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        bucket = _normalise_condition(r["weather_condition"])
        bucket_counts[bucket] += r["count"]

    # Return in canonical display order, omitting empty buckets.
    return [
        {"condition": name, "count": bucket_counts[name]}
        for name in _CANONICAL_ORDER
        if bucket_counts.get(name, 0) > 0
    ]


@router.get("/api/v1/weather/by-wind-speed")
async def weather_by_wind_speed(
    period: str = Query("30d"),
    db: AsyncConnection = Depends(get_db),
):
    """Detection counts grouped into four wind speed bins.

    Bins: Calm (<2 m/s), Light (2–5 m/s), Moderate (5–10 m/s), Strong (>10 m/s).
    All four bins are always present in the response (zero-filled).
    """
    where, params = _period_clause(period)

    rows = (
        await db.execute(
            text(f"""
            SELECT
                CASE
                    WHEN weather_wind_speed <  2  THEN 'calm'
                    WHEN weather_wind_speed <  5  THEN 'light'
                    WHEN weather_wind_speed < 10  THEN 'moderate'
                    ELSE 'strong'
                END AS bin,
                COUNT(*) AS count
            FROM detections
            WHERE weather_wind_speed IS NOT NULL AND {where}
            GROUP BY bin
            """),
            params,
        )
    ).mappings().all()

    counts = {r["bin"]: r["count"] for r in rows}
    return [
        {"bin": key, "label": label, "count": counts.get(key, 0)}
        for key, label in _WIND_BINS
    ]


@router.get("/api/v1/weather/by-temperature")
async def weather_by_temperature(
    period: str = Query("30d"),
    db: AsyncConnection = Depends(get_db),
):
    """Detection counts grouped into six temperature bins.

    Bins: <0°C, 0–5°C, 5–10°C, 10–15°C, 15–20°C, >20°C.
    All six bins are always present in the response (zero-filled).
    """
    where, params = _period_clause(period)

    rows = (
        await db.execute(
            text(f"""
            SELECT
                CASE
                    WHEN weather_temp <  0  THEN 'sub_zero'
                    WHEN weather_temp <  5  THEN 'zero_five'
                    WHEN weather_temp < 10  THEN 'five_ten'
                    WHEN weather_temp < 15  THEN 'ten_fifteen'
                    WHEN weather_temp < 20  THEN 'fifteen_twenty'
                    ELSE 'above_twenty'
                END AS bin,
                COUNT(*) AS count
            FROM detections
            WHERE weather_temp IS NOT NULL AND {where}
            GROUP BY bin
            """),
            params,
        )
    ).mappings().all()

    counts = {r["bin"]: r["count"] for r in rows}
    return [
        {"bin": key, "label": label, "count": counts.get(key, 0)}
        for key, label in _TEMP_BINS
    ]


@router.get("/api/v1/weather/wind-rose")
async def weather_wind_rose(
    period: str = Query("30d"),
    db: AsyncConnection = Depends(get_db),
):
    """Detection counts grouped into 16 compass direction sectors.

    Sector 0 = N, increasing clockwise in 22.5° steps (N, NNE, NE, … NNW).
    All 16 sectors are always present (zero-filled).  The sector index is
    computed as::

        CAST((weather_wind_direction + 11.25) / 22.5 AS INTEGER) % 16
    """
    where, params = _period_clause(period)

    rows = (
        await db.execute(
            text(f"""
            SELECT
                CAST((weather_wind_direction + 11.25) / 22.5 AS INTEGER) % 16 AS sector,
                COUNT(*) AS count
            FROM detections
            WHERE weather_wind_direction IS NOT NULL AND {where}
            GROUP BY sector
            """),
            params,
        )
    ).mappings().all()

    counts = {int(r["sector"]): r["count"] for r in rows}
    return [
        {"direction": direction, "count": counts.get(i, 0)}
        for i, direction in enumerate(_WIND_DIRECTIONS)
    ]
