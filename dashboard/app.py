"""
FastAPI application factory for the bird-detector dashboard.

Run with:
    uvicorn dashboard.app:app --host 0.0.0.0 --port 8080 --reload
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3 as _sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

_log = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sse_starlette.sse import EventSourceResponse

from dashboard.routes.analytics import router as analytics_router
from dashboard.routes.detections import router as detections_router
from dashboard.routes.media import router as media_router
from dashboard.routes.species import router as species_router
from dashboard.routes.sun import router as sun_router
from dashboard.routes.weather import router as weather_router
from dashboard.routes.auth import router as auth_router
from dashboard.routes.admin import router as admin_router
from dashboard.stream import detection_generator
from dashboard.config import DB_PATH, DB_TYPE, TIMEZONE, STATION_NAME
from dashboard.database import get_engine, startup_db, shutdown_db

_JSON_PATH = Path(__file__).parent.parent / "filters" / "uk_species_filter.json"

# Full schema — must match the root database.py _species_info table.
_CREATE_SPECIES_INFO = """
CREATE TABLE IF NOT EXISTS species_info (
    name                        TEXT PRIMARY KEY,
    scientific_name             TEXT,
    british_list_status         TEXT,
    population_estimate         TEXT,
    bto_2letter_code            TEXT,
    bto_5letter_code            TEXT,
    species_status              TEXT,
    uk_bocc                     TEXT,
    birdfacts_url               TEXT,
    international_english_name  TEXT,
    group_name                  TEXT,
    ebird_code                  TEXT,
    avicommons_image_url        TEXT,
    avicommons_image_by         TEXT,
    avicommons_image_license    TEXT
)
"""


async def _ensure_species_info() -> None:
    """Create and populate the species_info table from the JSON filter file (SQLite only).

    On PostgreSQL, the detector's own database.py owns this table and seeds it
    before the dashboard starts, so this function does nothing on that path.
    """
    if DB_TYPE == "postgresql":
        return

    if not _JSON_PATH.exists():
        return

    async with get_engine().begin() as conn:
        await conn.execute(text(_CREATE_SPECIES_INFO))

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

        # Add any species that don't exist yet; never overwrite existing rows.
        await conn.execute(
            text(
                "INSERT OR IGNORE INTO species_info "
                "(name, scientific_name, british_list_status, population_estimate, "
                " bto_2letter_code, bto_5letter_code, species_status, uk_bocc, "
                " birdfacts_url, international_english_name, group_name, "
                " ebird_code, avicommons_image_url, "
                " avicommons_image_by, avicommons_image_license) "
                "VALUES (:name, :scientific_name, :british_list_status, "
                " :population_estimate, :bto_2letter_code, :bto_5letter_code, "
                " :species_status, :uk_bocc, :birdfacts_url, "
                " :international_english_name, :group_name, "
                " :ebird_code, :avicommons_image_url, "
                " :avicommons_image_by, :avicommons_image_license)"
            ),
            rows,
        )

    # Backfill attribution for rows that are missing it using raw sqlite3,
    # which we know is reliable (bypasses SQLAlchemy async executemany quirks).
    attr_params = [
        (r["avicommons_image_by"], r["avicommons_image_license"], r["name"])
        for r in rows
        if r["avicommons_image_by"]
    ]
    if attr_params:
        def _backfill(db_path: Path, params: list) -> int:
            with _sqlite3.connect(db_path) as raw:
                cur = raw.executemany(
                    "UPDATE species_info SET avicommons_image_by=?, avicommons_image_license=? "
                    "WHERE name=? AND avicommons_image_by IS NULL",
                    params,
                )
                return cur.rowcount

        updated = await asyncio.to_thread(_backfill, DB_PATH, attr_params)
        _log.info("_ensure_species_info: backfilled attribution for %d species", updated)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    await startup_db()
    await _ensure_species_info()
    yield
    await shutdown_db()


app = FastAPI(title="Bird Detector Dashboard", docs_url="/api/docs", lifespan=_lifespan)

# ── API routers ────────────────────────────────────────────────────────────────
app.include_router(detections_router)
app.include_router(analytics_router)
app.include_router(media_router)
app.include_router(species_router)
app.include_router(sun_router)
app.include_router(weather_router)
app.include_router(auth_router)
app.include_router(admin_router)


# ── SSE stream ────────────────────────────────────────────────────────────────
@app.get("/stream/detections")
async def stream_detections():
    """Push new detections to the browser as Server-Sent Events."""
    return EventSourceResponse(detection_generator())


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ── Client config ─────────────────────────────────────────────────────────────
@app.get("/api/v1/config")
async def get_config():
    """Return public runtime settings consumed by the frontend (timezone, station name)."""
    return {"timezone": TIMEZONE, "station_name": STATION_NAME}


# ── Static frontend (production build) ────────────────────────────────────────
_DIST = Path(__file__).parent / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
