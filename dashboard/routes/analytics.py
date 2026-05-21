"""
Analytics endpoints — summary stats, activity-by-hour, species trends,
and conservation breakdowns.

All date/time SQL uses dialect-aware helpers from dashboard.utils so queries
work correctly on both SQLite and PostgreSQL.
"""

from __future__ import annotations

from datetime import date as date_cls
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from dashboard.database import get_db
from dashboard.utils import (
    _day_utc_bounds,
    _local_tz,
    local_date_expr,
    local_hour_expr,
    local_time_expr,
    period_clause as _period_clause,
)

router = APIRouter()


@router.get("/api/v1/analytics/species/daily")
async def species_daily(
    date: str = Query(..., description="YYYY-MM-DD local date"),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncConnection = Depends(get_db),
):
    """Per-species summary for a single day, with a 24-element hourly_counts array.

    `date` is treated as a local calendar date. Hours are extracted in the
    configured timezone so the heatmap aligns with local time.
    """
    tz = _local_tz()
    try:
        start_utc, end_utc = _day_utc_bounds(date_cls.fromisoformat(date), tz)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date format: {date!r}")

    summary_rows = (
        await db.execute(
            text(f"""
            SELECT
                d.species,
                COUNT(*) AS count,
                MIN({local_time_expr('d.timestamp')}) AS first_heard,
                MAX({local_time_expr('d.timestamp')}) AS latest_heard,
                si.scientific_name,
                si.group_name,
                si.uk_bocc,
                si.species_status,
                si.bto_2letter_code,
                si.bto_5letter_code
            FROM detections d
            LEFT JOIN species_info si ON si.name = d.bto_name
            WHERE d.timestamp >= :start AND d.timestamp < :end
            GROUP BY d.species, si.scientific_name, si.group_name,
                     si.uk_bocc, si.species_status,
                     si.bto_2letter_code, si.bto_5letter_code
            ORDER BY count DESC
            LIMIT :limit
            """),
            {"start": start_utc, "end": end_utc, "limit": limit},
        )
    ).mappings().all()

    # Fetch hourly counts for all species in a single query, then merge in Python.
    hourly_rows = (
        await db.execute(
            text(f"""
            SELECT
                species,
                {local_hour_expr('timestamp')} AS hour,
                COUNT(*) AS cnt
            FROM detections
            WHERE timestamp >= :start AND timestamp < :end
            GROUP BY species, hour
            """),
            {"start": start_utc, "end": end_utc},
        )
    ).mappings().all()

    hourly_map: dict[str, list[int]] = {}
    for r in hourly_rows:
        s = r["species"]
        if s not in hourly_map:
            hourly_map[s] = [0] * 24
        hourly_map[s][int(r["hour"])] += r["cnt"]

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
            "first_heard":      str(r["first_heard"]) if r["first_heard"] else None,
            "latest_heard":     str(r["latest_heard"]) if r["latest_heard"] else None,
        }
        for r in summary_rows
    ]


@router.get("/api/v1/analytics/by-hour")
async def by_hour(
    date: Optional[str] = None,
    period: Optional[str] = None,
    db: AsyncConnection = Depends(get_db),
):
    """Total detections grouped by local hour of day (0–23).

    Priority: date (single local day) > period (named range) > all time.
    """
    if date:
        tz = _local_tz()
        try:
            start_utc, end_utc = _day_utc_bounds(date_cls.fromisoformat(date), tz)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid date format: {date!r}")
        where, params = "timestamp >= :start AND timestamp < :end", {"start": start_utc, "end": end_utc}
    elif period:
        where, params = _period_clause(period)
    else:
        where, params = "1=1", {}

    rows = (
        await db.execute(
            text(f"""
            SELECT {local_hour_expr('timestamp')} AS hour,
                   COUNT(*) AS cnt
            FROM detections
            WHERE {where}
            GROUP BY hour
            """),
            params,
        )
    ).mappings().all()

    counts = [0] * 24
    for r in rows:
        counts[int(r["hour"])] = r["cnt"]

    return {
        "labels": [f"{h:02d}:00" for h in range(24)],
        "data": counts,
    }


