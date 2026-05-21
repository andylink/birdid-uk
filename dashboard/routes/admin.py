"""
Admin-only endpoints — all require a valid session cookie (require_admin dependency).

Route order matters: the static path /detections/count is registered before
the parameterised /detections/{id} to avoid it being captured as a wildcard.

GET    /api/v1/admin/detections/count            — count detections (optional species filter)
GET    /api/v1/admin/detections/export           — download all detections as CSV
DELETE /api/v1/admin/detections/{id}             — delete one detection + its audio clip
DELETE /api/v1/admin/detections                  — bulk delete (optional species filter)
PATCH  /api/v1/admin/detections/{id}/verification — set verification_status
PATCH  /api/v1/admin/detections/{id}/species     — change species (corrects false positives)
GET    /api/v1/admin/species                     — list all species from species_info
GET    /api/v1/admin/system/status               — disk usage, detection counts
POST   /api/v1/admin/system/retention            — trigger a retention run immediately
POST   /api/v1/admin/system/clear-image-cache    — delete cached species images
POST   /api/v1/admin/system/reseed-species       — wipe and re-seed the species_info table
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from dashboard.auth import require_admin
from dashboard.config import DETECTIONS_DIR, SPECTROGRAMS_DIR, DB_TYPE, LOCAL_TZ
from dashboard.database import get_db, get_engine
from dashboard.utils import _day_utc_bounds

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
        try:
            start, _ = _day_utc_bounds(date.fromisoformat(date_from), LOCAL_TZ)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid date_from format: {date_from!r}")
        clauses.append("timestamp >= :date_from")
        params["date_from"] = start
    if date_to:
        try:
            _, end = _day_utc_bounds(date.fromisoformat(date_to), LOCAL_TZ)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid date_to format: {date_to!r}")
        clauses.append("timestamp < :date_to")
        params["date_to"] = end

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = (await db.execute(
        text(f"SELECT * FROM detections {where} ORDER BY timestamp DESC"),
        params,
    )).mappings().all()

    columns = [
        "id", "timestamp", "species", "confidence", "filename",
        "model", "primary_confidence", "cross_validated", "cv_secondary_model",
        "cv_species", "cv_confidence", "cv_agree", "verification_status",
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


# ── Set verification status ────────────────────────────────────────────────────

# Valid values for verification_status
_VALID_STATUSES = {"unverified", "auto", "cv", "human"}


class VerificationBody(BaseModel):
    verification_status: str


@router.patch(
    "/api/v1/admin/detections/{det_id}/verification",
    dependencies=[Depends(require_admin)],
)
async def set_verification(det_id: int, body: VerificationBody):
    """Set the verification_status on a single detection.

    Valid values: unverified, auto, cv, human.
    """
    if body.verification_status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{body.verification_status}'. "
                   f"Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
        )
    async with get_engine().begin() as conn:
        result = await conn.execute(
            text("UPDATE detections SET verification_status = :vs WHERE id = :id"),
            {"vs": body.verification_status, "id": det_id},
        )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Detection {det_id} not found")
    return {"id": det_id, "verification_status": body.verification_status}


# ── Edit species (correct false positives) ────────────────────────────────────

class EditSpeciesBody(BaseModel):
    bto_name: str


@router.patch(
    "/api/v1/admin/detections/{det_id}/species",
    dependencies=[Depends(require_admin)],
)
async def edit_detection_species(det_id: int, body: EditSpeciesBody):
    """Change the species on a detection to correct a false positive.

    Updates species, bto_name, cv_species, cv_bto_name, clip_path, and sets
    verification_status to 'human'.  The audio clip file and its spectrogram
    PNG are renamed on disk to match the new species label.
    """
    # ── 1. Validate new species exists in species_info ─────────────────────────
    async with get_engine().connect() as conn:
        sp_row = (await conn.execute(
            text("SELECT name, international_english_name FROM species_info WHERE name = :name"),
            {"name": body.bto_name},
        )).one_or_none()

    if sp_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Species '{body.bto_name}' not found in species_info",
        )
    new_bto_name = sp_row[0]
    # Use the international (BirdNET/eBird) label when available, else BTO name.
    new_species  = sp_row[1] or sp_row[0]

    # ── 2. Read the current detection's clip_path ──────────────────────────────
    async with get_engine().connect() as conn:
        det_row = (await conn.execute(
            text("SELECT id, clip_path FROM detections WHERE id = :id"),
            {"id": det_id},
        )).one_or_none()

    if det_row is None:
        raise HTTPException(status_code=404, detail=f"Detection {det_id} not found")

    old_clip_path: str | None = det_row[1]
    new_clip_path = old_clip_path  # updated below if rename succeeds

    # ── 3. Rename audio clip and spectrogram PNG (best-effort) ─────────────────
    if old_clip_path:
        p = Path(old_clip_path)
        abs_p = p if p.is_absolute() else DETECTIONS_DIR / p

        # Derive the datetime prefix and new stem from the stored path string,
        # regardless of whether the audio file still exists on disk.
        # Filename format: YYYYMMDD_HHMMSS_Species_Name.ext
        stem = abs_p.stem   # e.g. "20260519_160531_Common_Moorhen"
        ext  = abs_p.suffix  # e.g. ".flac"
        parts = stem.split('_')
        dt_prefix = f"{parts[0]}_{parts[1]}" if len(parts) >= 2 else stem
        new_stem  = f"{dt_prefix}_{new_species.replace(' ', '_')}"

        # Rename the audio clip if it still exists on disk.
        if abs_p.is_file():
            new_abs_p = abs_p.parent / f"{new_stem}{ext}"
            try:
                abs_p.rename(new_abs_p)
                # Preserve whatever prefix (relative dir, or none) was stored.
                new_clip_path = (
                    str(new_abs_p) if p.is_absolute()
                    else str(p.parent / new_abs_p.name)
                )
            except OSError:
                pass  # Non-fatal: keep old path in DB if rename fails

        # Rename the spectrogram PNG independently — it may still exist even if
        # the audio clip was already removed by the retention policy.
        old_png = SPECTROGRAMS_DIR / f"{stem}.png"
        if old_png.is_file():
            try:
                old_png.rename(SPECTROGRAMS_DIR / f"{new_stem}.png")
            except OSError:
                pass

    # ── 4. Persist all changes in a single transaction ─────────────────────────
    async with get_engine().begin() as conn:
        result = await conn.execute(
            text("""
                UPDATE detections SET
                    species             = :species,
                    bto_name            = :bto_name,
                    clip_path           = :clip_path,
                    cv_species          = :cv_species,
                    cv_bto_name         = :cv_bto_name,
                    verification_status = 'human'
                WHERE id = :id
            """),
            {
                "species":    new_species,
                "bto_name":   new_bto_name,
                "clip_path":  new_clip_path,
                "cv_species":  new_species,
                "cv_bto_name": new_bto_name,
                "id":          det_id,
            },
        )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Detection {det_id} not found")

    return {
        "id":       det_id,
        "species":  new_species,
        "bto_name": new_bto_name,
    }


# ── List all species (for the edit-species dropdown) ──────────────────────────

@router.get("/api/v1/admin/species", dependencies=[Depends(require_admin)])
async def list_all_species(db: AsyncConnection = Depends(get_db)):
    """Return every species in species_info, sorted alphabetically by BTO name.

    Used to populate the 'edit species' dropdown on the species detail page so
    admins can correct false-positive detections.
    """
    rows = (await db.execute(
        text("SELECT name, international_english_name FROM species_info ORDER BY name ASC")
    )).mappings().all()
    return [
        {
            "name":                       r["name"],
            "international_english_name": r["international_english_name"],
        }
        for r in rows
    ]


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
    deleted = await asyncio.to_thread(run_cleanup)
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
            "avicommons_image_by":        e.get("avicommons_image_by") or None,
            "avicommons_image_license":   e.get("avicommons_image_license") or None,
        }
        for e in entries
        if e.get("name")
    ]

    async with get_engine().begin() as conn:
        await conn.execute(text("DELETE FROM species_info"))
        _cols = (
            "name, scientific_name, british_list_status, population_estimate, "
            "bto_2letter_code, bto_5letter_code, species_status, uk_bocc, "
            "birdfacts_url, international_english_name, group_name, "
            "ebird_code, avicommons_image_url, "
            "avicommons_image_by, avicommons_image_license"
        )
        _vals = (
            ":name, :scientific_name, :british_list_status, "
            ":population_estimate, :bto_2letter_code, :bto_5letter_code, "
            ":species_status, :uk_bocc, :birdfacts_url, "
            ":international_english_name, :group_name, "
            ":ebird_code, :avicommons_image_url, "
            ":avicommons_image_by, :avicommons_image_license"
        )
        if DB_TYPE == "sqlite":
            _stmt = f"INSERT OR REPLACE INTO species_info ({_cols}) VALUES ({_vals})"
        else:
            _stmt = (
                f"INSERT INTO species_info ({_cols}) VALUES ({_vals}) "
                "ON CONFLICT (name) DO UPDATE SET "
                "scientific_name=EXCLUDED.scientific_name, "
                "british_list_status=EXCLUDED.british_list_status, "
                "population_estimate=EXCLUDED.population_estimate, "
                "bto_2letter_code=EXCLUDED.bto_2letter_code, "
                "bto_5letter_code=EXCLUDED.bto_5letter_code, "
                "species_status=EXCLUDED.species_status, "
                "uk_bocc=EXCLUDED.uk_bocc, "
                "birdfacts_url=EXCLUDED.birdfacts_url, "
                "international_english_name=EXCLUDED.international_english_name, "
                "group_name=EXCLUDED.group_name, "
                "ebird_code=EXCLUDED.ebird_code, "
                "avicommons_image_url=EXCLUDED.avicommons_image_url, "
                "avicommons_image_by=EXCLUDED.avicommons_image_by, "
                "avicommons_image_license=EXCLUDED.avicommons_image_license"
            )
        await conn.execute(text(_stmt), rows)

    return {"seeded": len(rows)}
