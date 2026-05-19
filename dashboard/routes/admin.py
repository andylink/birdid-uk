"""
Admin-only endpoints — all require a valid session cookie (require_admin dependency).

Route order matters: the static path /detections/count is registered before
the parameterised /detections/{id} to avoid it being captured as a wildcard.

GET    /api/v1/admin/detections/count        — count detections (optional species filter)
GET    /api/v1/admin/detections/export       — download all detections as CSV
DELETE /api/v1/admin/detections/{id}         — delete one detection + its audio clip
DELETE /api/v1/admin/detections              — bulk delete (optional species filter)
POST   /api/v1/admin/detections/{id}/flag    — set or clear the flagged field
GET    /api/v1/admin/system/status           — disk usage, detection counts
POST   /api/v1/admin/system/retention        — trigger a retention run immediately
POST   /api/v1/admin/system/clear-image-cache — delete cached species images
POST   /api/v1/admin/system/reseed-species   — wipe and re-seed the species_info table
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from dashboard.auth import require_admin
from dashboard.config import DETECTIONS_DIR
from dashboard.database import get_db, get_engine

router = APIRouter()

# Path to the species filter JSON used to seed species_info.
_JSON_PATH = Path(__file__).parent.parent.parent / "filters" / "uk_species_filter.json"

# Path to the cached species images directory.
_IMAGES_DIR = Path(__file__).parent.parent.parent / "data" / "species_images"


# ── Count (register before /{id}) ─────────────────────────────────────────────

@router.get("/api/v1/admin/detections/count", dependencies=[Depends(require_admin)])
async def count_detections(
    species: Optional[str] = Query(None),
    db: AsyncConnection = Depends(get_db),
):
    """Return the number of detections matching an optional species filter."""
    if species:
        row = (await db.execute(
            text("SELECT COUNT(*) FROM detections WHERE species = :species"),
            {"species": species},
        )).one()
    else:
        row = (await db.execute(text("SELECT COUNT(*) FROM detections"))).one()
    return {"count": row[0]}


# ── Export CSV (static path — register before /{id}) ──────────────────────────

@router.get("/api/v1/admin/detections/export", dependencies=[Depends(require_admin)])
async def export_detections(
    species:   Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db: AsyncConnection = Depends(get_db),
):
    """Stream all matching detections as a CSV download."""
    clauses: list[str] = []
    params: dict = {}

    if species:
        clauses.append("species = :species")
        params["species"] = species
    if date_from:
        clauses.append("timestamp >= :date_from")
        params["date_from"] = date_from
    if date_to:
        clauses.append("timestamp < :date_to")
        params["date_to"] = date_to

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = (await db.execute(
        text(f"SELECT * FROM detections {where} ORDER BY timestamp DESC"),
        params,
    )).mappings().all()

    columns = [
        "id", "timestamp", "species", "confidence", "filename",
        "model", "primary_confidence", "cross_validated", "cv_secondary_model",
        "cv_species", "cv_confidence", "cv_agree", "flagged",
    ]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row.get(c, "") for c in columns])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=detections.csv"},
    )


# ── Delete one detection ───────────────────────────────────────────────────────

@router.delete(
    "/api/v1/admin/detections/{det_id}",
    dependencies=[Depends(require_admin)],
)
async def delete_detection(det_id: int):
    """Delete a single detection row and its audio clip file."""
    async with get_engine().begin() as conn:
        row = (await conn.execute(
            text("SELECT clip_path FROM detections WHERE id = :id"),
            {"id": det_id},
        )).one_or_none()

        if row is None:
            raise HTTPException(status_code=404, detail=f"Detection {det_id} not found")

        clip_path: str | None = row[0]
        await conn.execute(
            text("DELETE FROM detections WHERE id = :id"),
            {"id": det_id},
        )

    # Delete the audio clip after the transaction commits.
    if clip_path:
        p = Path(clip_path)
        if not p.is_absolute():
            p = DETECTIONS_DIR / p
        p.unlink(missing_ok=True)

    return {"id": det_id, "deleted": True}


# ── Bulk delete ────────────────────────────────────────────────────────────────

@router.delete("/api/v1/admin/detections", dependencies=[Depends(require_admin)])
async def bulk_delete_detections(species: Optional[str] = Query(None)):
    """Delete all detections (or all for one species) and their audio clip files."""
    async with get_engine().begin() as conn:
        if species:
            rows = (await conn.execute(
                text("SELECT clip_path FROM detections WHERE species = :species"),
                {"species": species},
            )).fetchall()
            await conn.execute(
                text("DELETE FROM detections WHERE species = :species"),
                {"species": species},
            )
        else:
            rows = (await conn.execute(text("SELECT clip_path FROM detections"))).fetchall()
            await conn.execute(text("DELETE FROM detections"))

    deleted_files = 0
    for row in rows:
        clip_path: str | None = row[0]
        if clip_path:
            p = Path(clip_path)
            if not p.is_absolute():
                p = DETECTIONS_DIR / p
            if p.exists():
                p.unlink(missing_ok=True)
                deleted_files += 1

    return {"deleted_rows": len(rows), "deleted_files": deleted_files}


# ── Toggle flag ────────────────────────────────────────────────────────────────

class FlagBody(BaseModel):
    flagged: bool


@router.post(
    "/api/v1/admin/detections/{det_id}/flag",
    dependencies=[Depends(require_admin)],
)
async def set_flag(det_id: int, body: FlagBody):
    """Set or clear the flagged field on a single detection."""
    async with get_engine().begin() as conn:
        result = await conn.execute(
            text("UPDATE detections SET flagged = :flagged WHERE id = :id"),
            {"flagged": int(body.flagged), "id": det_id},
        )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Detection {det_id} not found")
    return {"id": det_id, "flagged": body.flagged}


# ── System status ──────────────────────────────────────────────────────────────

@router.get("/api/v1/admin/system/status", dependencies=[Depends(require_admin)])
async def system_status(db: AsyncConnection = Depends(get_db)):
    """Return detection counts and disk usage for the detections directory."""
    total  = (await db.execute(text("SELECT COUNT(*) FROM detections"))).one()[0]
    newest = (await db.execute(text("SELECT MAX(timestamp) FROM detections"))).one()[0]
    oldest = (await db.execute(text("SELECT MIN(timestamp) FROM detections"))).one()[0]

    disk_root = DETECTIONS_DIR if DETECTIONS_DIR.exists() else Path("/")
    disk = shutil.disk_usage(disk_root)

    return {
        "total_detections": total,
        "newest_detection":  newest,
        "oldest_detection":  oldest,
        "disk_total_gb":  round(disk.total / 1e9, 2),
        "disk_used_gb":   round(disk.used  / 1e9, 2),
        "disk_free_gb":   round(disk.free  / 1e9, 2),
        "disk_used_pct":  round(disk.used  / disk.total * 100, 1),
    }


# ── Force retention run ────────────────────────────────────────────────────────

@router.post("/api/v1/admin/system/retention", dependencies=[Depends(require_admin)])
async def run_retention():
    """Trigger the retention cleanup and return the number of clips deleted."""
    from retention import run_cleanup  # noqa: PLC0415 — imported lazily to avoid startup cost
    loop    = asyncio.get_event_loop()
    deleted = await loop.run_in_executor(None, run_cleanup)
    return {"clips_deleted": deleted}


# ── Clear image cache ──────────────────────────────────────────────────────────

@router.post(
    "/api/v1/admin/system/clear-image-cache",
    dependencies=[Depends(require_admin)],
)
async def clear_image_cache():
    """Delete all cached species thumbnails from data/species_images/."""
    if not _IMAGES_DIR.is_dir():
        return {"deleted_files": 0}

    deleted = 0
    for f in _IMAGES_DIR.iterdir():
        if f.is_file():
            f.unlink(missing_ok=True)
            deleted += 1

    return {"deleted_files": deleted}


# ── Re-seed species info ───────────────────────────────────────────────────────

@router.post(
    "/api/v1/admin/system/reseed-species",
    dependencies=[Depends(require_admin)],
)
async def reseed_species():
    """Wipe the species_info table and re-seed it from the JSON filter file."""
    if not _JSON_PATH.exists():
        raise HTTPException(status_code=500, detail="Species filter JSON not found")

    entries = json.loads(_JSON_PATH.read_text(encoding="utf-8"))
    rows = [
        {
            "name":                       e["name"],
            "scientific_name":            e.get("scientific_name"),
            "british_list_status":        e.get("british_list_status"),
            "population_estimate":        e.get("population_estimate"),
            "bto_2letter_code":           e.get("bto_2letter_code") or None,
            "bto_5letter_code":           e.get("bto_5letter_code") or None,
            "species_status":             e.get("species_status"),
            "uk_bocc":                    e.get("uk_bocc"),
            "birdfacts_url":              e.get("birdfacts_url"),
            "international_english_name": e.get("international_english_name"),
            "group_name":                 e.get("group_name"),
            "ebird_code":                 e.get("ebird_code") or None,
            "avicommons_image_url":       e.get("avicommons_image_url") or None,
        }
        for e in entries
        if e.get("name")
    ]

    async with get_engine().begin() as conn:
        await conn.execute(text("DELETE FROM species_info"))
        await conn.execute(
            text(
                "INSERT OR REPLACE INTO species_info "
                "(name, scientific_name, british_list_status, population_estimate, "
                " bto_2letter_code, bto_5letter_code, species_status, uk_bocc, "
                " birdfacts_url, international_english_name, group_name, "
                " ebird_code, avicommons_image_url) "
                "VALUES (:name, :scientific_name, :british_list_status, "
                " :population_estimate, :bto_2letter_code, :bto_5letter_code, "
                " :species_status, :uk_bocc, :birdfacts_url, "
                " :international_english_name, :group_name, "
                " :ebird_code, :avicommons_image_url)"
            ),
            rows,
        )

    return {"seeded": len(rows)}
