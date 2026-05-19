"""
Weather analytics endpoints — correlate detections with weather conditions.

All endpoints require detections to have weather metadata populated. The
/status endpoint should be called first; the frontend uses its `with_weather`
field to decide whether to show charts or a "weather not configured" message.

Condition normalisation
-----------------------
Raw provider condition strings (from Open-Meteo, yr.no, OpenWeatherMap, etc.)
are mapped to eight fixed buckets in Python rather than SQL to keep the logic
readable and provider-agnostic. Buckets are checked in priority order so that
composite descriptions always resolve to the most significant category:

    Thunder → Snow/Sleet → Drizzle → Rain → Fog/Mist
    → Overcast → Partly cloudy → Clear → Other

Wind direction sectors
----------------------
Degrees are converted to one of 16 compass sectors (22.5° each) with:

    sector = CAST((weather_wind_direction + 11.25) / 22.5 AS INTEGER) % 16

Sector 0 = N, increasing clockwise. Missing sectors are zero-filled so the
response always contains all 16 directions.
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

# ── Canonical condition buckets (display order) ───────────────────────────────

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
    """Map a raw provider condition string to one of the eight canonical buckets.

    Checked in priority order so the most significant condition wins when
    descriptions are compound (e.g. "Thunderstorm with heavy hail").
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


# 16 compass direction labels, sector 0 = N, clockwise.
_WIND_DIRECTIONS = [
    "N", "NNE", "NE", "ENE",
    "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW",
    "W", "WNW", "NW", "NNW",
]

# Wind speed bins in fixed display order.
_WIND_BINS: list[tuple[str, str]] = [
    ("calm",     "Calm (<2 m/s)"),
    ("light",    "Light (2–5 m/s)"),
    ("moderate", "Moderate (5–10 m/s)"),
    ("strong",   "Strong (>10 m/s)"),
]

# Temperature bins in fixed display order.
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
    """Return total detections and how many have weather data for the period.

    The frontend calls this first. If `with_weather` is zero it shows an
    info card rather than weather charts.
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
    """Average weather conditions and most common weather type for the period.

    All fields are null when no weather data exists.
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

    # Normalise raw condition strings to buckets, then find the most common.
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

    Raw provider strings are mapped to canonical buckets before aggregating.
    Buckets with zero detections are omitted from the response.
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

    # Return in canonical display order, skipping empty buckets.
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
    All four bins are always present (zero-filled).
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
    All six bins are always present (zero-filled).
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
    """Detection counts grouped into 16 compass direction sectors (22.5° each).

    Sector 0 = N, increasing clockwise (N, NNE, NE, … NNW).
    All 16 sectors are always present (zero-filled).
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
