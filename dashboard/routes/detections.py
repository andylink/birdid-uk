"""
dashboard/routes/detections.py — detections list endpoint.
"""

from __future__ import annotations

from datetime import date as date_cls
from pathlib import Path
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, Query

from dashboard.database import get_db
from dashboard.utils import _day_utc_bounds, _local_tz, to_utc_iso

router = APIRouter()


@router.get("/api/v1/detections")
async def list_detections(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    species: Optional[str] = None,
    date: Optional[str] = None,
    flagged: Optional[bool] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Return a list of detections, newest first.

    The ``date`` parameter is a local calendar date (YYYY-MM-DD).  Filtering
    uses UTC range bounds so that detections are bucketed by the configured
    local timezone, not raw UTC date.

    Pass ``flagged=true`` to return only cross-validation-flagged detections
    (those requiring manual review).

    Returned timestamps are ISO 8601 with ``+00:00`` suffix so the frontend
    can parse them unambiguously as UTC.
    """
    clauses: list[str] = []
    params: list = []

    if species:
        clauses.append("species = ?")
        params.append(species)
    if date:
        tz = _local_tz()
        start, end = _day_utc_bounds(date_cls.fromisoformat(date), tz)
        clauses.append("timestamp >= ? AND timestamp < ?")
        params.extend([start, end])
    if flagged is not None:
        if flagged:
            clauses.append("flagged = 1")
        else:
            clauses.append("(flagged IS NULL OR flagged = 0)")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = await db.execute_fetchall(
        f"""
        SELECT
            d.id, d.timestamp, d.species, d.bto_name, d.confidence, d.clip_path,
            d.model,
            d.primary_confidence, d.cross_validated,
            d.cv_secondary_model, d.cv_species, d.cv_bto_name,
            d.cv_confidence, d.cv_agree, d.flagged,
            si.scientific_name, si.group_name, si.uk_bocc, si.species_status,
            si.bto_2letter_code, si.bto_5letter_code
        FROM detections d
        LEFT JOIN species_info si ON si.name = d.bto_name
        {where}
        ORDER BY d.id DESC LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )

    result = []
    for r in rows:
        d = dict(r)
        d["filename"] = Path(d["clip_path"]).name if d.get("clip_path") else None
        del d["clip_path"]
        d["timestamp"] = to_utc_iso(d.get("timestamp"))
        result.append(d)
    return result

