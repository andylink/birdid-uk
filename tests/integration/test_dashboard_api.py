"""
Integration tests for FastAPI dashboard routes.

A temp SQLite database is created per test with the full schema and a few
seeded rows. The FastAPI `get_db` dependency is overridden via
`app.dependency_overrides` so every route uses the temp DB.

`httpx.AsyncClient` sends requests directly to the ASGI app without starting
a network server. The lifespan handler (_ensure_species_info) is not triggered
by httpx, so species_info is seeded manually in the fixture.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncGenerator

import aiosqlite
import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from dashboard.app import app
from dashboard.database import get_db

# ── Schema helpers ────────────────────────────────────────────────────────────

_DDL_DETECTIONS = """
CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    species TEXT NOT NULL,
    bto_name TEXT,
    confidence REAL NOT NULL,
    clip_path TEXT,
    model TEXT,
    primary_confidence REAL,
    cross_validated INTEGER,
    cv_secondary_model TEXT,
    cv_species TEXT,
    cv_bto_name TEXT,
    cv_confidence REAL,
    cv_agree INTEGER,
    flagged INTEGER
)
"""

_DDL_SPECIES_INFO = """
CREATE TABLE IF NOT EXISTS species_info (
    name TEXT PRIMARY KEY,
    scientific_name TEXT,
    british_list_status TEXT,
    population_estimate TEXT,
    bto_2letter_code TEXT,
    bto_5letter_code TEXT,
    species_status TEXT,
    uk_bocc TEXT,
    birdfacts_url TEXT,
    international_english_name TEXT,
    group_name TEXT,
    ebird_code TEXT,
    avicommons_image_url TEXT
)
"""

_DDL_DETECTION_RESULTS = """
CREATE TABLE IF NOT EXISTS detection_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detection_id INTEGER NOT NULL,
    species TEXT NOT NULL,
    confidence REAL NOT NULL
)
"""


async def _setup_db(db_path: Path) -> None:
    """Create schema and seed test rows."""
    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.execute(_DDL_DETECTIONS)
        await conn.execute(_DDL_SPECIES_INFO)
        await conn.execute(_DDL_DETECTION_RESULTS)

        await conn.executemany(
            "INSERT INTO species_info (name, scientific_name, uk_bocc, group_name, species_status) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                ("Robin",     "Erithacus rubecula", "Green", "Chats",   "Common"),
                ("Blackbird", "Turdus merula",      "Green", "Thrushes","Common"),
                ("Curlew",    "Numenius arquata",   "Red",   "Waders",  "Scarce"),
            ],
        )

        # Three detections at different hours on the same day
        await conn.executemany(
            "INSERT INTO detections (timestamp, species, bto_name, confidence, clip_path, model) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("2026-05-13 08:00:00", "European Robin",   "Robin",     0.87, "20260513_080000_robin.flac",     "birdnet"),
                ("2026-05-13 09:00:00", "Common Blackbird", "Blackbird", 0.91, "20260513_090000_blackbird.flac", "birdnet"),
                ("2026-05-13 10:00:00", "Eurasian Curlew",  "Curlew",    0.78, "20260513_100000_curlew.flac",    "birdnet"),
            ],
        )
        await conn.commit()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def test_db(tmp_path) -> Path:
    """Populate a temp SQLite DB and return its path."""
    db_path = tmp_path / "api_test.db"
    await _setup_db(db_path)
    return db_path


@pytest.fixture
def api_client(test_db):
    """Return an httpx.AsyncClient wired to the FastAPI app using the temp DB."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{test_db}")

    async def _override_get_db() -> AsyncGenerator:
        async with engine.connect() as conn:
            yield conn

    app.dependency_overrides[get_db] = _override_get_db
    yield httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    app.dependency_overrides.clear()


# ── /healthz ──────────────────────────────────────────────────────────────────

async def test_healthz(api_client):
    async with api_client as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ── /api/v1/config ────────────────────────────────────────────────────────────

