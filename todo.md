# Bird Detector — TODO

## Done

- [x] Refactor `detect.py` into separate modules (`config.py`, `audio.py`, `inference.py`, `database.py`, `detector.py`, `detect.py`)
- [x] Move configuration to `config.toml` (TOML format, Python 3.11+ `tomllib`, zero extra dependencies)
- [x] Per-species confidence threshold and cooldown settings — any key from `[defaults]` can be overridden in `[species."Name"]` sections
- [x] High-pass filter — Butterworth, configurable `cutoff_hz` and `order`, applied to inference audio only (saved clips always remain unfiltered)


- [x] **Clip retention / disk cleanup**
  - `data/detections/` grows indefinitely; needs an age-based and/or disk-usage-based cleanup policy
  - New `[retention]` config section: `max_age_days`, `max_usage_percent`, `min_clips_per_species`
  - Runs as a background thread or on startup

- [x] **File logging with rotation**
  - Currently all output is `print()` to stdout — lost when the terminal closes
  - New `[log]` config section: `enabled`, `path`, `rotation` (daily / size), `max_size_bytes`
  - Replace `print()` calls in `detector.py` with `logging` module calls

- [x] **Species exclude list**
  - A simple global list of species to permanently suppress, distinct from `noise_labels` (which targets non-species classifier labels)
  - New `exclude` key under `[defaults]`: `exclude = ["Common Wood Pigeon", "Carrion Crow"]`
  - Filtered in `detector.py` before confidence checks




---

## Backlog


### Medium priority

- [x] **Multi-backend database support**
  - Replace direct `sqlite3` calls with SQLAlchemy Core so the backend is swappable via config
  - Support: SQLite (default, zero config), PostgreSQL, TimescaleDB (opt-in PostgreSQL extension — single hypertable call at init)
  - Also fix: `timestamp` column from `TEXT` (ISO string) → `TIMESTAMPTZ` for proper time-range queries in PostgreSQL / TimescaleDB
  - New `[database]` config section: `type`, `host`, `port`, `name`, `username`, `password`, `timescaledb` flag; SQLite path stays in `[paths]` as today
  - New dependencies: `sqlalchemy`; `psycopg2-binary` for PostgreSQL (optional, only needed if using PostgreSQL)
  - Only `database.py` and `config.py` change — no other files affected
  - *Blocker: none*

- [x] **MQTT publishing**
  - Publish each detection as a JSON message to a configurable MQTT broker and topic
  - New `[mqtt]` config section: `enabled`, `broker`, `port`, `topic`, `username`, `password`, `retain`
  - New `mqtt.py` module; called from `detector.py` alongside `record_detection`

- [ ] **Per-species on-detection actions**
  - Execute a configurable shell command/script when a specific species is detected
  - New `actions` key under `[species."Name"]` sections, e.g.:
    ```toml
    [species."Eurasian Sparrowhawk"]
    actions = ["/home/andy/scripts/notify.sh {species} {confidence}"]
    ```
  - Executed asynchronously so they don't block the classify loop

- [ ] **Dog bark filter**
  - Dog barks cause false positives for several species (e.g. Common Pheasant, Eurasian Eagle-Owl)
  - When the classifier scores `Dog` above `confidence`, suppress all detections for `suppress_seconds`
  - New `[dogbark]` config section: `enabled`, `confidence`, `suppress_seconds`
  - Requires adding a `Dog` class to the custom classifier (planned during upcoming species expansion)
  - *Blocker: requires custom classifier retraining with dog audio samples*

- [ ] **Human voice / privacy filter**
  - Suppress detections triggered by human voices near the microphone; same pattern as the dog bark filter
  - When the classifier scores `Human vocal` or `Human non-vocal` above `confidence`, suppress all detections for `suppress_seconds`
  - The standard BirdNET V2.4 model already includes these classes; add them to the custom classifier during the upcoming species expansion
  - New `[privacyfilter]` config section: `enabled`, `confidence`, `suppress_seconds`
  - *Blocker: requires custom classifier retraining with human audio samples*

- [ ] **Processing time reporting**
  - Log the wall-clock duration of each inference cycle
  - New `processing_time` boolean under `[defaults]` or a `[debug]` section
  - Useful for monitoring performance on constrained hardware (e.g. Raspberry Pi)

### Low priority

- [ ] **Species tracking (first of year / first of season)**
  - Track and surface the first detection of each species per calendar year and per season
  - Requires new DB tables (`species_first_seen`, `species_yearly`, `species_seasonal`)
  - Season boundaries configurable in `config.toml`
  - Exposed via the dashboard

- [ ] **Audio export format (mp3 / flac)**
  - WAV clips are large; mp3 at ~192k would reduce storage by ~85% with no meaningful quality loss for review
  - New `format` key under `[paths]` or a `[export]` section: `wav`, `mp3`, `flac`
  - Requires `ffmpeg` (via `subprocess`) or `pydub`
