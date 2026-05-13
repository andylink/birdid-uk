"""
database.py — multi-backend persistence for bird detections.

Supported backends (configured via ``[database]`` in config.toml):
    sqlite      — default, zero config; path taken from ``[paths] db_path``
    postgresql  — standard PostgreSQL (requires ``psycopg2-binary``)

TimescaleDB is an opt-in PostgreSQL extension.  Set ``timescaledb = true``
in ``[database]`` to run ``create_hypertable`` on ``detections.timestamp``
at init time; the backend ``type`` stays ``"postgresql"``.

Schema
------
detections
    id                  INTEGER  PK AUTOINCREMENT
    timestamp           TIMESTAMPTZ  (DATETIME on SQLite)
    species             TEXT     NOT NULL   (primary model common name, e.g. "European Robin")
    bto_name            TEXT               (BTO British name, e.g. "Robin"; NULL if unmapped)
    confidence          FLOAT    NOT NULL   (primary model confidence score)
    clip_path           TEXT
    model               TEXT               (primary inference backend, e.g. "birdnet" or "perch")

    -- Cross-validation columns (all NULL when CV is disabled or not applicable)
    primary_confidence  FLOAT              (raw primary model score; equals confidence when CV not run)
    cross_validated     BOOLEAN            (NULL = CV disabled/not applicable; True/False = CV ran)
    cv_secondary_model  TEXT               (secondary model name, e.g. "perch")
    cv_species          TEXT               (raw label from secondary model's top result)
    cv_bto_name         TEXT               (BTO-resolved name from secondary model)
    cv_confidence       FLOAT              (secondary model's top confidence score)
    cv_agree            BOOLEAN            (True if primary and secondary BTO names matched)
    flagged             BOOLEAN            (True when disagreement + on_disagree = "flag")

detection_results
    id           INTEGER  PK AUTOINCREMENT
    detection_id INTEGER  FK → detections.id  NOT NULL
    species      TEXT     NOT NULL
    confidence   FLOAT    NOT NULL

species_info
    name                     TEXT  PK  (British common name)
    scientific_name          TEXT
    british_list_status      TEXT
    population_estimate      TEXT
    bto_2letter_code         TEXT
    bto_5letter_code         TEXT
    species_status           TEXT  (Common / Scarce / Rare / Very rare)
    uk_bocc                  TEXT  (Red / Amber / Green)
    birdfacts_url            TEXT
    international_english_name TEXT
    group_name               TEXT
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    TIMESTAMP,
    event,
    text,
)
from sqlalchemy.engine import URL

from config import cfg

logger = logging.getLogger(__name__)

_engine: sa.Engine | None = None

_metadata = MetaData()

_detections = Table(
    "detections", _metadata,
    Column("id",         Integer, primary_key=True, autoincrement=True),
    Column("timestamp",  TIMESTAMP(timezone=True), nullable=False),
    Column("species",    String,  nullable=False),
    Column("bto_name",   String),
    Column("confidence", Float,   nullable=False),
    Column("clip_path",  String),
    Column("model",      String),
    # Cross-validation columns — all nullable; NULL = CV not performed
    Column("primary_confidence",  Float),
    Column("cross_validated",     Boolean),
    Column("cv_secondary_model",  String),
    Column("cv_species",          String),
    Column("cv_bto_name",         String),
    Column("cv_confidence",       Float),
    Column("cv_agree",            Boolean),
    Column("flagged",             Boolean),
)

_detection_results = Table(
    "detection_results", _metadata,
    Column("id",           Integer, primary_key=True, autoincrement=True),
    Column("detection_id", Integer, ForeignKey("detections.id"), nullable=False),
    Column("species",      String,  nullable=False),
    Column("confidence",   Float,   nullable=False),
)

_species_info = Table(
    "species_info", _metadata,
    Column("name",                       String, primary_key=True),
    Column("scientific_name",            String),
    Column("british_list_status",        String),
    Column("population_estimate",        String),
    Column("bto_2letter_code",           String),
    Column("bto_5letter_code",           String),
    Column("species_status",             String),
    Column("uk_bocc",                    String),
    Column("birdfacts_url",              String),
    Column("international_english_name", String),
    Column("group_name",                 String),
)

# ── Cross-validation columns added in this version ────────────────────────────
# If the detections table already exists (created by an older version without
# these columns), _migrate_detections_table() adds them via ALTER TABLE.
_CV_COLUMNS: dict[str, str] = {
    "primary_confidence":  "FLOAT",
    "cross_validated":     "BOOLEAN",
    "cv_secondary_model":  "TEXT",
    "cv_species":          "TEXT",
    "cv_bto_name":         "TEXT",
    "cv_confidence":       "FLOAT",
    "cv_agree":            "BOOLEAN",
    "flagged":             "BOOLEAN",
}


def _engine_url() -> str | URL:
    """Build a SQLAlchemy connection URL from config."""
    db = cfg.database
    if db.type == "sqlite":
        cfg.paths.db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{cfg.paths.db_path}"
    # postgresql (and timescaledb, which is a postgresql extension)
    return URL.create(
        drivername="postgresql+psycopg2",
        username=db.username or None,
        password=db.password or None,
        host=db.host,
        port=db.port,
        database=db.name,
    )


def _migrate_detections_table(engine: sa.Engine) -> None:
    """Add any missing cross-validation columns to an existing detections table.

    SQLite does not support ``ALTER TABLE … ADD COLUMN IF NOT EXISTS`` so we
    introspect the schema first and only issue ``ALTER TABLE`` for columns that
    are genuinely absent.  Safe to call on a fresh database (no-op when all
    columns already exist because ``create_all`` created them).
    """
    db_type = cfg.database.type
    with engine.begin() as conn:
        if db_type == "sqlite":
            rows = conn.execute(text("PRAGMA table_info(detections)")).fetchall()
            existing = {row[1] for row in rows}
        else:
            rows = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'detections'"
            )).fetchall()
            existing = {row[0] for row in rows}

        for col_name, col_type in _CV_COLUMNS.items():
            if col_name not in existing:
                conn.execute(text(
                    f"ALTER TABLE detections ADD COLUMN {col_name} {col_type}"
                ))
                logger.info("DB migration: added column detections.%s", col_name)


def init_db() -> None:
    """
    Open the database, ensure the schema exists, and (when configured)
    initialise the TimescaleDB hypertable on *detections.timestamp*.

    Also runs :func:`_migrate_detections_table` to add cross-validation
    columns to any database created by an earlier version of the detector.

    Safe to call multiple times — ``CREATE TABLE IF NOT EXISTS`` is used and
    ``create_hypertable`` is called with ``if_not_exists => TRUE``.
    """
    global _engine

    db_type = cfg.database.type
    url = _engine_url()

    if db_type == "sqlite":
        _engine = sa.create_engine(
            url,
            connect_args={"check_same_thread": False},
        )
        # WAL mode: readers don't block the writer and vice-versa.
        @event.listens_for(_engine, "connect")
        def _set_wal_mode(dbapi_conn, _record) -> None:
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
    else:
        _engine = sa.create_engine(url)

    _metadata.create_all(_engine)
    _migrate_detections_table(_engine)

    if cfg.database.timescaledb:
        with _engine.begin() as conn:
            conn.execute(text(
                "SELECT create_hypertable('detections', 'timestamp',"
                " if_not_exists => TRUE)"
            ))


def record_detection(
    ts:         datetime,
    species:    str,
    confidence: float,
    clip_path:  Path,
    secondary:  list[tuple[str, float]],
    bto_name:   str | None = None,
    model_name: str | None = None,
    # Cross-validation fields — all optional; omit entirely when CV is disabled
    primary_confidence:  float | None = None,
    cross_validated:     bool | None  = None,
    cv_secondary_model:  str | None   = None,
    cv_species:          str | None   = None,
    cv_bto_name:         str | None   = None,
    cv_confidence:       float | None = None,
    cv_agree:            bool | None  = None,
    flagged:             bool | None  = None,
) -> None:
    """
    Persist one detection to the database.

    Inserts a row into ``detections`` for the top species, then one row per
    entry in *secondary* into ``detection_results`` (FK back to
    ``detections``).  Both inserts run in a single transaction.

    When cross-validation was performed, pass the :class:`CrossValidationResult`
    fields directly.  The ``confidence`` column contains the primary model
    confidence score; the raw primary score is also stored in
    ``primary_confidence``.

    Args:
        ts:                  UTC timestamp of the best-confidence hit.
        species:             Primary model common name (e.g. "European Robin").
        confidence:          Primary model confidence score.
        clip_path:           Path to the saved WAV clip.
        secondary:           Additional candidate species from the same window
                             (written to ``detection_results``).
        bto_name:            BTO British name (e.g. "Robin"); ``None`` if
                             unmapped.
        model_name:          Primary inference backend (e.g. ``"birdnet"``).
        primary_confidence:  Raw primary model confidence before any ensemble
                             averaging.  ``None`` when CV was not performed
                             (``confidence`` already equals the primary score).
        cross_validated:     ``True`` / ``False`` if CV ran; ``None`` if CV is
                             disabled or the detection bypassed CV.
        cv_secondary_model:  Name of the secondary model (e.g. ``"perch"``).
        cv_species:          Secondary model's top species label.
        cv_bto_name:         BTO-resolved name for ``cv_species``.
        cv_confidence:       Secondary model's top confidence score.
        cv_agree:            ``True`` if both BTO names matched.
        flagged:             ``True`` when disagreement + ``on_disagree="flag"``.
    """
    if _engine is None:
        return
    with _engine.begin() as conn:
        result = conn.execute(
            _detections.insert().values(
                timestamp            = ts,
                species              = species,
                bto_name             = bto_name,
                confidence           = confidence,
                clip_path            = str(clip_path),
                model                = model_name,
                primary_confidence   = primary_confidence,
                cross_validated      = cross_validated,
                cv_secondary_model   = cv_secondary_model,
                cv_species           = cv_species,
                cv_bto_name          = cv_bto_name,
                cv_confidence        = cv_confidence,
                cv_agree             = cv_agree,
                flagged              = flagged,
            )
        )
        detection_id = result.inserted_primary_key[0]
        if secondary:
            conn.execute(
                _detection_results.insert(),
                [
                    {"detection_id": detection_id, "species": s, "confidence": c}
                    for s, c in secondary
                ],
            )



def seed_species_info(json_path: Path) -> None:
    """Populate ``species_info`` from the BTO JSON file.

    Idempotent: skips seeding if the table already contains rows.  To force
    a re-seed, truncate the table first::

        DELETE FROM species_info;

    Supports both SQLite (INSERT OR REPLACE) and PostgreSQL (INSERT … ON
    CONFLICT DO UPDATE).
    """
    if _engine is None:
        return

    with _engine.begin() as conn:
        count = conn.execute(
            sa.select(sa.func.count()).select_from(_species_info)
        ).scalar()
        if count:
            return  # already seeded

    with json_path.open(encoding="utf-8") as fh:
        entries: list[dict] = json.load(fh)

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
        }
        for e in entries
        if e.get("name")
    ]

    if not rows:
        return

    db_type = cfg.database.type
    with _engine.begin() as conn:
        if db_type == "sqlite":
            # INSERT OR REPLACE handles any future re-seeding after a partial truncate.
            conn.execute(
                text(
                    "INSERT OR REPLACE INTO species_info "
                    "(name, scientific_name, british_list_status, population_estimate, "
                    " bto_2letter_code, bto_5letter_code, species_status, uk_bocc, "
                    " birdfacts_url, international_english_name, group_name) "
                    "VALUES (:name, :scientific_name, :british_list_status, "
                    " :population_estimate, :bto_2letter_code, :bto_5letter_code, "
                    " :species_status, :uk_bocc, :birdfacts_url, "
                    " :international_english_name, :group_name)"
                ),
                rows,
            )
        else:
            # PostgreSQL upsert
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = pg_insert(_species_info).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["name"],
                set_={c.name: c for c in stmt.excluded if c.name != "name"},
            )
            conn.execute(stmt)
