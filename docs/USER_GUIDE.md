# Bird Detector — User Guide

Real-time UK garden bird classifier: a microphone listens continuously, BirdNET
analyses three-second windows, and confirmed detections are written to a SQLite
database and saved as audio clips.  A FastAPI + SvelteKit dashboard shows live
detections, spectrograms, and statistics.

---

## Contents

1. [Requirements](#1-requirements)
2. [Installation](#2-installation)
3. [Find your audio device](#3-find-your-audio-device)
4. [Configuration](#4-configuration)
5. [Running the detector](#5-running-the-detector)
6. [Running the dashboard](#6-running-the-dashboard)
7. [Understanding the terminal output](#7-understanding-the-terminal-output)
8. [Per-species overrides](#8-per-species-overrides)
9. [Optional features](#9-optional-features)
10. [Maintenance](#10-maintenance)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Requirements

**Hardware**
- A microphone or USB audio interface positioned outdoors or near a window.
  An omnidirectional condenser mic works well; a USB interface with a shotgun
  or parabolic mic increases range.
- Any modern Linux machine (Raspberry Pi 5 or x86 desktop both work).
  BirdNET inference takes roughly 0.15–0.4 s per 3-second window on a Pi 5.

**Software**
- Python 3.11 (the repo `venv` is set up for 3.11)
- Node.js ≥ 18 and npm (for the frontend build only)

---

## 2. Installation

```sh
# Clone the repo and create a virtual environment
git clone <repo-url>
cd birdid-uk
python3.11 -m venv venv
source venv/bin/activate

# All dependencies (detector + dashboard) are in one file
pip install -r requirements.txt

# Frontend build (required once before running in production)
cd dashboard/frontend
npm install
npm run build
cd ../..
```

The first time you run the detector, BirdNET will be ready immediately — no
model download required.  The `data/` directory and SQLite database are created
automatically on first run.

---

## 3. Find your audio device

List available audio devices to find the index for your microphone:

```sh
source venv/bin/activate
python -m sounddevice
```

Output looks like:

```
   0 HDA Intel PCH: CX8200 Analog (hw:0,0), ALSA (2 in, 0 out)
   1 USB Audio Device, ALSA (2 in, 0 out)
   2 pulse, ALSA (32 in, 32 out)
```

Set the index in `config.toml`:

```toml
[audio]
device = 1   # USB Audio Device
```

Use `device = 0` to let the system default (PipeWire/PulseAudio) decide.

---

## 4. Configuration

All settings live in `config.toml`.  Edit this file before running the
detector.  The minimum you need to change for a new installation are
`[location]` (your coordinates) and `[audio] device`.

### `[general]`

```toml
timezone     = "Europe/London"
station_name = "My Garden"
```

`timezone` must be a valid IANA timezone name.  `"Europe/London"` handles
GMT/BST automatically — no manual clock-change adjustment needed.

`station_name` appears in the dashboard header.  Leave empty to use the
default "BirdNet-UK".

---

### `[location]`

```toml
lat = 52.69867
lon = 1.67531
```

WGS-84 decimal degrees for your location.  Used for sunrise/sunset
calculations in the dashboard.  Find your coordinates on
[Google Maps](https://maps.google.com) by right-clicking your location.

---

### `[paths]`

```toml
detections_dir = "data/detections"
db_path        = "data/birds.db"
```

Paths relative to the project root.  Change `detections_dir` if you want
audio clips saved to a different volume (e.g. an external SSD).

---

### `[audio]`

```toml
sample_rate           = 48000
hop_seconds           = 1
clip_mode             = "window"
window_pad_seconds    = 0.5
device                = 0
```

**`sample_rate`** — recording rate in Hz.  `48000` works with virtually all
USB audio interfaces.  Change to `44100` only if your hardware requires it.
Both BirdNET and Perch resample internally; this does not affect accuracy.

**`hop_seconds`** — how often (in seconds) the analysis window advances.
At `1`, a new BirdNET result is produced every second.

**`clip_mode`** — controls the audio saved for each detection:

| Mode | What is saved | Best for |
|---|---|---|
| `"window"` | Model window + `window_pad_seconds` of lead-in (~3.5 s) | Disk-efficient, clean clips, model fine-tuning |
| `"full"` | `clip_seconds` of audio centred on the detection (~15 s) | Manual listening with context |

`"window"` is the default and recommended.  When using `"full"` mode, also
set `clip_seconds`, `pre_capture_seconds`, and `capture_buffer_seconds`.

---

### `[inference]`

```toml
model = "birdnet"
```

`"birdnet"` uses BirdNET GLOBAL 6K V2.4 (bundled, no download needed).
`"perch"` uses Google Perch v2 (see [Optional features](#9-optional-features)).

---

### `[defaults]`

```toml
min_confidence              = 0.6
cooldown_seconds            = 30
min_detections              = 2
confirmation_window_seconds = 9
exclude                     = []
```

**`min_confidence`** — detections below this score are discarded.  `0.6` is
a good starting point.  Lower it (e.g. `0.4`) if you are missing detections;
raise it (e.g. `0.8`) if you are seeing false positives.

**`cooldown_seconds`** — minimum gap between saved clips for the same species.
Prevents the log being flooded when a bird sings continuously.

**`min_detections`** / **`confirmation_window_seconds`** — a species must be
detected at least `min_detections` times within `confirmation_window_seconds`
seconds before a clip is saved.  With `hop_seconds = 1` this means a species
must appear in at least 2 consecutive windows within 9 seconds.  Set
`min_detections = 1` to save on the first hit (less filtering, more clips).

**`exclude`** — species to permanently suppress regardless of confidence.
Use exact IOC common names as printed in the terminal output:

```toml
exclude = ["Common Wood-Pigeon", "Carrion Crow", "Common Starling"]
```

---

### `[filter]`

```toml
enabled   = true
cutoff_hz = 150
order     = 5
```

A high-pass Butterworth filter applied to audio **before inference** only —
saved clips always contain the original, unfiltered audio.  Reduces false
positives from wind, traffic, and HVAC noise.  `150 Hz` is safe for all UK
bird species.

---

### `[seasonal_filter]`

```toml
enabled     = true
filter_json = "uk_seasonal_filter.json"
```

Suppresses detections outside a species' expected UK season, using ISO 8601
week numbers derived from GBIF Great Britain occurrence data.  Species absent
from the JSON are treated as year-round.

To customise: copy `uk_seasonal_filter.json`, edit it, and point `filter_json`
at the copy.  To regenerate the original from GBIF data:

```sh
python build_uk_seasonal_filter.py
```

---

### `[nocturnal_filter]`

```toml
enabled     = true
filter_json = "uk_nocturnal_filter.json"
```

Suppresses detections of nocturnal and crepuscular species during daytime.
`uk_nocturnal_filter.json` covers Tawny Owl, Barn Owl, Long-eared Owl,
European Nightjar, Eurasian Woodcock, Corn Crake, and Black-crowned Night Heron.

Two window types are supported:

| Type | Description |
|---|---|
| `sunset_sunrise` | Active from sunset to sunrise, with optional per-event offsets in minutes (negative = before the event) |
| `fixed` | Fixed local clock range, e.g. `21:00`–`05:00`; spans midnight correctly |

Windows are calculated using `[location] lat`/`lon` and `[general] timezone`.
Species not in the JSON are unaffected (pass through freely).

Per-species active-hours overrides are set in `[species."Name"]` blocks — see
[Per-species overrides](#8-per-species-overrides).

---

### `[retention]`

```toml
enabled               = true
max_age_days          = 30
max_usage_percent     = 90.0
min_clips_per_species = 5
run_interval_seconds  = 3600
```

Automatic disk cleanup for `data/detections/`.  A background thread runs
every `run_interval_seconds` and applies two passes:

1. **Age pass** — delete clips older than `max_age_days`.
2. **Disk pass** — if the disk is more than `max_usage_percent` full, delete
   the oldest clips until usage drops below that threshold.

`min_clips_per_species` protects a minimum number of clips per species from
both passes, so rare species are not wiped by the age cutoff.

Set `max_age_days = 0` to disable age-based deletion and rely on disk usage
alone.

---

### `[log]`

```toml
enabled  = true
path     = "data/birdid-uk.log"
level    = "INFO"
rotation = "daily"
backup_count = 7
```

**`level`** — `"INFO"` is recommended for normal use.  Use `"DEBUG"` to see
individual BOU/seasonal filter decisions (why a detection was suppressed).

**`rotation`** — `"daily"` creates a new file at midnight and keeps
`backup_count` previous files.  `"size"` rotates when the file exceeds
`max_size_bytes`.

---

### `[database]`

The default SQLite backend requires no configuration.  For PostgreSQL see
[Optional features](#9-optional-features).

---

## 5. Running the detector

### Single process (development / SBC)

`main.py` runs the detector and dashboard together in one process — the
simplest way to get everything running:

```sh
source venv/bin/activate
python main.py
```

Open `http://localhost:8080` in your browser.  Stop with `Ctrl+C`; the
detector shuts down cleanly after uvicorn exits.

Options:

```sh
python main.py --host 0.0.0.0 --port 9000   # different port
python main.py --host 127.0.0.1              # localhost only
```

### Detector only

If you want to run the detector without the dashboard (e.g. headless capture):

```sh
source venv/bin/activate
python detect.py
```

### Production — two independent systemd services

The `systemd/` directory contains pre-written service files that run the
detector and dashboard as separate services with automatic restart on crash.

```sh
# 1. Copy service files
sudo cp systemd/birddetector-capture.service  /etc/systemd/system/
sudo cp systemd/birddetector-dashboard.service /etc/systemd/system/
sudo cp systemd/birddetector.target           /etc/systemd/system/

# 2. Substitute your username (the account that owns the project directory)
sudo sed -i 's/%i/<your-user>/g' \
    /etc/systemd/system/birddetector-capture.service \
    /etc/systemd/system/birddetector-dashboard.service

# 3. Update WorkingDirectory and ExecStart paths if the project is not at
#    /opt/birdid-uk

# 4. Enable and start
sudo systemctl daemon-reload
sudo systemctl enable --now birddetector.target

# Follow logs from both services
journalctl -u birddetector-capture -u birddetector-dashboard -f
```

Manage both services together via the target:

```sh
sudo systemctl start birddetector.target
sudo systemctl stop  birddetector.target
sudo systemctl status birddetector.target
```

---

## 6. Running the dashboard

**Quickest (detector + dashboard together):**

```sh
source venv/bin/activate
python main.py          # open http://localhost:8080
```

**Editing the frontend (Svelte/TypeScript — hot module reload):**

```sh
# Terminal 1
python main.py

# Terminal 2 — Vite dev server; proxies /api/* to :8080
cd dashboard/frontend
npm run dev             # open http://localhost:5173
```

**Editing dashboard backend Python (FastAPI routes — auto-reload):**

```sh
# Terminal 1
source venv/bin/activate
python detect.py

# Terminal 2
uvicorn dashboard.app:app --host 0.0.0.0 --port 8080 --reload
```

---

## 7. Understanding the terminal output

```
INFO  Inference model: birdnet  (window: 3 s)
INFO  BOU filter active — non-BOU species will be suppressed
INFO  Seasonal filter enabled — out-of-season detections will be suppressed
INFO  Nocturnal filter enabled — out-of-hours detections will be suppressed
INFO  Cross-validation enabled — secondary model: perch …
```

Startup messages confirm which filters and models are active.

During operation:

```
INFO  European Robin             0.72
INFO  European Robin             0.81
INFO  European Robin             CONFIRMED (2 hits, best=0.81)
INFO  European Robin             CV AGREE  primary_bto=Robin  secondary=Robin (mean_conf=0.76)
```

| Line | Meaning |
|---|---|
| `0.72` | A candidate detection cleared `min_confidence`; accumulating hits |
| `CONFIRMED` | Required `min_detections` hits reached; deferred save submitted |
| `CV AGREE` | Secondary model confirmed the species; clip will be saved |
| `CV DROP` | Models disagreed; detection discarded |
| `CV FLAG` | Models disagreed; detection saved with `flagged = true` for review |

At `level = "DEBUG"`, suppressed detections are also logged:

```
DEBUG Tawny Owl                        outside active hours — suppressed
DEBUG Fieldfare                        out of season (week 28) — suppressed
```

Every ~60 windows (about 60 seconds) a heartbeat line is logged to confirm
the loop is alive:

```
INFO  [heartbeat] window=120  top: Great Tit 0.41
```

---

## 8. Per-species overrides

Any key from `[defaults]` can be overridden for a specific species.  The
species name must exactly match the common name printed in the terminal.

```toml
# Require higher confidence for a very common species
[species."House Sparrow"]
min_confidence   = 0.90
cooldown_seconds = 90

# Save the first detection of a rare nocturnal species (skip confirmation)
[species."Tawny Owl"]
min_detections = 1

# Flag cross-validation disagreements for manual review instead of dropping
[species."Bittern"]
min_detections = 1
on_disagree    = "flag"

# Lower the confidence threshold for a scarce summer visitor
[species."Common Whitethroat"]
min_confidence = 0.20
min_detections = 1
```

Available override keys: `min_confidence`, `cooldown_seconds`,
`min_detections`, `confirmation_window_seconds`, `on_disagree`.

### Nocturnal filter per-species active-hours override

To change the active window for a specific species without editing the JSON,
add `active_hours` to its `[species."Name"]` block.  Two formats are supported:

```toml
# Dynamic window relative to today's sunrise/sunset (recommended for owls)
[species."Tawny Owl"]
min_detections = 1
active_hours   = {type = "sunset_sunrise", sunset_offset_minutes = -30, sunrise_offset_minutes = 60}

# Fixed clock range spanning midnight
[species."European Nightjar"]
active_hours = {type = "fixed", start = "21:00", end = "04:00"}
```

`sunset_offset_minutes` / `sunrise_offset_minutes`: negative values shift the
window boundary earlier (e.g. `-30` = 30 minutes *before* sunset); positive
values shift it later.

---

## 9. Optional features

### Google Perch v2 inference backend

Perch v2 is a TensorFlow model trained by Google on a much larger dataset than
BirdNET.  It uses 5-second analysis windows and may detect species BirdNET
misses, at the cost of a larger install (~2 GB) and slower inference.

```sh
pip install 'perch-hoplite[tf]'
```

Obtain Kaggle credentials (needed for the first model download only):

1. Go to [kaggle.com/settings](https://www.kaggle.com/settings) and create an
   API token.
2. Save it to `~/.config/kaggle/kaggle.json`:
   ```json
   {"username": "your-username", "key": "your-token"}
   ```

Switch to Perch in `config.toml`:

```toml
[inference]
model = "perch"
```

The model (~400 MB) downloads on first run and is cached in
`~/.cache/kagglehub/`.  Subsequent starts load from the cache.

---

### Dual-model cross-validation

When `[cross_validation] enabled = true`, every confirmed detection from the
primary model is re-evaluated by the secondary model (the one not selected in
`[inference] model`).  **Both BirdNET and Perch must be installed for this to
work.**

```toml
[cross_validation]
enabled        = true
skip_threshold = 0.90   # skip CV when primary confidence is very high
on_disagree    = "drop" # "drop" or "flag"
```

When the two models agree on species, the saved confidence is the arithmetic
mean of both scores.  When they disagree, the detection is dropped (or flagged
for review if `on_disagree = "flag"`).  Detections above `skip_threshold` are
saved immediately without running the secondary model.

Cross-validation substantially reduces false positives.  The cost is roughly
one additional Perch inference per confirmed detection (typically 0.5–1 s on
a Pi 5).

---

### MQTT

Publishes each detection as a JSON message to an MQTT broker.

```sh
pip install paho-mqtt
```

```toml
[mqtt]
enabled  = true
broker   = "192.168.1.100"
port     = 1883
topic    = "birds/detections"
username = "user"   # leave empty if broker has no auth
password = "pass"
retain   = false
```

The JSON payload includes `timestamp`, `species`, `bto_name`, `confidence`,
and `clip_path`.

---

### birdmap.co.uk forwarding

Forwards each detection to [birdmap.co.uk](https://birdmap.co.uk), a
community mapping service for UK bird sightings.

1. Register at birdmap.co.uk and create a station.
2. Copy your API key and station ID into `config.toml`:

```toml
[birdmap]
enabled      = true
api_url      = "https://api.birdmap.co.uk"
api_key      = "bm_your-key-here"
station_id   = 42
upload_audio = true
```

Set `upload_audio = false` to send metadata only (no WAV clip).

---

### PostgreSQL / TimescaleDB

The detector can write to PostgreSQL instead of SQLite.  Note that the
dashboard always reads from the SQLite file — this backend is for the
detector only.

```sh
pip install psycopg2-binary
```

```toml
[database]
type     = "postgresql"
host     = "localhost"
port     = 5432
name     = "birds"
username = "birdsuser"
password = "secret"
```

For TimescaleDB, additionally set `timescaledb = true` — this runs
`create_hypertable` on `detections.timestamp` at init time.

---

## 10. Maintenance

### Log files

Log files rotate automatically per the `[log]` settings.  They are written to
`data/birdid-uk.log` by default alongside stdout.

To watch the live log:

```sh
tail -f data/birdid-uk.log
```

### Audio clips

Clips accumulate in `data/detections/<species>/`.  The `[retention]` cleanup
thread handles automatic purging.  To manually review or export clips:

```sh
ls data/detections/
# data/detections/European Robin/
# data/detections/Blue Tit/
# ...
```

### Regenerating the seasonal filter

The file `uk_seasonal_filter.json` is generated from GBIF Great Britain
occurrence data and committed to the repo.  To regenerate it (e.g. after GBIF
releases new data):

```sh
source venv/bin/activate
python build_uk_seasonal_filter.py
```

This requires internet access to download GBIF occurrence exports.  Edit
`build_uk_seasonal_filter.py` to change the species list, date range, or
week-presence thresholds.

### Database

The SQLite database at `data/birds.db` grows over time.  To reclaim space
after old clips have been cleaned up:

```sh
sqlite3 data/birds.db "VACUUM;"
```

There is no migration framework.  If you need to alter the schema, use
`ALTER TABLE` directly or delete `data/birds.db` to start fresh (clips on
disk are not affected).

---

## 11. Troubleshooting

**No detections at all**

- Check the terminal for `BirdNET inference:` lines — if inference is running
  but nothing passes, lower `[defaults] min_confidence` to `0.3` temporarily.
- Run `python -m sounddevice` and confirm the correct device index is set.
- Try recording a short clip with `arecord -D hw:<device>,0 -d 5 test.wav` and
  play it back to verify the microphone is picking up sound.

**Too many false positives**

- Raise `[defaults] min_confidence` (e.g. `0.75`).
- Raise `[defaults] min_detections` to `3` or `4`.
- Enable `[filter]` high-pass if wind or traffic noise is present.
- Enable cross-validation (`[cross_validation] enabled = true`) — this is the
  most effective single change for reducing false positives.

**A common species is flooding the log**

Add it to the `exclude` list or use a per-species override with a high
confidence threshold and long cooldown:

```toml
[species."Common Wood-Pigeon"]
min_confidence   = 0.95
cooldown_seconds = 300
```

**Clips are very short / missing audio**

In `"window"` clip mode the clip length is `window_pad_seconds` +
model window (3 s for BirdNET).  Increase `window_pad_seconds` to capture more
lead-in, or switch to `clip_mode = "full"` and set `clip_seconds = 15`.

**Cross-validation drops everything**

This means the secondary model (Perch or BirdNET) consistently disagrees with
the primary.  Check:

- Both models are installed and working (run each in isolation by temporarily
  switching `[inference] model` and watching the terminal).
- `[cross_validation] cv_min_confidence` is set to `0.01` (the default).

Alternatively, change `on_disagree = "flag"` to review disagreements in the
dashboard rather than having them silently dropped.

**`out of season` suppressing a species that is present**

The seasonal filter uses GBIF data which may not reflect your specific garden
or an unusually early/late arrival.  Either add per-species overrides in
`uk_seasonal_filter.json` or set `[seasonal_filter] enabled = false`.

**Dashboard shows no data**

- Confirm `data/birds.db` exists and the detector has run at least once.
- The dashboard reads from the SQLite file path set in `[paths] db_path`.
  Make sure the backend was started from the project root directory.
