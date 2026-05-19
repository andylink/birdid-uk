"""
Per-species statistics endpoints and AviCommons image cache.

Images are downloaded on first request, stored in data/species_images/, and
served directly from disk on subsequent requests. A .none sentinel file is
written when no image is available so failed lookups aren't retried too often.
"""

from __future__ import annotations

import asyncio
import json
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
from dashboard.utils import normalise_bools, period_clause, to_utc_iso

router = APIRouter()

# ── Image cache ────────────────────────────────────────────────────────────────

IMAGE_DIR: Path = DETECTIONS_DIR.parent / "species_images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_TTL_DAYS = 30     # re-fetch cached images after this many days
NEGATIVE_TTL_DAYS = 1   # retry failed lookups after this many days

_UA = "bird-detector/1.0 (local garden monitor; contact via github)"

# Cap concurrent outbound image fetches to avoid hammering the CDN.
_IMG_SEM = asyncio.Semaphore(4)

# ── Wikipedia summary cache ────────────────────────────────────────────────────

SUMMARY_DIR: Path = IMAGE_DIR.parent / "species_summaries"
SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

SUMMARY_TTL_DAYS      = 90   # re-fetch cached summaries after this many days
SUMMARY_NEG_TTL_DAYS  = 7    # retry failed lookups after this many days


def _summary_path(species: str) -> Path:
    return SUMMARY_DIR / f"{_slug(species)}.json"


def _summary_neg_path(species: str) -> Path:
    return SUMMARY_DIR / f"{_slug(species)}.none"

# Allowed sort keys mapped to the SQL ORDER BY expression they produce.
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
    """Convert a species name to a safe filename component."""
    return re.sub(r"[^a-z0-9]+", "_", species.lower()).strip("_")


def _img_path(species: str) -> Path:
    return IMAGE_DIR / f"{_slug(species)}.jpg"


def _neg_path(species: str) -> Path:
    """Sentinel file written when no image exists for a species."""
    return IMAGE_DIR / f"{_slug(species)}.none"


def _age_days(path: Path) -> float:
    """Return how many days ago a file was last modified."""
    return (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).days


async def _fetch_image_bytes(url: str) -> bytes | None:
    """Download image bytes from a URL. Returns None on any non-200 response."""
    async with _IMG_SEM:
        async with httpx.AsyncClient(headers={"User-Agent": _UA}, timeout=15) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return r.content
            return None


def _normalise_bools(d: dict) -> dict:
    """Coerce cross-validation boolean fields to integers.

    SQLite returns 0/1; PostgreSQL returns Python bools. The frontend uses
    strict equality (=== 1), so we normalise to integers for both backends.
    """
    for key in ("cross_validated", "cv_agree"):
        if key in d and isinstance(d[key], bool):
            d[key] = int(d[key])
    return d


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/v1/species/image")
async def species_image(
    name: str = Query(..., description="BTO common name or eBird/BirdNET common name"),
    db: AsyncConnection = Depends(get_db),
):
    """Serve a cached species photo sourced from AviCommons.

    Accepts either a BTO name (e.g. "Robin") or an eBird/BirdNET name (e.g.
    "European Robin"). When the direct lookup in species_info fails, falls back
    to resolving the name via the bto_name column in detections.

    Checks disk cache first. If the image is missing or stale, fetches from
    AviCommons using the URL stored in species_info. A .none sentinel prevents
    repeated failed lookups within NEGATIVE_TTL_DAYS.
    """
    img_path = _img_path(name)
    neg_path = _neg_path(name)

    # Serve from cache if fresh
    if img_path.exists() and _age_days(img_path) < IMAGE_TTL_DAYS:
        return FileResponse(str(img_path), media_type="image/jpeg")

    # Skip retry if we recently failed to find an image
    if neg_path.exists() and _age_days(neg_path) < NEGATIVE_TTL_DAYS:
        raise HTTPException(status_code=404, detail="No image available")

    # Look up the AviCommons URL from species_info.
    # Try the supplied name first (BTO name), then fall back to resolving the
    # eBird/BirdNET name via the bto_name mapping stored in detections.
    rows = (
        await db.execute(
            text("""
                SELECT si.avicommons_image_url
                FROM species_info si
                WHERE si.name = :name
                UNION
                SELECT si2.avicommons_image_url
                FROM species_info si2
                WHERE si2.name = (
                    SELECT d.bto_name
                    FROM detections d
                    WHERE d.species = :name AND d.bto_name IS NOT NULL
                    LIMIT 1
                )
                LIMIT 1
            """),
            {"name": name},
        )
    ).mappings().all()
    avi_url: str | None = rows[0]["avicommons_image_url"] if rows else None

    if not avi_url:
        neg_path.touch()
        raise HTTPException(status_code=404, detail="No image available for this species")

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

    Conservation filters (bocc, status, group) are applied server-side via a
    JOIN on species_info so pagination counts stay accurate.
    """
    order = SORT_COLS.get(sort, "detections DESC")
    where, params = period_clause(period, date_from=date_from, date_to=date_to)

    # Append any optional conservation filters to the WHERE clause.
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
                d.bto_name,
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
                si.bto_5letter_code,
                si.ebird_code,
                si.avicommons_image_by,
                si.avicommons_image_license,
                si.british_list_status,
                si.population_estimate
            FROM detections d
            LEFT JOIN species_info si ON si.name = d.bto_name
            WHERE {where}
            GROUP BY d.species, d.bto_name, si.scientific_name, si.group_name, si.uk_bocc,
                     si.species_status, si.bto_2letter_code, si.bto_5letter_code,
                     si.ebird_code, si.avicommons_image_by, si.avicommons_image_license,
                     si.british_list_status, si.population_estimate
            ORDER BY {order}
            LIMIT :limit OFFSET :offset
            """),
            {**params, "limit": limit, "offset": offset},
        )
    ).mappings().all()

    # Use the same WHERE (including conservation filters) for the total count.
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
                "species":                   r["species"],
                "bto_name":                  r["bto_name"],
                "detections":                r["detections"],
                "avg_confidence":            round(r["avg_confidence"] or 0, 4),
                "peak_confidence":           round(r["peak_confidence"] or 0, 4),
                "first_detected":            to_utc_iso(r["first_detected"]),
                "last_detected":             to_utc_iso(r["last_detected"]),
                "scientific_name":           r["scientific_name"],
                "group_name":                r["group_name"],
                "uk_bocc":                   r["uk_bocc"],
                "species_status":            r["species_status"],
                "bto_2letter_code":          r["bto_2letter_code"],
                "bto_5letter_code":          r["bto_5letter_code"],
                "avicommons_image_by":       r["avicommons_image_by"],
                "avicommons_image_license":  r["avicommons_image_license"],
                "british_list_status":       r["british_list_status"],
                "population_estimate":       r["population_estimate"],
                "avicommons_attribution_url": (
                    f"https://avicommons.org/species/{r['ebird_code']}"
                    if r["ebird_code"] else None
                ),
            }
            for r in rows
        ],
    }


