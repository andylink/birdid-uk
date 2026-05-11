"""
dashboard/app.py — FastAPI application factory for the bird-detector dashboard.

Run with:
    uvicorn dashboard.app:app --host 0.0.0.0 --port 8080 --reload
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from dashboard.routes.analytics import router as analytics_router
from dashboard.routes.detections import router as detections_router
from dashboard.routes.media import router as media_router
from dashboard.routes.species import router as species_router
from dashboard.routes.sun import router as sun_router
from dashboard.stream import detection_generator
from dashboard.config import DB_PATH, TIMEZONE, STATION_NAME

_JSON_PATH = Path(__file__).parent.parent / "species_bto_FINAL_filtered.json"

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
    group_name                  TEXT
)
"""


async def _ensure_species_info() -> None:
    """Create species_info if it doesn't exist and seed it from the JSON if empty."""
    if not _JSON_PATH.exists():
        return

    async with aiosqlite.connect(str(DB_PATH)) as conn:
        await conn.execute(_CREATE_SPECIES_INFO)
        await conn.commit()

        (count,) = await (await conn.execute("SELECT COUNT(*) FROM species_info")).fetchone()
        if count:
            return

        entries = json.loads(_JSON_PATH.read_text(encoding="utf-8"))
        rows = [
            (
                e["name"],
                e.get("scientific_name"),
                e.get("british_list_status"),
                e.get("population_estimate"),
                e.get("bto_2letter_code") or None,
                e.get("bto_5letter_code") or None,
                e.get("species_status"),
                e.get("uk_bocc"),
                e.get("birdfacts_url"),
                e.get("international_english_name"),
                e.get("group_name"),
            )
            for e in entries
            if e.get("name")
        ]
        await conn.executemany(
            "INSERT OR REPLACE INTO species_info "
            "(name, scientific_name, british_list_status, population_estimate, "
            " bto_2letter_code, bto_5letter_code, species_status, uk_bocc, "
            " birdfacts_url, international_english_name, group_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        await conn.commit()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    await _ensure_species_info()
    yield


app = FastAPI(title="Bird Detector Dashboard", docs_url="/api/docs", lifespan=_lifespan)

# ── API routers ────────────────────────────────────────────────────────────────
app.include_router(detections_router)
app.include_router(analytics_router)
app.include_router(media_router)
app.include_router(species_router)
app.include_router(sun_router)


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
