"""
dashboard/app.py — FastAPI application factory for the bird-detector dashboard.

Run with:
    uvicorn dashboard.app:app --host 0.0.0.0 --port 8080 --reload
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

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
from dashboard.stream import detection_generator
from dashboard.config import DB_TYPE, TIMEZONE, STATION_NAME
from dashboard.database import get_engine, startup_db, shutdown_db

_JSON_PATH = Path(__file__).parent.parent / "uk_species_filter.json"

# Full 13-column schema — matches root database.py's _species_info table.
# The two extra columns (ebird_code, avicommons_image_url) were previously
# missing from the dashboard DDL but are already queried by routes/species.py.
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
    avicommons_image_url        TEXT
)
"""


async def _ensure_species_info() -> None:
    """Create and seed species_info if needed (SQLite only).

    When PostgreSQL is configured, the detector's database.py owns the schema
    and has already seeded species_info before the dashboard starts, so this
    function is a no-op on that path.
    """
    if DB_TYPE == "postgresql":
        return

    if not _JSON_PATH.exists():
        return

    async with get_engine().begin() as conn:
        await conn.execute(text(_CREATE_SPECIES_INFO))

        row = (await conn.execute(text("SELECT COUNT(*) FROM species_info"))).one()
        if row[0]:
            return

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


# ── SSE stream ────────────────────────────────────────────────────────────────
@app.get("/stream/detections")
async def stream_detections():
    """Server-sent events: push each new detection as a named 'detection' event."""
    return EventSourceResponse(detection_generator())


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ── Client config ─────────────────────────────────────────────────────────────
@app.get("/api/v1/config")
async def get_config():
    """Return public runtime config consumed by the frontend (e.g. timezone)."""
    return {"timezone": TIMEZONE, "station_name": STATION_NAME}


# ── Static frontend (production build) ────────────────────────────────────────
_DIST = Path(__file__).parent / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
