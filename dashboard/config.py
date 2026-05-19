"""
Dashboard configuration — reads settings from the detector's config singleton.

Adds the project root to sys.path so `from config import cfg` resolves
correctly regardless of which directory uvicorn was launched from.
"""

from __future__ import annotations

import sys
from pathlib import Path
from zoneinfo import ZoneInfo

# Parent of the dashboard/ package directory
_PROJECT_ROOT = Path(__file__).parent.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import cfg  # noqa: E402 — must follow sys.path manipulation

# ── Paths ─────────────────────────────────────────────────────────────────────
# Paths in config.toml are relative to CWD; resolve against project root so
# the dashboard works correctly from any working directory.
DB_PATH: Path = (_PROJECT_ROOT / cfg.paths.db_path).resolve()
DETECTIONS_DIR: Path = (_PROJECT_ROOT / cfg.paths.detections_dir).resolve()

# ── Timezone ──────────────────────────────────────────────────────────────────
# IANA timezone name from [general] in config.toml.
# LOCAL_TZ is used to convert UTC timestamps and compute local day boundaries.
TIMEZONE: str = cfg.general.timezone
LOCAL_TZ: ZoneInfo = ZoneInfo(TIMEZONE)

# ── Station name ──────────────────────────────────────────────────────────────
# Shown in the dashboard header; falls back to "BirdNet-UK" if not set.
STATION_NAME: str = cfg.general.station_name or "BirdNet-UK"

# ── Confidence thresholds — keep in sync with frontend/src/lib/confidence.ts ──
CONF_HIGH: float = 0.9
CONF_MED: float = 0.7

# ── Geographic location ───────────────────────────────────────────────────────
# WGS-84 decimal degrees from [location] in config.toml.
# Used for sunrise/sunset calculations.
SUN_LAT: float = cfg.location.lat
SUN_LON: float = cfg.location.lon

# ── Database backend ──────────────────────────────────────────────────────────
# "sqlite" or "postgresql" — controls which async driver is used.
DB_TYPE: str = cfg.database.type

# Build the async SQLAlchemy connection URL for the chosen backend:
#   sqlite      → sqlite+aiosqlite:///path/to/birds.db
#   postgresql  → postgresql+asyncpg://user:pass@host:port/db
if DB_TYPE == "postgresql":
    _db = cfg.database
    DB_URL: str = (
        f"postgresql+asyncpg://{_db.username}:{_db.password}"
        f"@{_db.host}:{_db.port}/{_db.name}"
    )
else:
    DB_URL: str = f"sqlite+aiosqlite:///{DB_PATH}"

# ── SSE polling interval ──────────────────────────────────────────────────────
SSE_POLL_SECONDS: float = 2.0
