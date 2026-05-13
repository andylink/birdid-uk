"""
dashboard/routes/species.py — per-species statistics and AviCommons image cache.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from dashboard.config import DETECTIONS_DIR
from dashboard.database import get_db
from dashboard.utils import period_clause, to_utc_iso

router = APIRouter()

# ── Image cache ────────────────────────────────────────────────────────────────

IMAGE_DIR: Path = DETECTIONS_DIR.parent / "species_images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_TTL_DAYS = 30     # re-fetch positive cache after this many days
NEGATIVE_TTL_DAYS = 1   # retry failed lookups after this many days

_UA = "bird-detector/1.0 (local garden monitor; contact via github)"

# Limit concurrent outbound requests to avoid hammering the CDN.
_IMG_SEM = asyncio.Semaphore(4)

SORT_COLS = {
    "detections_desc":        "detections DESC",
    "detections_asc":         "detections ASC",
    "avg_confidence_desc":    "avg_confidence DESC",
    "avg_confidence_asc":     "avg_confidence ASC",
    "peak_confidence_desc":   "peak_confidence DESC",
    "peak_confidence_asc":    "peak_confidence ASC",
    "first_detected_asc":     "first_detected ASC",
    "first_detected_desc":    "first_detected DESC",
    "last_detected_desc":     "last_detected DESC",
    "last_detected_asc":      "last_detected ASC",
    "name_asc":               "d.species ASC",
    "name_desc":              "d.species DESC",
    "group_asc":              "si.group_name ASC",
    "group_desc":             "si.group_name DESC",
    "status_asc":             "si.species_status ASC",
    "status_desc":            "si.species_status DESC",
    "bocc_asc":               "si.uk_bocc ASC",
    "bocc_desc":              "si.uk_bocc DESC",
}


def _slug(species: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", species.lower()).strip("_")


def _img_path(species: str) -> Path:
    return IMAGE_DIR / f"{_slug(species)}.jpg"


def _neg_path(species: str) -> Path:
    return IMAGE_DIR / f"{_slug(species)}.none"


def _age_days(path: Path) -> float:
    return (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).days


async def _fetch_image_bytes(url: str) -> bytes | None:
    """Fetch image bytes from a URL. Returns JPEG bytes or None on failure."""
    async with _IMG_SEM:
        async with httpx.AsyncClient(headers={"User-Agent": _UA}, timeout=15) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return r.content
            return None


def _normalise_bools(d: dict) -> dict:
    """Coerce boolean DB fields to integers for frontend compatibility.

    SQLite returns 0/1 integers; PostgreSQL/asyncpg returns Python bools.
    """
    for key in ("flagged", "cross_validated", "cv_agree"):
        if key in d and isinstance(d[key], bool):
            d[key] = int(d[key])
    return d


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/v1/species/image")
async def species_image(
    name: str = Query(..., description="BTO common species name"),
    db: AsyncConnection = Depends(get_db),
):
    """Serve a cached species photo sourced from AviCommons.

    Images are stored in data/species_images/ and refreshed every 30 days.
    A .none sentinel file is written when no AviCommons URL is available or
    the fetch fails (retried daily).
    """
    img_path = _img_path(name)
    neg_path = _neg_path(name)

    # Positive cache hit
    if img_path.exists() and _age_days(img_path) < IMAGE_TTL_DAYS:
        return FileResponse(str(img_path), media_type="image/jpeg")

    # Negative cache — don't retry failed lookups too often
    if neg_path.exists() and _age_days(neg_path) < NEGATIVE_TTL_DAYS:
        raise HTTPException(status_code=404, detail="No image available")

    # Look up AviCommons image URL from species_info
    rows = (
        await db.execute(
            text("SELECT avicommons_image_url FROM species_info WHERE name = :name LIMIT 1"),
            {"name": name},
        )
    ).mappings().all()
    avi_url: str | None = rows[0]["avicommons_image_url"] if rows else None

    if not avi_url:
        neg_path.touch()
        raise HTTPException(status_code=404, detail="No image available for this species")

    # Fetch from AviCommons CDN
    try:
        data = await _fetch_image_bytes(avi_url)
    except Exception:
        neg_path.touch()
        raise HTTPException(status_code=404, detail="Image fetch failed")

    if data is None:
        neg_path.touch()
        raise HTTPException(status_code=404, detail="No image at AviCommons CDN")

    img_path.write_bytes(data)
    neg_path.unlink(missing_ok=True)
    return FileResponse(str(img_path), media_type="image/jpeg")


@router.get("/api/v1/species")
async def list_species(
    period: str = Query("all"),
    sort: str = Query("detections_desc"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD (custom period start)"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD (custom period end)"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    bocc: Optional[str] = Query(None, description="Filter by BoCC status: Red, Amber, Green"),
    status: Optional[str] = Query(None, description="Filter by species_status e.g. Scarce"),
    group: Optional[str] = Query(None, description="Filter by group_name e.g. Warblers"),
    db: AsyncConnection = Depends(get_db),
):
    """Per-species detection statistics for the given period, sorted as requested.

    Optional conservation filters (bocc, status, group) are applied via a
    LEFT JOIN on species_info; they narrow the result set server-side so that
    pagination counts remain accurate.
    """
    order = SORT_COLS.get(sort, "detections DESC")
    where, params = period_clause(period, date_from=date_from, date_to=date_to)

    # Build any additional WHERE conditions from conservation filters.
    conservation_clauses: list[str] = []
    if bocc:
        conservation_clauses.append("si.uk_bocc = :bocc")
        params["bocc"] = bocc
    if status:
        conservation_clauses.append("si.species_status = :status")
        params["status"] = status
    if group:
        conservation_clauses.append("si.group_name = :group_name")
        params["group_name"] = group
    if conservation_clauses:
        where = f"{where} AND {' AND '.join(conservation_clauses)}"

    rows = (
        await db.execute(
            text(f"""
            SELECT
                d.species,
                COUNT(*)          AS detections,
                AVG(d.confidence) AS avg_confidence,
                MAX(d.confidence) AS peak_confidence,
                MIN(d.timestamp)  AS first_detected,
                MAX(d.timestamp)  AS last_detected,
                si.scientific_name,
                si.group_name,
                si.uk_bocc,
                si.species_status,
                si.bto_2letter_code,
                si.bto_5letter_code
            FROM detections d
            LEFT JOIN species_info si ON si.name = d.bto_name
            WHERE {where}
            GROUP BY d.species, si.scientific_name, si.group_name, si.uk_bocc,
                     si.species_status, si.bto_2letter_code, si.bto_5letter_code
            ORDER BY {order}
            LIMIT :limit OFFSET :offset
            """),
            {**params, "limit": limit, "offset": offset},
        )
    ).mappings().all()

    # Count must also join species_info when conservation filters are active.
    total_row = (
        await db.execute(
            text(f"""
            SELECT COUNT(DISTINCT d.species) AS n
            FROM detections d
            LEFT JOIN species_info si ON si.name = d.bto_name
            WHERE {where}
            """),
            params,
        )
    ).mappings().one()

    return {
        "total": total_row["n"],
        "species": [
            {
                "species":          r["species"],
                "detections":       r["detections"],
                "avg_confidence":   round(r["avg_confidence"] or 0, 4),
                "peak_confidence":  round(r["peak_confidence"] or 0, 4),
                "first_detected":   to_utc_iso(r["first_detected"]),
                "last_detected":    to_utc_iso(r["last_detected"]),
                "scientific_name":  r["scientific_name"],
                "group_name":       r["group_name"],
                "uk_bocc":          r["uk_bocc"],
                "species_status":   r["species_status"],
                "bto_2letter_code": r["bto_2letter_code"],
                "bto_5letter_code": r["bto_5letter_code"],
            }
            for r in rows
        ],
    }


@router.get("/api/v1/species/{name}")
async def species_detail(
    name: str,
    db: AsyncConnection = Depends(get_db),
):
    """Aggregate stats + species_info metadata for a single species."""
    rows = (
        await db.execute(
            text("""
            SELECT
                d.species,
                COUNT(*)          AS detections,
                AVG(d.confidence) AS avg_confidence,
                MAX(d.confidence) AS peak_confidence,
                MIN(d.timestamp)  AS first_detected,
                MAX(d.timestamp)  AS last_detected,
                si.scientific_name,
                si.group_name,
                si.uk_bocc,
                si.species_status,
                si.bto_2letter_code,
                si.bto_5letter_code
            FROM detections d
            LEFT JOIN species_info si ON si.name = d.bto_name
            WHERE d.species = :name
            GROUP BY d.species, si.scientific_name, si.group_name, si.uk_bocc,
                     si.species_status, si.bto_2letter_code, si.bto_5letter_code
            """),
            {"name": name},
        )
    ).mappings().all()
    if not rows:
        raise HTTPException(status_code=404, detail="Species not found")
    r = rows[0]
    return {
        "species":          r["species"],
        "detections":       r["detections"],
        "avg_confidence":   round(r["avg_confidence"] or 0, 4),
        "peak_confidence":  round(r["peak_confidence"] or 0, 4),
        "first_detected":   to_utc_iso(r["first_detected"]),
        "last_detected":    to_utc_iso(r["last_detected"]),
        "scientific_name":  r["scientific_name"],
        "group_name":       r["group_name"],
        "uk_bocc":          r["uk_bocc"],
        "species_status":   r["species_status"],
        "bto_2letter_code": r["bto_2letter_code"],
        "bto_5letter_code": r["bto_5letter_code"],
    }


@router.get("/api/v1/species/{name}/detections")
async def species_detection_list(
    name: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncConnection = Depends(get_db),
):
    """Paginated detection recordings for a single species, newest first.

    Joins species_info so the response includes uk_bocc / species_status for
    use in the frontend notable-species highlighting logic.
    """
    rows = (
        await db.execute(
            text("""
            SELECT
                d.id, d.timestamp, d.species, d.confidence, d.clip_path, d.bto_name,
                d.model,
                d.primary_confidence, d.cross_validated,
                d.cv_secondary_model, d.cv_species, d.cv_bto_name,
                d.cv_confidence, d.cv_agree, d.flagged,
                si.scientific_name, si.group_name, si.uk_bocc, si.species_status,
                si.bto_2letter_code, si.bto_5letter_code
            FROM detections d
            LEFT JOIN species_info si ON si.name = d.bto_name
            WHERE d.species = :name
            ORDER BY d.id DESC
            LIMIT :limit OFFSET :offset
            """),
            {"name": name, "limit": limit, "offset": offset},
        )
    ).mappings().all()

    total_row = (
        await db.execute(
            text("SELECT COUNT(*) AS n FROM detections WHERE species = :name"),
            {"name": name},
        )
    ).mappings().one()

    result = []
    for r in rows:
        d = _normalise_bools(dict(r))
        d["filename"] = Path(d["clip_path"]).name if d.get("clip_path") else None
        del d["clip_path"]
        d["timestamp"] = to_utc_iso(d.get("timestamp"))
        result.append(d)

    return {"total": total_row["n"], "detections": result}