@router.get("/api/v1/species/{name}")
async def species_detail(
    name: str,
    db: AsyncConnection = Depends(get_db),
):
    """Aggregate detection stats and species_info metadata for a single species."""
    rows = (
        await db.execute(
            text("""
            SELECT
                d.species,
                d.bto_name,
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
                si.bto_5letter_code,
                si.ebird_code,
                si.avicommons_image_by,
                si.avicommons_image_license,
                si.british_list_status,
                si.population_estimate
            FROM detections d
            LEFT JOIN species_info si ON si.name = d.bto_name
            WHERE d.species = :name
            GROUP BY d.species, d.bto_name, si.scientific_name, si.group_name, si.uk_bocc,
                     si.species_status, si.bto_2letter_code, si.bto_5letter_code,
                     si.ebird_code, si.avicommons_image_by, si.avicommons_image_license,
                     si.british_list_status, si.population_estimate
            """),
            {"name": name},
        )
    ).mappings().all()
    if not rows:
        raise HTTPException(status_code=404, detail="Species not found")
    r = rows[0]
    return {
        "species":                   r["species"],
        "bto_name":                  r["bto_name"],
        "detections":                r["detections"],
        "avg_confidence":            round(r["avg_confidence"] or 0, 4),
        "peak_confidence":           round(r["peak_confidence"] or 0, 4),
        "first_detected":            to_utc_iso(r["first_detected"]),
        "last_detected":             to_utc_iso(r["last_detected"]),
        "scientific_name":           r["scientific_name"],
        "group_name":                r["group_name"],
        "uk_bocc":                   r["uk_bocc"],
        "species_status":            r["species_status"],
        "bto_2letter_code":          r["bto_2letter_code"],
        "bto_5letter_code":          r["bto_5letter_code"],
        "avicommons_image_by":       r["avicommons_image_by"],
        "avicommons_image_license":  r["avicommons_image_license"],
        "british_list_status":       r["british_list_status"],
        "population_estimate":       r["population_estimate"],
        "avicommons_attribution_url": (
            f"https://avicommons.org/species/{r['ebird_code']}"
            if r["ebird_code"] else None
        ),
    }


