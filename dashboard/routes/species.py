"""
dashboard/routes/species.py — per-species statistics and Wikimedia image cache.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from dashboard.config import DETECTIONS_DIR
from dashboard.database import get_db
from dashboard.utils import period_clause, to_utc_iso

router = APIRouter()

# ── Image cache ────────────────────────────────────────────────────────────────

IMAGE_DIR: Path = DETECTIONS_DIR.parent / "species_images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_TTL_DAYS = 30     # re-fetch positive cache after this many days
NEGATIVE_TTL_DAYS = 1   # retry failed lookups after this many days

_WM_UA = "bird-detector/1.0 (local garden monitor; contact via github)"

# Limit concurrent outbound Wikimedia requests to avoid 429s.
# Images for a full grid of species cards are requested in parallel by the
# browser; this semaphore serialises the actual Wikimedia fetches.
_WM_SEM = asyncio.Semaphore(2)

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


async def _wikimedia_image_bytes(species: str) -> bytes | None:
    """Fetch a species thumbnail from Wikipedia. Returns JPEG bytes or None."""
    async with _WM_SEM:
        async with httpx.AsyncClient(headers={"User-Agent": _WM_UA}, timeout=10) as client:

            async def page_image(title: str) -> str | None:
                for attempt in range(3):
                    r = await client.get(
                        "https://en.wikipedia.org/w/api.php",
                        params={
                            "action": "query", "format": "json",
                            "titles": title, "prop": "pageimages",
                            "pithumbsize": "400", "redirects": "1",
                        },
                    )
                    if r.status_code == 429:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    r.raise_for_status()
                    pages = r.json().get("query", {}).get("pages", {})
                    pid, page = next(iter(pages.items()))
                    if pid == "-1":
                        return None
                    return page.get("thumbnail", {}).get("source")
                return None  # exhausted retries

            # 1. Direct title match
            url = await page_image(species)

            # 2. Fall back to a Wikipedia search
            if not url:
                r2 = await client.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={
                        "action": "query", "format": "json",
                        "list": "search", "srsearch": f"{species} bird", "srlimit": "1",
                    },
                )
                r2.raise_for_status()
                results = r2.json().get("query", {}).get("search", [])
                if results:
                    url = await page_image(results[0]["title"])

            if not url:
                return None

            img = await client.get(url)
            img.raise_for_status()
            return img.content


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/v1/species/image")
async def species_image(name: str = Query(..., description="Common species name")):
    """Serve a cached species photo sourced from Wikimedia Commons.

    Images are stored in data/species_images/ and refreshed every 30 days.
    A .none sentinel file is written on failed lookups (retried daily).
    """
    img_path = _img_path(name)
    neg_path = _neg_path(name)

    # Positive cache hit
    if img_path.exists() and _age_days(img_path) < IMAGE_TTL_DAYS:
        return FileResponse(str(img_path), media_type="image/jpeg")

    # Negative cache — don't hammer Wikimedia for known-missing species
    if neg_path.exists() and _age_days(neg_path) < NEGATIVE_TTL_DAYS:
        raise HTTPException(status_code=404, detail="No image available")

    # Fetch from Wikimedia
    try:
        data = await _wikimedia_image_bytes(name)
    except Exception:
        neg_path.touch()
        raise HTTPException(status_code=404, detail="Image fetch failed")

    if data is None:
        neg_path.touch()
        raise HTTPException(status_code=404, detail="No image on Wikipedia")

    img_path.write_bytes(data)
    # Remove stale negative sentinel if it existed
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
    db: aiosqlite.Connection = Depends(get_db),
):
    """Per-species detection statistics for the given period, sorted as requested."""
    order = SORT_COLS.get(sort, "detections DESC")
    where, params = period_clause(period, date_from=date_from, date_to=date_to)

    rows = await db.execute_fetchall(
        f"""
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
        GROUP BY d.species
        ORDER BY {order}
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )

    total_row = (await db.execute_fetchall(
        f"SELECT COUNT(DISTINCT species) AS n FROM detections WHERE {where}",
        params,
    ))[0]

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
