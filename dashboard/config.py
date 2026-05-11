"""
dashboard/config.py — configuration for the dashboard, derived from the
detector's config singleton.

Adds the project root to sys.path so `from config import cfg` resolves
correctly regardless of the working directory uvicorn was launched from.
"""

from __future__ import annotations

import sys
from pathlib import Path
from zoneinfo import ZoneInfo

# Project root = parent of this file's parent (dashboard/)
_PROJECT_ROOT = Path(__file__).parent.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import cfg  # noqa: E402 — must follow sys.path manipulation

# ── Paths ─────────────────────────────────────────────────────────────────────
# config.toml stores paths relative to CWD; resolve them against project root
# so the dashboard works from any working directory.
DB_PATH: Path = (_PROJECT_ROOT / cfg.paths.db_path).resolve()
DETECTIONS_DIR: Path = (_PROJECT_ROOT / cfg.paths.detections_dir).resolve()

# ── Timezone ──────────────────────────────────────────────────────────────────
# IANA timezone name from [general] timezone in config.toml.
# LOCAL_TZ is used to convert UTC timestamps from the DB to local time and
# to compute correct day boundaries for date-based filters.
TIMEZONE: str = cfg.general.timezone
LOCAL_TZ: ZoneInfo = ZoneInfo(TIMEZONE)

# ── Confidence thresholds — keep in sync with frontend/src/lib/confidence.ts ──
CONF_HIGH: float = 0.9
CONF_MED: float = 0.7

# ── Geographic location ───────────────────────────────────────────────────────
# WGS-84 decimal degrees from [location] in config.toml.
# Used for sunrise/sunset calculations.
SUN_LAT: float = cfg.location.lat
SUN_LON: float = cfg.location.lon

# ── SSE polling interval ──────────────────────────────────────────────────────
SSE_POLL_SECONDS: float = 2.0
