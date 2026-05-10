# AGENTS.md

## What this is

Real-time garden bird detector for a Norfolk, UK garden. Two independently runnable processes:
- **Detector** (`detect.py`): microphone → BirdNET TFLite inference → SQLite + WAV clips
- **Dashboard** (`dashboard/`): FastAPI backend + Svelte SPA

## Commands

```bash
# Detector
python detect.py

# Dashboard backend (dev, with auto-reload)
uvicorn dashboard.app:app --host 0.0.0.0 --port 8080 --reload

# Frontend dev server (port 5173, proxies /api /stream /spectrogram /audio → 8080)
cd dashboard/frontend && npm run dev

# Build frontend for production (outputs to dashboard/frontend/dist/)
cd dashboard/frontend && npm run build

# TypeScript typecheck (Svelte)
cd dashboard/frontend && npm run check

# List available audio input devices
python -m sounddevice
```

No Makefile, Taskfile, pre-commit hooks, or CI workflows exist. No test suite.

## Install

```bash
pip install -r requirements.txt
pip install -r dashboard/requirements.txt

# NOTE: librosa and matplotlib are missing from dashboard/requirements.txt
# but are imported by dashboard/routes/media.py — install them separately:
pip install librosa matplotlib

# Optional PostgreSQL support
pip install psycopg2-binary

cd dashboard/frontend && npm install
```

## Architecture notes

- **Unified database layer**: Both the detector (writes) and dashboard (reads) use SQLAlchemy, driven by the same `[database]` section in `config.toml`. `dashboard/database.py` creates its own read engine from `cfg` — separate instance from the write engine, which is safe under SQLite WAL. `dashboard/config.py` derives `DB_PATH` from `cfg.paths.db_path` (no longer hardcoded).
- **WAL mode**: Detector enables SQLite WAL so the dashboard reader never blocks the writer.
- **Config singleton**: All runtime config lives in `config.toml`. Loaded once at import time into a frozen dataclass hierarchy. Import with `from config import cfg`. Note: `cfg.database.type` (not `.backend`) is the backend key.
- **Path resolution**: `config.py` loads `db_path` as a raw `Path` from `config.toml` (relative to CWD). `dashboard/database.py` and `dashboard/config.py` resolve it against `Path(__file__).parent.parent` so the dashboard works from any working directory.
- **Inference via temp file**: `run_inference()` writes a temp WAV, calls BirdNET `analyze()` (stdout suppressed), reads back CSV. BirdNET analyzer is imported lazily inside the function.

## Non-obvious conventions

- **High-pass filter is inference-only**: Applied to a copy of the buffer. `save_clip()` always writes raw, unfiltered audio.
- **Two clip types**: Detection clips are amplitude-normalised (full int16 range). Pending clips for retraining (`data/pending/`) are *not* normalised — this is intentional to match xeno-canto training data amplitude characteristics.
- **Confidence threshold sync**: `dashboard/config.py` defines `CONF_HIGH = 0.9` / `CONF_MED = 0.7`. `dashboard/frontend/src/lib/confidence.ts` mirrors these manually — no codegen. Keep both in sync.
- **Species name format**: Custom classifier labels are `Genus_species_Common_Name`. `clean_species_name()` strips the scientific prefix. Config keys must use the resulting common name (case-insensitive lookup).
- **Location hardcoded**: Sunrise/sunset in `dashboard/sun.py` uses 52.699°N 1.675°E (Norfolk). Also in `dashboard/config.py` as `SUN_LAT`/`SUN_LON`. `SPECIES_META` is UK-specific.
- **paho-mqtt v1/v2 compat**: `mqtt.py` branches on `CallbackAPIVersion` availability to handle both API versions.

## Key file map

| File | Role |
|---|---|
| `detect.py` | Entry point (calls `detector.main()`) |
| `detector.py` | Recording thread, classify loop, main loop |
| `audio.py` | WAV I/O, clip saving, high-pass filter |
| `inference.py` | BirdNET wrapper, label parsing, `clean_species_name()` |
| `database.py` | SQLAlchemy multi-backend (detector writes) |
| `config.py` | Typed config loader via `tomllib` |
| `retention.py` | Background thread: age/disk cleanup |
| `mqtt.py` | Optional paho-mqtt publish |
| `dashboard/app.py` | FastAPI app factory |
| `dashboard/database.py` | sqlite3 read-only helper (dashboard reads) |
| `dashboard/routes/media.py` | Spectrogram generation (librosa, LRU 256 entries) |
| `dashboard/frontend/src/lib/api.ts` | Typed fetch wrappers for all API endpoints |
| `checkpoints/custom/` | TFLite classifier + labels (required at runtime) |
| `data/` | Runtime data: `birds.db`, `detections/`, `pending/`, image cache |