@router.get("/api/v1/analytics/summary")
async def analytics_summary(
    period: str = Query("today"),
    db: AsyncConnection = Depends(get_db),
):
    """Headline stats for the given period: total detections, unique species,
    average confidence, most common species, and conservation counts."""
    where, params = _period_clause(period)

    totals = (
        await db.execute(
            text(f"""
            SELECT COUNT(*)               AS total,
                   COUNT(DISTINCT species) AS unique_spp,
                   AVG(confidence)         AS avg_conf
            FROM detections
            WHERE {where}
            """),
            params,
        )
    ).mappings().one()

    top = (
        await db.execute(
            text(f"""
            SELECT species, COUNT(*) AS cnt
            FROM detections
            WHERE {where}
            GROUP BY species
            ORDER BY cnt DESC
            LIMIT 1
            """),
            params,
        )
    ).mappings().all()

    # Count distinct species in each UK BoCC category and by scarcity status.
    conservation = (
        await db.execute(
            text(f"""
            SELECT
                COUNT(DISTINCT CASE WHEN si.uk_bocc = 'Red'
                                    THEN d.species END)                                       AS red_list,
                COUNT(DISTINCT CASE WHEN si.uk_bocc = 'Amber'
                                    THEN d.species END)                                       AS amber_list,
                COUNT(DISTINCT CASE WHEN si.uk_bocc = 'Green'
                                    THEN d.species END)                                       AS green_list,
                COUNT(DISTINCT CASE WHEN si.species_status IN ('Scarce', 'Rare', 'Very rare')
                                    THEN d.species END)                                       AS scarce_rare,
                COUNT(DISTINCT si.group_name)                                                 AS groups_represented
            FROM detections d
            LEFT JOIN species_info si ON si.name = d.bto_name
            WHERE {where}
            """),
            params,
        )
    ).mappings().one()

    red   = conservation["red_list"]   or 0
    amber = conservation["amber_list"] or 0
    green = conservation["green_list"] or 0

    return {
        "total_detections":    totals["total"]      or 0,
        "unique_species":      totals["unique_spp"] or 0,
        "avg_confidence":      round(totals["avg_conf"] or 0.0, 4),
        "most_common_species": top[0]["species"] if top else None,
        "most_common_count":   top[0]["cnt"]     if top else 0,
        "red_list_species":    red,
        "scarce_rare_species": conservation["scarce_rare"] or 0,
        "groups_represented":  conservation["groups_represented"] or 0,
        # Weighted score gives more weight to higher-priority conservation species
        "conservation_score":  red * 3 + amber * 2 + green,
    }


