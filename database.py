"""
database.py — saves bird detections to SQLite or PostgreSQL.

Configure the backend via ``[database]`` in config.toml:
    sqlite      — default, no setup required; path from ``[paths] db_path``
    postgresql  — requires psycopg2-binary; set host/port/name/user/password

TimescaleDB: set ``timescaledb = true`` under ``[database]`` to enable time-series
optimisation. The backend type stays ``"postgresql"`` — TimescaleDB is just an
extension on top of it.

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

    -- Weather metadata columns (all NULL when weather is disabled or fetch failed)
    weather_temp           FLOAT              (°C)
    weather_humidity       FLOAT              (%)
    weather_wind_speed     FLOAT              (m/s)
    weather_wind_direction FLOAT              (degrees, 0–360 clockwise from N)
    weather_pressure       FLOAT              (hPa, sea level)
    weather_condition      TEXT               (human-readable, e.g. "Partly cloudy")
    weather_precipitation  FLOAT              (mm)
    weather_provider       TEXT               (e.g. "open_meteo", "yr_no", "meteobridge")

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
    ebird_code               TEXT  (eBird species code, e.g. "robin1")
    avicommons_image_url     TEXT  (AviCommons CDN image URL; NULL if unmatched)
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
    # Cross-validation columns — NULL means CV was not performed
    Column("primary_confidence",  Float),
    Column("cross_validated",     Boolean),
    Column("cv_secondary_model",  String),
    Column("cv_species",          String),
    Column("cv_bto_name",         String),
    Column("cv_confidence",       Float),
    Column("cv_agree",            Boolean),
    Column("flagged",             Boolean),
    # Verification status — set automatically at insert time, overridable by admin.
    # Values: 'unverified' | 'auto' | 'cv' | 'human'
    Column("verification_status", String, default="unverified"),
    # Weather columns — NULL means weather was disabled or the fetch failed
    Column("weather_temp",           Float),
    Column("weather_humidity",        Float),
    Column("weather_wind_speed",      Float),
    Column("weather_wind_direction",  Float),
    Column("weather_pressure",        Float),
    Column("weather_condition",       String),
    Column("weather_precipitation",   Float),
    Column("weather_provider",        String),
    # NULL in single-source mode; set to the source name when multiple sources are active
    Column("source_name",            String),
    # NULL when dedup is disabled or this is the primary detection
    Column("deduplicated",           Boolean),
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
    Column("ebird_code",                 String),
    Column("avicommons_image_url",       String),
    Column("avicommons_image_by",        String),
    Column("avicommons_image_license",   String),
)

# Columns added when cross-validation support was introduced.
# _migrate_detections_table() adds these to older databases that predate CV.
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

# Columns added to species_info after the initial schema.
_SPECIES_INFO_COLUMNS: dict[str, str] = {
    "ebird_code":                "TEXT",
    "avicommons_image_url":      "TEXT",
    "avicommons_image_by":       "TEXT",
    "avicommons_image_license":  "TEXT",
}

# Columns added when weather logging was introduced.
# NULL on all rows where weather was disabled or the fetch failed.
_WEATHER_COLUMNS: dict[str, str] = {
    "weather_temp":           "FLOAT",
    "weather_humidity":       "FLOAT",
    "weather_wind_speed":     "FLOAT",
    "weather_wind_direction": "FLOAT",
    "weather_pressure":       "FLOAT",
    "weather_condition":      "TEXT",
    "weather_precipitation":  "FLOAT",
    "weather_provider":       "TEXT",
}

# Column added when multi-source audio support was introduced.
# NULL on rows created before this; set to [[audio.sources]] name going forward.
_SOURCE_NAME_COLUMN: dict[str, str] = {
    "source_name": "TEXT",
}

# Column added when cross-source deduplication was introduced.
# NULL when dedup is off or this is the primary detection.
# TRUE when on_duplicate = "flag" and this is a flagged duplicate.
_DEDUP_COLUMN: dict[str, str] = {
    "deduplicated": "BOOLEAN",
}

# Column added when the verification status system was introduced.
# Replaces the boolean flagged column with a richer status string.
# Values: 'unverified' | 'auto' | 'cv' | 'human'
_VERIFICATION_STATUS_COLUMN: dict[str, str] = {
    "verification_status": "TEXT",
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


def _get_existing_columns(conn: sa.Connection, table: str) -> set[str]:
    """Return the set of column names currently in *table*.

    Uses PRAGMA table_info on SQLite and information_schema on PostgreSQL,
    since SQLite doesn't support ALTER TABLE … ADD COLUMN IF NOT EXISTS.
    """
    db_type = cfg.database.type
    if db_type == "sqlite":
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return {row[1] for row in rows}
    else:
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t"
        ), {"t": table}).fetchall()
        return {row[0] for row in rows}


def _add_missing_columns(
    engine: sa.Engine,
    table: str,
    columns: dict[str, str],
) -> None:
    """Add any columns from *columns* that are not already present in *table*.

    Safe to call on a fresh database — it's a no-op when all columns exist.
    Each ``{col_name: col_type}`` entry is added via ``ALTER TABLE … ADD COLUMN``
    only if the column is absent, so the function is idempotent.
    """
    with engine.begin() as conn:
        existing = _get_existing_columns(conn, table)
        for col_name, col_type in columns.items():
            assert col_name.isidentifier(), f"Unsafe column name: {col_name!r}"
            if col_name not in existing:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"
                ))
                logger.info("DB migration: added column %s.%s", table, col_name)


def _migrate_detections_table(engine: sa.Engine) -> None:
    """Add any missing cross-validation columns to an existing detections table."""
    _add_missing_columns(engine, "detections", _CV_COLUMNS)


def _migrate_species_info_table(engine: sa.Engine) -> None:
    """Add any missing columns to an existing species_info table."""
    _add_missing_columns(engine, "species_info", _SPECIES_INFO_COLUMNS)


def _migrate_weather_columns(engine: sa.Engine) -> None:
    """Add weather columns to an existing detections table."""
    _add_missing_columns(engine, "detections", _WEATHER_COLUMNS)


def _migrate_source_name_column(engine: sa.Engine) -> None:
    """Add the source_name column to an existing detections table.

    Introduced with multi-source audio support. Rows created before this
    migration will have NULL; new rows are populated from [[audio.sources]] name.
    No-op if the column already exists.
    """
    _add_missing_columns(engine, "detections", _SOURCE_NAME_COLUMN)


def _migrate_dedup_column(engine: sa.Engine) -> None:
    """Add the deduplicated column to an existing detections table.

    Introduced with cross-source deduplication. Rows before this migration
    will have NULL. Set to TRUE when on_duplicate = "flag" and the detection
    is a cross-source duplicate. No-op if the column already exists.
    """
    _add_missing_columns(engine, "detections", _DEDUP_COLUMN)


def _migrate_verification_status_column(engine: sa.Engine) -> None:
    """Add the verification_status column and back-fill existing rows.

    Introduced to replace the simple boolean flagged column with a richer
    verification workflow. Values: 'unverified', 'auto', 'cv', 'human'.

    Back-fill rules applied to existing rows:
      - 'cv'   if cross_validated=1 AND cv_agree=1
      - 'auto' if confidence >= auto_verify_threshold (from config)
      - 'unverified' otherwise

    No-op if the column already exists.
    """
    threshold = cfg.admin.auto_verify_threshold
    with engine.begin() as conn:
        existing = _get_existing_columns(conn, "detections")

        if "verification_status" not in existing:
            conn.execute(text(
                "ALTER TABLE detections ADD COLUMN verification_status TEXT DEFAULT 'unverified'"
            ))
            logger.info("DB migration: added column detections.verification_status")
            # Back-fill cv rows first (strongest signal)
            conn.execute(text(
                "UPDATE detections SET verification_status = 'cv' "
                "WHERE cross_validated = 1 AND cv_agree = 1"
            ))
            # Back-fill auto rows where confidence meets the threshold
            conn.execute(text(
                "UPDATE detections SET verification_status = 'auto' "
                "WHERE verification_status = 'unverified' AND confidence >= :t"
            ), {"t": threshold})
            logger.info(
                "DB migration: back-filled verification_status (auto threshold=%.2f)",
                threshold,
            )


def init_db() -> None:
    """Open the database, create tables if needed, and run any pending migrations.

    Also enables the TimescaleDB hypertable on detections.timestamp when
    ``[database] timescaledb = true``. Safe to call more than once.
    """
    global _engine

    db_type = cfg.database.type
    url = _engine_url()

    if db_type == "sqlite":
        _engine = sa.create_engine(
            url,
            connect_args={"check_same_thread": False},
        )
        # WAL mode lets readers and writers run concurrently without blocking each other.
        @event.listens_for(_engine, "connect")
        def _set_wal_mode(dbapi_conn, _record) -> None:
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
    else:
        _engine = sa.create_engine(url)

    _metadata.create_all(_engine)
    _migrate_detections_table(_engine)
    _migrate_species_info_table(_engine)
    _migrate_weather_columns(_engine)
    _migrate_source_name_column(_engine)
    _migrate_dedup_column(_engine)
    _migrate_verification_status_column(_engine)

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
    bto_name:   str | None = None,
    model_name: str | None = None,
    # Cross-validation fields — omit (leave None) when CV is disabled
    primary_confidence:  float | None = None,
    cross_validated:     bool | None  = None,
    cv_secondary_model:  str | None   = None,
    cv_species:          str | None   = None,
    cv_bto_name:         str | None   = None,
    cv_confidence:       float | None = None,
    cv_agree:            bool | None  = None,
    # Weather fields — None when weather is disabled or unavailable
    weather_temp:           float | None = None,
    weather_humidity:       float | None = None,
    weather_wind_speed:     float | None = None,
    weather_wind_direction: float | None = None,
    weather_pressure:       float | None = None,
    weather_condition:      str | None   = None,
    weather_precipitation:  float | None = None,
    weather_provider:       str | None   = None,
    # None in single-source mode
    source_name:            str | None   = None,
    # True when flagged as a cross-source duplicate; None otherwise
    deduplicated:           bool | None  = None,
    # True when CV returned action="flag" (models disagree but detection is saved)
    flagged:                bool         = False,
) -> None:
    """Write one detection to the database.

    Inserts a row into ``detections`` for the top species.

    verification_status is computed automatically:
      - 'cv'          when cross_validated=True and cv_agree=True
      - 'auto'        when confidence >= cfg.admin.auto_verify_threshold
      - 'unverified'  otherwise

    Args:
        ts:                  UTC timestamp of the detection.
        species:             Primary model common name (e.g. "European Robin").
        confidence:          Primary model confidence score.
        clip_path:           Path to the saved audio clip.
        bto_name:            BTO British name (e.g. "Robin"); None if unmapped.
        model_name:          Primary inference backend (e.g. "birdnet").
        primary_confidence:  Raw primary score before any ensemble averaging.
                             None when CV was not performed.
        cross_validated:     True/False if CV ran; None if CV is disabled.
        cv_secondary_model:  Name of the secondary model (e.g. "perch").
        cv_species:          Secondary model's top species label.
        cv_bto_name:         BTO-resolved name for cv_species.
        cv_confidence:       Secondary model's top confidence score.
        cv_agree:            True if both models agreed on the same BTO name.
        weather_temp:        Air temperature in °C at detection time.
        weather_humidity:    Relative humidity (%) at detection time.
        weather_wind_speed:  Wind speed in m/s at detection time.
        weather_wind_direction: Wind direction in degrees (0–360) at detection time.
        weather_pressure:    Sea-level pressure in hPa at detection time.
        weather_condition:   Human-readable sky condition, e.g. "Light rain".
        weather_precipitation: Precipitation in mm at detection time.
        weather_provider:    Data source identifier, e.g. "open_meteo".
        source_name:         Audio source name from ``[[audio.sources]]``.
                             None (SQL NULL) in single-source mode.
        deduplicated:        True when saved as a flagged cross-source duplicate.
                             None in all other cases.
        flagged:             True when CV returned action="flag" — both models ran
                             but disagreed; detection is saved for manual review.
    """
    # Compute verification status at insert time — admin can override later.
    if cross_validated and cv_agree:
        verification_status = "cv"
    elif confidence >= cfg.admin.auto_verify_threshold:
        verification_status = "auto"
    else:
        verification_status = "unverified"

    if _engine is None:
        return
    with _engine.begin() as conn:
        result = conn.execute(
            _detections.insert().values(
                timestamp              = ts,
                species                = species,
                bto_name               = bto_name,
                confidence             = confidence,
                clip_path              = str(clip_path),
                model                  = model_name,
                primary_confidence     = primary_confidence,
                cross_validated        = cross_validated,
                cv_secondary_model     = cv_secondary_model,
                cv_species             = cv_species,
                cv_bto_name            = cv_bto_name,
                cv_confidence          = cv_confidence,
                cv_agree               = cv_agree,
                verification_status    = verification_status,
                weather_temp           = weather_temp,
                weather_humidity       = weather_humidity,
                weather_wind_speed     = weather_wind_speed,
                weather_wind_direction = weather_wind_direction,
                weather_pressure       = weather_pressure,
                weather_condition      = weather_condition,
                weather_precipitation  = weather_precipitation,
                weather_provider       = weather_provider,
                source_name            = source_name,
                deduplicated           = deduplicated,
                flagged                = flagged,
            )
        )


def seed_species_info(json_path: Path) -> None:
    """Load species reference data from the BTO JSON file into species_info.

    Runs an upsert on every startup so that newly-added columns (e.g.
    ebird_code, avicommons_image_url) are back-filled into existing databases.

    To force a full reset (e.g. to remove deleted species):
        DELETE FROM species_info;

    Supports both SQLite (INSERT OR REPLACE) and PostgreSQL (INSERT … ON
    CONFLICT DO UPDATE).
    """
    if _engine is None:
        return

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
            "ebird_code":                 e.get("ebird_code") or None,
            "avicommons_image_url":       e.get("avicommons_image_url") or None,
            "avicommons_image_by":        e.get("avicommons_image_by") or None,
            "avicommons_image_license":   e.get("avicommons_image_license") or None,
        }
        for e in entries
        if e.get("name")
    ]

    if not rows:
        return

    db_type = cfg.database.type
    with _engine.begin() as conn:
        if db_type == "sqlite":
            # INSERT OR REPLACE handles re-seeding after a partial truncate.
            conn.execute(
                text(
                    "INSERT OR REPLACE INTO species_info "
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
        else:
            # PostgreSQL upsert
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = pg_insert(_species_info).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["name"],
                set_={c.name: c for c in stmt.excluded if c.name != "name"},
            )
            conn.execute(stmt)