@router.get("/api/v1/species/{name}/summary")
async def species_summary(
    name: str,
    db: AsyncConnection = Depends(get_db),
):
    """Return a short Wikipedia description for a species, with disk caching.

    Resolves the scientific name from species_info (with eBird→BTO fallback),
    fetches the Wikipedia page summary, and caches the result as a JSON file.
    Falls back to an OpenSearch query if the scientific-name title isn't found.
    """
    cache = _summary_path(name)
    neg   = _summary_neg_path(name)

    # Serve from cache if fresh
    if cache.exists() and _age_days(cache) < SUMMARY_TTL_DAYS:
        return json.loads(cache.read_text())

    # Honour the negative-cache TTL to avoid repeated failed fetches
    if neg.exists() and _age_days(neg) < SUMMARY_NEG_TTL_DAYS:
        raise HTTPException(status_code=404, detail="No summary available")

    # Resolve scientific name (BTO direct or via eBird→BTO mapping)
    rows = (
        await db.execute(
            text("""
                SELECT si.scientific_name
                FROM species_info si
                WHERE si.name = :name
                UNION
                SELECT si2.scientific_name
                FROM species_info si2
                WHERE si2.name = (
                    SELECT d.bto_name FROM detections d
                    WHERE d.species = :name AND d.bto_name IS NOT NULL
                    LIMIT 1
                )
                LIMIT 1
            """),
            {"name": name},
        )
    ).mappings().all()

    sci_name: str | None = rows[0]["scientific_name"] if rows else None
    if not sci_name:
        neg.touch()
        raise HTTPException(status_code=404, detail="No scientific name found")

    # Fetch from Wikipedia
    title = sci_name.replace(" ", "_")
    try:
        async with httpx.AsyncClient(headers={"User-Agent": _UA}, timeout=10) as client:
            r = await client.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
            )
            if r.status_code == 404:
                # Try OpenSearch to locate the canonical article title
                os_r = await client.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={
                        "action": "opensearch",
                        "search": sci_name,
                        "limit": "1",
                        "format": "json",
                    },
                )
                candidates = os_r.json()[1] if os_r.status_code == 200 else []
                if not candidates:
                    neg.touch()
                    raise HTTPException(status_code=404, detail="No Wikipedia article found")
                r = await client.get(
                    f"https://en.wikipedia.org/api/rest_v1/page/summary/{candidates[0].replace(' ', '_')}"
                )
            if r.status_code != 200:
                neg.touch()
                raise HTTPException(status_code=404, detail="Wikipedia fetch failed")

            data = r.json()
    except HTTPException:
        raise
    except Exception:
        neg.touch()
        raise HTTPException(status_code=503, detail="Wikipedia request failed")

    extract: str = data.get("extract", "").strip()
    if not extract:
        neg.touch()
        raise HTTPException(status_code=404, detail="No extract in Wikipedia response")

    result = {
        "extract":       extract,
        "wikipedia_url": data.get("content_urls", {}).get("desktop", {}).get("page"),
    }
    cache.write_text(json.dumps(result))
    neg.unlink(missing_ok=True)
    return result


@router.get("/api/v1/species/{name}/detections")
async def species_detection_list(
    name: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    verification_status: Optional[str] = None,
    db: AsyncConnection = Depends(get_db),
):
    """Paginated list of individual recordings for a single species, newest first.

    Includes uk_bocc and species_status so the frontend can apply
    notable-species highlighting without a separate lookup.
    Pass verification_status=unverified|auto|cv|verified to filter by review state.
    """
    # Build an optional extra WHERE clause for the verification filter.
    vs_clause = "AND COALESCE(d.verification_status, 'unverified') = :vs" if verification_status else ""
    params: dict = {"name": name, "limit": limit, "offset": offset}
    if verification_status:
        params["vs"] = verification_status

    rows = (
        await db.execute(
            text(f"""
            SELECT
                d.id, d.timestamp, d.species, d.confidence, d.clip_path, d.bto_name,
                d.model,
                d.primary_confidence, d.cross_validated,
                d.cv_secondary_model, d.cv_species, d.cv_bto_name,
                d.cv_confidence, d.cv_agree,
                COALESCE(d.verification_status, 'unverified') AS verification_status,
                si.scientific_name, si.group_name, si.uk_bocc, si.species_status,
                si.bto_2letter_code, si.bto_5letter_code
            FROM detections d
            LEFT JOIN species_info si ON si.name = d.bto_name
            WHERE d.species = :name {vs_clause}
            ORDER BY d.id DESC
            LIMIT :limit OFFSET :offset
            """),
            params,
        )
    ).mappings().all()

    count_params: dict = {"name": name}
    if verification_status:
        count_params["vs"] = verification_status
    total_row = (
        await db.execute(
            text(
                f"SELECT COUNT(*) AS n FROM detections "
                f"WHERE species = :name "
                f"{'AND COALESCE(verification_status, \'unverified\') = :vs' if verification_status else ''}"
            ),
            count_params,
        )
    ).mappings().one()

    result = []
    for r in rows:
        d = normalise_bools(dict(r))
        d["filename"] = Path(d["clip_path"]).name if d.get("clip_path") else None
        del d["clip_path"]
        d["timestamp"] = to_utc_iso(d.get("timestamp"))
        result.append(d)

    return {"total": total_row["n"], "detections": result}
