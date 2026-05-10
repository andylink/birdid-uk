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
    db: aiosqlite.Connection = Depends(get_db),
):
    """Return a list of detections, newest first.

    The ``date`` parameter is a local calendar date (YYYY-MM-DD).  Filtering
    uses UTC range bounds so that detections are bucketed by the configured
    local timezone, not raw UTC date.

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

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = await db.execute_fetchall(
        f"SELECT id, timestamp, species, confidence, clip_path "
        f"FROM detections {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )

    result = []
    for r in rows:
        d = dict(r)
        d["filename"] = Path(d["clip_path"]).name if d.get("clip_path") else None
        d["timestamp"] = to_utc_iso(d.get("timestamp"))
        result.append(d)
    return result
