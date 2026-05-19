"""
Integration tests for database.py.

Each test gets a fresh SQLite database in a temp directory. `database.cfg`
is patched so init_db() and record_detection() use that temp file instead of
the real data/birds.db.

The module-level `database._engine` is reset to None before and after each
test so init_db() always creates a fresh engine.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text

import database
from database import (
    _CV_COLUMNS,
    _detections,
    _migrate_detections_table,
    _migrate_species_info_table,
    init_db,
    record_detection,
    seed_species_info,
)
from config import DatabaseConfig


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def db_cfg(test_cfg, tmp_path):
    """A Config whose db_path points to a temp SQLite file."""
    db_path = tmp_path / "test_birds.db"
    new_paths = dataclasses.replace(test_cfg.paths, db_path=db_path)
    cfg = dataclasses.replace(test_cfg, paths=new_paths)
    return cfg


@pytest.fixture(autouse=True)
def _reset_engine(monkeypatch, db_cfg):
    """Patch database.cfg and reset the engine before/after each test."""
    monkeypatch.setattr(database, "cfg", db_cfg)
    monkeypatch.setattr(database, "_engine", None)
    yield
    # Dispose cleanly to avoid ResourceWarning on the SQLite file
    if database._engine is not None:
        database._engine.dispose()
    monkeypatch.setattr(database, "_engine", None)


# ── init_db ───────────────────────────────────────────────────────────────────

class TestInitDb:
    def test_creates_detections_table(self, db_cfg):
        init_db()
        engine = database._engine
        assert engine is not None
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        table_names = {r[0] for r in rows}
        assert "detections" in table_names

    def test_creates_species_info_table(self, db_cfg):
        init_db()
        engine = database._engine
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        assert "species_info" in {r[0] for r in rows}

    def test_creates_detection_results_table(self, db_cfg):
        init_db()
        engine = database._engine
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        assert "detection_results" in {r[0] for r in rows}

    def test_idempotent_second_call(self, db_cfg):
        """Calling init_db() twice should not raise."""
        init_db()
        init_db()

    def test_cv_columns_present_after_init(self, db_cfg):
        """All cross-validation columns should be present after init_db()."""
        init_db()
        engine = database._engine
        with engine.connect() as conn:
            rows = conn.execute(text("PRAGMA table_info(detections)")).fetchall()
        cols = {r[1] for r in rows}
        for col_name in _CV_COLUMNS:
            assert col_name in cols, f"Missing CV column: {col_name}"

    def test_wal_mode_enabled(self, db_cfg):
        """SQLite WAL journal mode should be enabled for better concurrent access."""
        init_db()
        engine = database._engine
        with engine.connect() as conn:
            mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert mode == "wal"


# ── record_detection ──────────────────────────────────────────────────────────

class TestRecordDetection:
    @pytest.fixture(autouse=True)
    def _init(self):
        init_db()

    def test_inserts_basic_row(self, db_cfg):
        ts = datetime(2026, 5, 13, 10, 0, 0, tzinfo=timezone.utc)
        record_detection(
            ts, "European Robin", 0.85,
            Path("/detections/clip.flac"), [],
            bto_name="Robin", model_name="birdnet",
        )
        engine = database._engine
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM detections")).fetchall()
        assert len(rows) == 1
        row = dict(rows[0]._mapping)
        assert row["species"] == "European Robin"
        assert row["bto_name"] == "Robin"
        assert abs(row["confidence"] - 0.85) < 1e-6
        assert row["model"] == "birdnet"
        assert "clip.flac" in row["clip_path"]

    def test_inserts_secondary_candidates(self, db_cfg):
        ts = datetime(2026, 5, 13, 10, 0, 0, tzinfo=timezone.utc)
        record_detection(
            ts, "European Robin", 0.85,
            Path("/detections/clip.flac"),
            [("Common Blackbird", 0.62), ("Song Thrush", 0.41)],
        )
        engine = database._engine
        with engine.connect() as conn:
            results = conn.execute(text("SELECT * FROM detection_results")).fetchall()
        assert len(results) == 2
        species_names = {r[2] for r in results}
        assert "Common Blackbird" in species_names
        assert "Song Thrush" in species_names

    def test_no_secondary_leaves_detection_results_empty(self, db_cfg):
        ts = datetime(2026, 5, 13, 10, 0, 0, tzinfo=timezone.utc)
        record_detection(ts, "European Robin", 0.85, Path("clip.flac"), [])
        engine = database._engine
        with engine.connect() as conn:
            results = conn.execute(text("SELECT * FROM detection_results")).fetchall()
        assert len(results) == 0

    def test_cv_fields_stored(self, db_cfg):
        """Cross-validation columns should be persisted correctly."""
        ts = datetime(2026, 5, 13, 10, 0, 0, tzinfo=timezone.utc)
        record_detection(
            ts, "European Robin", 0.85,
            Path("clip.flac"), [],
            bto_name="Robin",
            primary_confidence=0.85,
            cross_validated=True,
            cv_secondary_model="perch",
            cv_species="European Robin",
            cv_bto_name="Robin",
            cv_confidence=0.72,
            cv_agree=True,
            flagged=None,
        )
        engine = database._engine
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM detections")).fetchall()
        row = dict(rows[0]._mapping)
        assert row["cross_validated"] == 1
        assert row["cv_secondary_model"] == "perch"
        assert row["cv_agree"] == 1
        assert row["flagged"] is None

    def test_flagged_detection_stored(self, db_cfg):
        ts = datetime(2026, 5, 13, 10, 0, 0, tzinfo=timezone.utc)
        record_detection(
            ts, "European Robin", 0.75,
            Path("clip.flac"), [],
            cross_validated=True,
            cv_agree=False,
            flagged=True,
        )
        engine = database._engine
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT flagged FROM detections")).fetchall()
        assert rows[0][0] == 1

    def test_no_engine_is_noop(self, monkeypatch):
        """record_detection should return silently when the engine is not initialised."""
        monkeypatch.setattr(database, "_engine", None)
        ts = datetime(2026, 5, 13, 10, 0, 0, tzinfo=timezone.utc)
        record_detection(ts, "European Robin", 0.85, Path("clip.flac"), [])

    def test_multiple_detections_auto_increment(self, db_cfg):
        ts = datetime(2026, 5, 13, 10, 0, 0, tzinfo=timezone.utc)
        record_detection(ts, "Robin",     0.8, Path("a.flac"), [])
        record_detection(ts, "Blackbird", 0.9, Path("b.flac"), [])
        engine = database._engine
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id FROM detections ORDER BY id")).fetchall()
        assert rows[0][0] == 1
        assert rows[1][0] == 2


# ── Migration ─────────────────────────────────────────────────────────────────

class TestMigration:
    def test_migration_noop_on_fresh_db(self, db_cfg):
        """_migrate_detections_table should not change columns on a fresh database."""
        init_db()
        engine = database._engine

        with engine.connect() as conn:
            before = {r[1] for r in conn.execute(text("PRAGMA table_info(detections)")).fetchall()}

        _migrate_detections_table(engine)

        with engine.connect() as conn:
            after = {r[1] for r in conn.execute(text("PRAGMA table_info(detections)")).fetchall()}

        assert before == after

    def test_migration_adds_missing_cv_columns(self, db_cfg):
        """Missing CV columns should be added by _migrate_detections_table."""
        init_db()
        engine = database._engine

        # Drop CV columns by recreating the table without them
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE detections_old AS SELECT id, timestamp, species, "
                "bto_name, confidence, clip_path, model FROM detections"
            ))
            conn.execute(text("DROP TABLE detections"))
            conn.execute(text("ALTER TABLE detections_old RENAME TO detections"))

        with engine.connect() as conn:
            existing = {r[1] for r in conn.execute(text("PRAGMA table_info(detections)")).fetchall()}
        for col in _CV_COLUMNS:
            assert col not in existing

        _migrate_detections_table(engine)

        with engine.connect() as conn:
            after = {r[1] for r in conn.execute(text("PRAGMA table_info(detections)")).fetchall()}
        for col in _CV_COLUMNS:
            assert col in after, f"Column {col} still missing after migration"


# ── seed_species_info ─────────────────────────────────────────────────────────

class TestSeedSpeciesInfo:
    def test_seeds_from_json(self, db_cfg, tmp_path):
        """seed_species_info should populate species_info from a JSON file."""
        import json

        json_path = tmp_path / "species.json"
        json_path.write_text(json.dumps([
            {"name": "Robin",     "scientific_name": "Erithacus rubecula", "uk_bocc": "Green", "group_name": "Chats"},
            {"name": "Blackbird", "scientific_name": "Turdus merula",      "uk_bocc": "Green", "group_name": "Thrushes"},
        ]), encoding="utf-8")

        init_db()
        seed_species_info(json_path)

        engine = database._engine
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT name FROM species_info ORDER BY name")).fetchall()
        names = [r[0] for r in rows]
        assert "Blackbird" in names
        assert "Robin" in names

    def test_seed_is_idempotent(self, db_cfg, tmp_path):
        """Calling seed_species_info twice should upsert without creating duplicates."""
        import json

        json_path = tmp_path / "species.json"
        json_path.write_text(json.dumps([
            {"name": "Robin", "uk_bocc": "Green"},
        ]), encoding="utf-8")

        init_db()
        seed_species_info(json_path)
        seed_species_info(json_path)

        engine = database._engine
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM species_info")).scalar()
        assert count == 1

    def test_no_engine_is_noop(self, monkeypatch, tmp_path):
        """seed_species_info should return silently when the engine is not initialised."""
        monkeypatch.setattr(database, "_engine", None)
        import json
        json_path = tmp_path / "species.json"
        json_path.write_text(json.dumps([{"name": "Robin"}]), encoding="utf-8")
        seed_species_info(json_path)
