"""
dashboard/routes/analytics.py — daily species heatmap and by-hour activity.

All SQL date/time extraction (DATE, strftime, TIME) applies a UTC offset
modifier via SQLite's datetime() function so that hours and dates reflect the
configured local timezone (e.g. Europe/London), not raw UTC.
"""

from __future__ import annotations

from datetime import date as date_cls
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, Query

from dashboard.database import get_db
from dashboard.utils import (
    _day_utc_bounds,
    _local_tz,
    period_clause as _period_clause,
    utc_offset_str,
)

router = APIRouter()


# ── Existing endpoints ────────────────────────────────────────────────────────

@router.get("/api/v1/analytics/species/daily")
async def species_daily(
    date: str = Query(..., description="YYYY-MM-DD local date"),
    limit: int = Query(200, ge=1, le=1000),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Per-species daily summary with a 24-element hourly_counts array.

    ``date`` is interpreted as a local calendar date; the query uses the
    configured timezone's UTC offset to extract local hours and to build the
    UTC timestamp range for the day boundary filter.
    """
    tz = _local_tz()
    ofs = utc_offset_str()
    start_utc, end_utc = _day_utc_bounds(date_cls.fromisoformat(date), tz)

    summary_rows = await db.execute_fetchall(
        f"""
        SELECT
            d.species,
            COUNT(*) AS count,
            MIN(TIME(datetime(d.timestamp, {ofs}))) AS first_heard,
            MAX(TIME(datetime(d.timestamp, {ofs}))) AS latest_heard,
            si.scientific_name,
            si.group_name,
            si.uk_bocc,
            si.species_status,
            si.bto_2letter_code,
            si.bto_5letter_code
        FROM detections d
        LEFT JOIN species_info si ON si.name = d.bto_name
        WHERE d.timestamp >= ? AND d.timestamp < ?
        GROUP BY d.species
        ORDER BY count DESC
        LIMIT ?
        """,
        (start_utc, end_utc, limit),
    )

    # Hourly breakdown for all species on this date in one query.
    hourly_rows = await db.execute_fetchall(
        f"""
        SELECT
            species,
            CAST(strftime('%H', datetime(timestamp, {ofs})) AS INTEGER) AS hour,
            COUNT(*) AS cnt
        FROM detections
        WHERE timestamp >= ? AND timestamp < ?
        GROUP BY species, hour
        """,
        (start_utc, end_utc),
    )

    hourly_map: dict[str, list[int]] = {}
    for r in hourly_rows:
        s = r["species"]
        if s not in hourly_map:
            hourly_map[s] = [0] * 24
        hourly_map[s][r["hour"]] += r["cnt"]

    return [
        {
            "species":          r["species"],
            "scientific_name":  r["scientific_name"],
            "group_name":       r["group_name"],
            "uk_bocc":          r["uk_bocc"],
            "species_status":   r["species_status"],
            "bto_2letter_code": r["bto_2letter_code"],
            "bto_5letter_code": r["bto_5letter_code"],
            "count":            r["count"],
            "hourly_counts":    hourly_map.get(r["species"], [0] * 24),
            "first_heard":      r["first_heard"],
            "latest_heard":     r["latest_heard"],
        }
        for r in summary_rows
    ]


@router.get("/api/v1/analytics/by-hour")
async def by_hour(
    date: Optional[str] = None,
    period: Optional[str] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Total detections grouped by local hour of day.

    Priority: date (single local day) > period (named range) > all time.
    Hours are extracted in the configured local timezone.
    """
    ofs = utc_offset_str()

    if date:
        tz = _local_tz()
        start_utc, end_utc = _day_utc_bounds(date_cls.fromisoformat(date), tz)
        where, params = "timestamp >= ? AND timestamp < ?", [start_utc, end_utc]
    elif period:
        where, params = _period_clause(period)
    else:
        where, params = "1=1", []

    rows = await db.execute_fetchall(
        f"""
        SELECT CAST(strftime('%H', datetime(timestamp, {ofs})) AS INTEGER) AS hour,
               COUNT(*) AS cnt
        FROM detections
        WHERE {where}
        GROUP BY hour
        """,
        params,
    )

    counts = [0] * 24
    for r in rows:
        counts[r["hour"]] = r["cnt"]

    return {
        "labels": [f"{h:02d}:00" for h in range(24)],
        "data": counts,
    }


# ── Analytics endpoints ───────────────────────────────────────────────────────

@router.get("/api/v1/analytics/summary")
async def analytics_summary(
    period: str = Query("today"),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Headline stats: total detections, unique species, avg confidence, top species."""
    where, params = _period_clause(period)

    totals = (await db.execute_fetchall(
        f"""
        SELECT COUNT(*)              AS total,
               COUNT(DISTINCT species) AS unique_spp,
               AVG(confidence)       AS avg_conf
        FROM detections
        WHERE {where}
        """,
        params,
    ))[0]

    top = await db.execute_fetchall(
        f"""
        SELECT species, COUNT(*) AS cnt
        FROM detections
        WHERE {where}
        GROUP BY species
        ORDER BY cnt DESC
        LIMIT 1
        """,
        params,
    )

    return {
        "total_detections": totals["total"] or 0,
        "unique_species": totals["unique_spp"] or 0,
        "avg_confidence": round(totals["avg_conf"] or 0.0, 4),
        "most_common_species": top[0]["species"] if top else None,
        "most_common_count": top[0]["cnt"] if top else 0,
    }


@router.get("/api/v1/analytics/top-species")
async def top_species(
    period: str = Query("today"),
    limit: int = Query(10, ge=1, le=50),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Top N species by detection count for the given period."""
    where, params = _period_clause(period)

    rows = await db.execute_fetchall(
        f"""
        SELECT species, COUNT(*) AS count
        FROM detections
        WHERE {where}
        GROUP BY species
        ORDER BY count DESC
        LIMIT ?
        """,
        params + [limit],
    )

    return [{"species": r["species"], "count": r["count"]} for r in rows]


@router.get("/api/v1/analytics/new-species")
async def new_species_timeline(
    period: str = Query("30d"),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Number of species recorded for the very first time on each local day in the period.

    A species is "new" on the date of its earliest detection ever — this shows
    the rate at which new species are being added to the site list.
    Days are expressed in the configured local timezone.
    """
    ofs = utc_offset_str()
    # Filter `first_seen` (the species' first-ever detection) to the period.
    where, params = _period_clause(period, col="first_seen")

    rows = await db.execute_fetchall(
        f"""
        SELECT DATE(datetime(first_seen, {ofs})) AS day, COUNT(*) AS new_count
        FROM (
            SELECT species, MIN(timestamp) AS first_seen
            FROM detections
            GROUP BY species
        )
        WHERE {where}
        GROUP BY day
        ORDER BY day
        """,
        params,
    )

    return [{"day": r["day"], "count": r["new_count"]} for r in rows]