@router.get("/api/v1/analytics/top-species")
async def top_species(
    period: str = Query("today"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncConnection = Depends(get_db),
):
    """Top N species by detection count for the given period.

    Includes group_name so the frontend can colour-code bars by bird group.
    """
    where, params = _period_clause(period)

    rows = (
        await db.execute(
            text(f"""
            SELECT d.species, COUNT(*) AS count, si.group_name
            FROM detections d
            LEFT JOIN species_info si ON si.name = d.bto_name
            WHERE {where}
            GROUP BY d.species, si.group_name
            ORDER BY count DESC
            LIMIT :limit
            """),
            {**params, "limit": limit},
        )
    ).mappings().all()

    return [{"species": r["species"], "count": r["count"], "group_name": r["group_name"]} for r in rows]


@router.get("/api/v1/analytics/new-species")
async def new_species_timeline(
    period: str = Query("30d"),
    db: AsyncConnection = Depends(get_db),
):
    """Number of species heard for the first time on each local day in the period.

    A species counts as "new" on the date of its earliest-ever detection, so
    this shows how quickly new species are being added to the site list.
    """
    # Filter on first_seen (each species' earliest detection) rather than all detections
    where, params = _period_clause(period, col="first_seen")

    rows = (
        await db.execute(
            text(f"""
            SELECT {local_date_expr('first_seen')} AS day, COUNT(*) AS new_count
            FROM (
                SELECT species, MIN(timestamp) AS first_seen
                FROM detections
                GROUP BY species
            ) sub
            WHERE {where}
            GROUP BY day
            ORDER BY day
            """),
            params,
        )
    ).mappings().all()

    return [{"day": str(r["day"]), "count": r["new_count"]} for r in rows]


@router.get("/api/v1/analytics/bocc-breakdown")
async def bocc_breakdown(
    period: str = Query("today"),
    db: AsyncConnection = Depends(get_db),
):
    """Unique species count and total detections broken down by UK BoCC conservation status.

    Results are ordered Red → Amber → Green → Unknown so the frontend can
    render them in consistent conservation-priority order.
    """
    where, params = _period_clause(period)

    rows = (
        await db.execute(
            text(f"""
            SELECT
                COALESCE(si.uk_bocc, 'Unknown') AS bocc,
                COUNT(DISTINCT d.species)        AS species_count,
                COUNT(*)                         AS detection_count
            FROM detections d
            LEFT JOIN species_info si ON si.name = d.bto_name
            WHERE {where}
            GROUP BY si.uk_bocc
            ORDER BY CASE COALESCE(si.uk_bocc, 'Unknown')
                         WHEN 'Red'    THEN 1
                         WHEN 'Amber'  THEN 2
                         WHEN 'Green'  THEN 3
                         ELSE 4
                     END
            """),
            params,
        )
    ).mappings().all()

    return [
        {
            "bocc":            r["bocc"],
            "species_count":   r["species_count"],
            "detection_count": r["detection_count"],
        }
        for r in rows
    ]


@router.get("/api/v1/analytics/group-breakdown")
async def group_breakdown(
    period: str = Query("today"),
    limit: int = Query(15, ge=1, le=50),
    db: AsyncConnection = Depends(get_db),
):
    """Detection count and unique species count per taxonomic group, top-N by detections."""
    where, params = _period_clause(period)

    rows = (
        await db.execute(
            text(f"""
            SELECT
                COALESCE(si.group_name, 'Unknown') AS group_name,
                COUNT(DISTINCT d.species)           AS species_count,
                COUNT(*)                            AS detection_count
            FROM detections d
            LEFT JOIN species_info si ON si.name = d.bto_name
            WHERE {where}
            GROUP BY si.group_name
            ORDER BY detection_count DESC
            LIMIT :limit
            """),
            {**params, "limit": limit},
        )
    ).mappings().all()

    return [
        {
            "group_name":      r["group_name"],
            "species_count":   r["species_count"],
            "detection_count": r["detection_count"],
        }
        for r in rows
    ]


@router.get("/api/v1/analytics/bocc-trend")
async def bocc_trend(
    period: str = Query("30d"),
    db: AsyncConnection = Depends(get_db),
):
    """Daily detection counts broken down by UK BoCC status.

    Returns one row per (local calendar day, BoCC status) combination, ordered
    by day then Red → Amber → Green → Unknown. The frontend pivots this into a
    stacked bar chart.
    """
    where, params = _period_clause(period)

    rows = (
        await db.execute(
            text(f"""
            SELECT
                {local_date_expr('d.timestamp')}        AS day,
                COALESCE(si.uk_bocc, 'Unknown')          AS bocc,
                COUNT(*)                                 AS detection_count
            FROM detections d
            LEFT JOIN species_info si ON si.name = d.bto_name
            WHERE {where}
            GROUP BY day, si.uk_bocc
            ORDER BY day,
                     CASE COALESCE(si.uk_bocc, 'Unknown')
                         WHEN 'Red'    THEN 1
                         WHEN 'Amber'  THEN 2
                         WHEN 'Green'  THEN 3
                         ELSE 4
                     END
            """),
            params,
        )
    ).mappings().all()

    return [
        {
            "day":             str(r["day"]),
            "bocc":            r["bocc"],
            "detection_count": r["detection_count"],
        }
        for r in rows
    ]