async def test_get_config(api_client):
    async with api_client as client:
        resp = await client.get("/api/v1/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "timezone" in data
    assert "station_name" in data


# ── /api/v1/detections ────────────────────────────────────────────────────────

async def test_list_detections_returns_all(api_client):
    async with api_client as client:
        resp = await client.get("/api/v1/detections")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


async def test_list_detections_newest_first(api_client):
    """Detections should be sorted by id DESC (most recent first)."""
    async with api_client as client:
        resp = await client.get("/api/v1/detections")
    data = resp.json()
    assert data[0]["species"] == "Eurasian Curlew"
    assert data[-1]["species"] == "European Robin"


async def test_list_detections_species_filter(api_client):
    async with api_client as client:
        resp = await client.get("/api/v1/detections?species=European+Robin")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["species"] == "European Robin"


async def test_list_detections_limit(api_client):
    async with api_client as client:
        resp = await client.get("/api/v1/detections?limit=2")
    assert len(resp.json()) == 2


async def test_list_detections_offset(api_client):
    async with api_client as client:
        resp = await client.get("/api/v1/detections?limit=10&offset=2")
    assert len(resp.json()) == 1   # 3 total, 2 skipped


async def test_list_detections_has_filename_not_clip_path(api_client):
    """Response should expose 'filename' derived from clip_path, not the raw path."""
    async with api_client as client:
        resp = await client.get("/api/v1/detections")
    row = resp.json()[0]
    assert "filename" in row
    assert "clip_path" not in row


async def test_list_detections_timestamp_iso8601(api_client):
    """Returned timestamps should carry a UTC offset (+00:00)."""
    async with api_client as client:
        resp = await client.get("/api/v1/detections")
    for row in resp.json():
        ts = row["timestamp"]
        assert ts.endswith("+00:00"), f"Timestamp missing UTC offset: {ts}"


async def test_list_detections_flagged_filter(api_client, test_db):
    """?flagged=true should return only detections with flagged=1."""
    async with aiosqlite.connect(str(test_db)) as conn:
        await conn.execute(
            "INSERT INTO detections (timestamp, species, confidence, clip_path, flagged) "
            "VALUES ('2026-05-13 11:00:00', 'Song Thrush', 0.6, 'x.flac', 1)"
        )
        await conn.commit()

    async with api_client as client:
        resp = await client.get("/api/v1/detections?flagged=true")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["species"] == "Song Thrush"


# ── /api/v1/analytics/summary ─────────────────────────────────────────────────

async def test_analytics_summary_all(api_client):
    async with api_client as client:
        resp = await client.get("/api/v1/analytics/summary?period=all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_detections"] == 3
    assert data["unique_species"] == 3
    assert "avg_confidence" in data
    assert "most_common_species" in data


async def test_analytics_summary_empty_db(api_client, test_db):
    """Summary on an empty database should return zeros rather than errors."""
    async with aiosqlite.connect(str(test_db)) as conn:
        await conn.execute("DELETE FROM detections")
        await conn.commit()

    async with api_client as client:
        resp = await client.get("/api/v1/analytics/summary?period=all")
    data = resp.json()
    assert data["total_detections"] == 0
    assert data["unique_species"] == 0


# ── /api/v1/analytics/top-species ────────────────────────────────────────────

async def test_top_species(api_client):
    async with api_client as client:
        resp = await client.get("/api/v1/analytics/top-species?period=all&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    for row in data:
        assert "species" in row
        assert "count" in row


async def test_top_species_limit_respected(api_client):
    async with api_client as client:
        resp = await client.get("/api/v1/analytics/top-species?period=all&limit=1")
    assert len(resp.json()) == 1


# ── /api/v1/analytics/by-hour ─────────────────────────────────────────────────

async def test_by_hour_all_period(api_client):
    async with api_client as client:
        resp = await client.get("/api/v1/analytics/by-hour")
    assert resp.status_code == 200
    data = resp.json()
    assert "labels" in data
    assert "data" in data
    assert len(data["labels"]) == 24
    assert len(data["data"]) == 24
    assert sum(data["data"]) == 3


# ── /api/v1/analytics/bocc-breakdown ─────────────────────────────────────────

async def test_bocc_breakdown(api_client):
    async with api_client as client:
        resp = await client.get("/api/v1/analytics/bocc-breakdown?period=all")
    assert resp.status_code == 200
    data = resp.json()
    bocc_values = {row["bocc"] for row in data}
    # Robin and Blackbird are Green; Curlew is Red
    assert "Green" in bocc_values or "Red" in bocc_values


# ── /api/v1/analytics/group-breakdown ────────────────────────────────────────

async def test_group_breakdown(api_client):
    async with api_client as client:
        resp = await client.get("/api/v1/analytics/group-breakdown?period=all")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) > 0
    for row in data:
        assert "group_name" in row
        assert "detection_count" in row
        assert "species_count" in row


# ── /api/v1/analytics/new-species ────────────────────────────────────────────

async def test_new_species_timeline(api_client):
    async with api_client as client:
        resp = await client.get("/api/v1/analytics/new-species?period=all")
    assert resp.status_code == 200
    data = resp.json()
    total_new = sum(row["count"] for row in data)
    assert total_new == 3   # all 3 species appear for the first time on the same day


# ── /api/v1/analytics/species/daily ──────────────────────────────────────────

async def test_species_daily(api_client):
    async with api_client as client:
        resp = await client.get("/api/v1/analytics/species/daily?date=2026-05-13")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    for row in data:
        assert "species" in row
        assert "hourly_counts" in row
        assert len(row["hourly_counts"]) == 24


async def test_species_daily_empty_day(api_client):
    async with api_client as client:
        resp = await client.get("/api/v1/analytics/species/daily?date=2000-01-01")
    assert resp.status_code == 200
    assert resp.json() == []


# ── /api/v1/analytics/bocc-trend ─────────────────────────────────────────────

async def test_bocc_trend(api_client):
    async with api_client as client:
        resp = await client.get("/api/v1/analytics/bocc-trend?period=all")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for row in data:
        assert "day" in row
        assert "bocc" in row
        assert "detection_count" in row
