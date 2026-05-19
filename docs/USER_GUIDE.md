# BirdID-UK — User Guide

Real-time UK garden bird classifier.  A microphone listens continuously,
BirdNET (or Google Perch) analyses overlapping windows, and confirmed
detections are saved as FLAC clips and written to a database.  A FastAPI +
SvelteKit dashboard streams live detections, spectrograms, species photos,
and analytics.

---

## Contents

1. [Requirements](#1-requirements)
2. [Installation](#2-installation)
3. [Find your audio device](#3-find-your-audio-device)
4. [Configuration](#4-configuration)
   - [general](#general)
   - [location](#location)
   - [paths](#paths)
   - [audio — single source](#audio--single-source)
   - [audio — RTSP source](#audio--rtsp-source)
   - [audio — multiple sources](#audio--multiple-sources)
   - [inference](#inference)
   - [defaults](#defaults)
   - [filter](#filter)
   - [seasonal_filter](#seasonal_filter)
   - [nocturnal_filter](#nocturnal_filter)
   - [species_filter](#species_filter)
   - [retention](#retention)
   - [log](#log)
   - [database](#database)
    - [deduplication](#deduplication)
   - [weather](#weather)
   - [mqtt](#mqtt)
   - [birdweather](#birdweather)
   - [birdmap](#birdmap)
   - [cross_validation](#cross_validation)
   - [Per-species overrides](#per-species-overrides)
5. [Running the detector](#5-running-the-detector)
6. [Running as a service](#6-running-as-a-service)
7. [The dashboard](#7-the-dashboard)
8. [Understanding the terminal output](#8-understanding-the-terminal-output)
9. [Maintenance](#9-maintenance)
10. [Developer setup](#10-developer-setup)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Requirements

**Hardware**

- A microphone or USB audio interface positioned outdoors or near a window.
  An omnidirectional condenser mic works well.  A USB interface with a
  directional or parabolic mic increases detection range.
- Any modern Linux machine.  Recommended:
  - Raspberry Pi 4 (2 GB+ RAM) — 1–2 microphones
  - Raspberry Pi 5 — up to 3–4 microphones
  - Any 64-bit x86 server or desktop

**Software**

- Python 3.11 or newer
- Debian/Ubuntu-based OS recommended (the installer uses `apt-get`)

> Node.js is **not** required to run BirdID-UK.  The dashboard frontend is
> pre-built and included in the repository.  Node.js is only needed if you
> want to modify the frontend yourself (see [Developer setup](#10-developer-setup)).

---

## 2. Installation

### One-line install (recommended)

On a fresh machine with `curl` and `git` available:

```sh
curl -fsSL https://raw.githubusercontent.com/andylink/birdid-uk/main/install.sh | bash
```

This clones the repository (you choose the location), installs all
dependencies, and immediately launches the interactive setup wizard to
configure your microphone and location.

### Manual install from a cloned repo

```sh
git clone https://github.com/andylink/birdid-uk.git
cd birdid-uk
bash install.sh
```

### What the installer does

1. Installs system packages (`portaudio19-dev`, `ffmpeg`, etc.) via `apt-get`
2. Creates a Python virtual environment at `venv/`
3. Installs all Python dependencies (this may take several minutes on a Pi)
4. Creates `data/detections/` and `data/species_images/`
5. Copies `config.toml.example` → `config.toml` if none exists
6. Offers to run the **setup wizard** (see below)

> **Raspberry Pi note:** `birdnet-analyzer` includes a compiled C extension.
> On a Pi 4 the first install typically takes 3–5 minutes.

### Setup wizard

The wizard runs automatically at the end of the install (or any time later):

```sh
source venv/bin/activate
python scripts/setup_wizard.py
```

It walks through five steps:

1. **Station details** — name and timezone
2. **Location** — latitude/longitude for sunrise/sunset calculations
3. **Microphone selection** — lists all input devices in a numbered table
4. **Microphone test** — records 3 seconds, shows a live dBFS level bar,
   and optionally plays the recording back so you can verify audio quality
5. **Background service** — optionally installs the systemd units

### Optional: install as a background service only

```sh
bash install.sh --systemd
```

Installs and enables the systemd services so the detector starts
automatically at boot.  See [Running as a service](#6-running-as-a-service)
for details.

### Non-interactive / scripted install

```sh
bash install.sh --no-configure          # install only, skip wizard prompt
bash install.sh --systemd --no-configure  # install + systemd, no wizard
```

---

## 3. Find your audio device

The [setup wizard](#setup-wizard) handles microphone selection interactively.
To list devices manually at any time:

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

Use index `0` to let the system default (PipeWire/PulseAudio) choose.

For RTSP audio sources (IP cameras, network microphones) see
[audio — RTSP source](#audio--rtsp-source) below.

---

## 4. Configuration

All settings live in `config.toml`.  Edit this file before running the
detector.  The minimum you need to change for a new installation are
`[location]` lat/lon and `[audio] device`.

---

### `[general]`

```toml
timezone     = "Europe/London"
station_name = "My Garden"
```

`timezone` must be a valid IANA timezone name.  `"Europe/London"` handles
GMT/BST automatically.  Find your timezone at
[en.wikipedia.org/wiki/List_of_tz_database_time_zones](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).

`station_name` appears in the dashboard header.

---

### `[location]`

```toml
lat = 52.5
lon = -1.5
```

WGS-84 decimal degrees.  Used for sunrise/sunset calculations (nocturnal
filter, dashboard display).  Find your coordinates by right-clicking your
location on [Google Maps](https://maps.google.com) or at
[latlong.net](https://www.latlong.net).

---

### `[paths]`

```toml
detections_dir = "data/detections"
db_path        = "data/birds.db"
```

Relative to the project root.  Change `detections_dir` if you want clips
saved to a different volume such as an external SSD.

---

### `[audio]` — single source

```toml
source         = "sounddevice"
sample_rate    = 48000
hop_seconds    = 1
clip_mode      = "window"
window_pad_seconds = 0.5
device         = 0
```

**`source`** — audio capture backend:

| Value | Description |
|---|---|
| `"sounddevice"` | Local microphone via PortAudio.  Set `device` to the index from `python -m sounddevice`. |
| `"rtsp"` | Network microphone or IP camera via FFmpeg.  Configure `[audio.rtsp]` below. |

**`sample_rate`** — capture rate in Hz.  `48000` works with virtually all
USB audio interfaces.  Both BirdNET and Perch resample internally; this
does not affect inference accuracy.

**`hop_seconds`** — how often the analysis window advances.  At `1`, a new
result is produced every second.

**`clip_mode`** — controls what audio is saved for each detection:

| Mode | Length | Best for |
|---|---|---|
| `"window"` | `window_pad_seconds` + model window (3.5 s for BirdNET) | Disk-efficient; clean single-species clips |
| `"full"` | `clip_seconds` centred on the detection | Manual listening with full context |

`"window"` is the default.  When using `"full"` mode, also set
`clip_seconds`, `pre_capture_seconds`, and `capture_buffer_seconds`.

---

### `[audio]` — RTSP source

Used when `source = "rtsp"`.

```toml
[audio.rtsp]
url                     = "rtsp://192.168.1.100:554/audio"
transport               = "tcp"   # "tcp" (reliable) or "udp" (lower latency)
reconnect_delay_seconds = 5
ffmpeg_path             = "ffmpeg"
```

`ffmpeg` must be installed (`sudo apt-get install ffmpeg`).  Verify the URL
plays with `ffplay rtsp://...` before configuring.

---

### `[audio]` — multiple sources

To run several microphones simultaneously, replace the single `source = ...`
line with one `[[audio.sources]]` block per microphone.  Each source runs
its own independent recording thread and classify loop.

```toml
# Remove or comment out:  source = "sounddevice"

[[audio.sources]]
name   = "garden-north"
type   = "sounddevice"
device = 0

[[audio.sources]]
name      = "garden-south"
type      = "rtsp"
url       = "rtsp://192.168.1.10:554/audio"
transport = "tcp"
reconnect_delay_seconds = 5
```

**Sizing guide (BirdNET, CPU inference):**

| Hardware | Recommended max sources |
|---|---|
| Raspberry Pi 4 | 2 |
| Raspberry Pi 5 | 3–4 |
| Modern x86 (i5+) | 6–8 |

When multiple sources are active, consider enabling
[deduplication](#deduplication) to avoid duplicate records when the same
bird is heard by more than one microphone.

---

### `[inference]`

```toml
model = "birdnet"
```

| Value | Description |
|---|---|
| `"birdnet"` | BirdNET GLOBAL 6K V2.4.  Bundled — no download needed.  3-second analysis windows. |
| `"perch"` | Google Perch v2.  Requires extra install and Kaggle credentials.  5-second windows.  See [optional features](#cross_validation). |

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
a good starting point.  Lower (e.g. `0.4`) if you are missing detections;
raise (e.g. `0.8`) to reduce false positives.

**`cooldown_seconds`** — minimum gap between saved clips for the same
species.  Prevents the database being flooded when a bird sings
continuously.

**`min_detections` / `confirmation_window_seconds`** — a species must
appear at least `min_detections` times within `confirmation_window_seconds`
seconds before a clip is saved.  With `hop_seconds = 1` and
`min_detections = 2`, a species must hit in at least two consecutive windows
within 9 seconds.  Set `min_detections = 1` to save on the first hit.

**`exclude`** — species to permanently suppress regardless of confidence.
Use exact IOC common names as printed in the terminal:

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

A high-pass Butterworth filter applied to audio **before inference only** —
saved clips always contain the original, unfiltered audio.  Removes
low-frequency noise from wind, traffic, and HVAC.  `150 Hz` is safe for all
UK bird species (bird calls start well above this).

---

### `[seasonal_filter]`

```toml
enabled     = true
filter_json = "filters/uk_seasonal_filter.json"
```

Suppresses detections outside a species' expected UK season, derived from
GBIF Great Britain occurrence data (ISO week numbers).  Species absent from
the JSON are treated as year-round.

To regenerate the filter after GBIF publishes new data:

```sh
source venv/bin/activate
python scripts/build_uk_seasonal_filter.py
```

---

### `[nocturnal_filter]`

```toml
enabled     = true
filter_json = "filters/uk_nocturnal_filter.json"
```

Suppresses detections of nocturnal and crepuscular species during daytime.
The bundled filter covers Tawny Owl, Barn Owl, Long-eared Owl, European
Nightjar, Eurasian Woodcock, Corn Crake, and Black-crowned Night Heron.

Two window types are supported in the JSON and in per-species overrides:

| Type | Description |
|---|---|
| `"sunset_sunrise"` | Active from (sunset + offset) to (sunrise + offset).  Handles seasonal variation automatically. |
| `"fixed"` | Fixed local clock range, e.g. `21:00`–`05:00`.  Spans midnight correctly. |

Windows are calculated from `[location]` lat/lon and `[general] timezone`.
See [Per-species overrides](#per-species-overrides) to adjust a species'
window without editing the JSON.

---

### `[species_filter]`

```toml
exclude_status = ["Accidental"]
```

Filters detections against the BOU British List.  Each species on the list
has a `british_list_status` field; any species whose status contains a token
in `exclude_status` is suppressed.

Commonly useful tokens:

| Token | Species affected | Notes |
|---|---|---|
| `"Accidental"` | ~255 vagrant species | No regular UK presence; ideal for a garden detector |
| `"Introduced Breeder"` | 5 species (Pheasant, partridges, etc.) | Non-native, release-dependent |
| `"Escaped Breeder"` | 4 species | Captive-origin feral birds |

Leave `exclude_status = []` to accept all BTO-listed species.

To admit a species that would otherwise be suppressed (e.g. a known local
vagrant), add a per-species override:

```toml
[species."King Eider"]
species_status_override = true
```

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
every `run_interval_seconds` and applies two passes in order:

1. **Age pass** — delete clips older than `max_age_days` (set to `0` to
   disable).
2. **Disk pass** — if disk usage exceeds `max_usage_percent`, delete the
   oldest clips until usage drops below that threshold.

`min_clips_per_species` protects at least that many clips per species from
both passes, so rare birds are not wiped by routine cleanup.

---

### `[log]`

```toml
enabled      = true
path         = "data/birdid-uk.log"
level        = "INFO"
rotation     = "daily"
backup_count = 7
```

**`level`**

| Level | Shows |
|---|---|
| `"INFO"` | Confirmed detections, heartbeat, startup messages |
| `"DEBUG"` | Everything above, plus every BOU/seasonal/nocturnal filter decision |

Use `"DEBUG"` temporarily when diagnosing missing detections.

**`rotation`** — `"daily"` creates a new file at midnight and keeps
`backup_count` previous files.  `"size"` rotates when the file exceeds
`max_size_bytes`.

---

### `[database]`

The default SQLite backend requires no configuration and works out of the
box.  To use PostgreSQL or TimescaleDB instead:

```toml
[database]
type        = "postgresql"
host        = "localhost"
port        = 5432
name        = "birds"
username    = "birdsuser"
password    = "secret"
timescaledb = false   # set true to create a TimescaleDB hypertable
```

Requires `psycopg2-binary` (`pip install psycopg2-binary`).

> Note: the dashboard always reads from the SQLite file regardless of which
> database backend the detector uses.

---

### `[deduplication]`

Only relevant when multiple audio sources are configured.  With a single
source this section has no effect.

```toml
[deduplication]
enabled        = false
window_seconds = 10
on_duplicate   = "flag"
```

When enabled, if the same species is confirmed from **two different sources**
within `window_seconds`, the second detection is treated as a duplicate of
the same bird singing near two microphones.

**`on_duplicate`**

| Value | Behaviour |
|---|---|
| `"flag"` | Save the detection with `deduplicated = true`; hidden in the live feed by default but kept in the database for review. *(Recommended)* |
| `"skip"` | Silently discard; no database row, no clip saved. |

---

### `[weather]`

Attaches a weather snapshot to every saved detection.

```toml
[weather]
enabled       = true
provider      = "open_meteo"
api_key       = ""
cache_seconds = 300
```

**`provider`** options:

| Provider | Cost | API key required |
|---|---|---|
| `"open_meteo"` | Free | No |
| `"yr_no"` | Free | No |
| `"openweathermap"` | Free tier | Yes — sign up at openweathermap.org |
| `"pws"` | — | Depends on plugin |

Weather data is cached for `cache_seconds` so a burst of detections
triggers only a single upstream request.

#### Personal Weather Station (PWS) plugin

Set `provider = "pws"` and choose a plugin via `pws_plugin`:

**Meteobridge** (Davis Vantage Vue and other stations):

```toml
[weather]
provider   = "pws"
pws_plugin = "meteobridge"

[weather.pws_meteobridge]
host            = "192.168.1.100"
port            = 80
username        = "meteobridge"
password        = "meteobridge"
wind_speed_unit = "ms"   # "ms" or "kmh"
```

**WeatherFlow Tempest:**

```toml
[weather]
provider   = "pws"
pws_plugin = "tempest"

[weather.pws_tempest]
station_id = 12345   # numeric ID from tempestwx.com
token      = ""      # personal access token from tempestwx.com
```

---

### `[mqtt]`

Publishes each detection as a JSON message to an MQTT broker.

```toml
[mqtt]
enabled  = true
broker   = "192.168.1.100"
port     = 1883
topic    = "birds/detections"
username = ""
password = ""
retain   = false
```

The JSON payload includes `timestamp`, `species`, `bto_name`, `confidence`,
`source_name`, and `clip_path`.

---

### `[birdweather]`

Forwards detections to [app.birdweather.com](https://app.birdweather.com),
a global citizen-science network for BirdNET stations.

```toml
[birdweather]
enabled      = true
token        = "your-station-token"
upload_audio = true
```

1. Register at [app.birdweather.com](https://app.birdweather.com) and create
   a station.
2. Copy the token from Station → Token on the station settings page.
3. Set `upload_audio = false` to send metadata only (no audio clip).

---

### `[birdmap]`

Forwards detections to [birdmap.co.uk](https://birdmap.co.uk), a UK
community sightings mapping service.

```toml
[birdmap]
enabled      = true
api_url      = "https://birdmap.co.uk"
api_key      = "bm_your-key-here"
station_id   = 42
upload_audio = true
```

Register at birdmap.co.uk to obtain your API key and station ID.

---

### `[cross_validation]`

Re-evaluates each confirmed detection with a second model.  **Requires both
BirdNET and Perch to be installed.**  See
[Google Perch v2](#google-perch-v2) below for the Perch install.

```toml
[cross_validation]
enabled           = true
skip_threshold    = 0.90
on_disagree       = "drop"
cv_min_confidence = 0.01
```

When the two models agree on species, the saved confidence is the arithmetic
mean.  When they disagree:

| `on_disagree` | Behaviour |
|---|---|
| `"drop"` | Discard the detection (maximises precision) |
| `"flag"` | Save with `flagged = true` for manual dashboard review |

`skip_threshold` — if the primary model's confidence is at or above this
value, cross-validation is skipped and the detection is saved immediately.

`cv_min_confidence` — minimum secondary-model confidence to count as a
candidate match.  Keep at `0.01`; Perch softmax scores are inherently much
smaller than BirdNET logistic scores.

---

### Per-species overrides

Any key from `[defaults]` can be overridden for a specific species.  The
name must exactly match the common name printed in the terminal output.

```toml
# Require higher confidence for an abundant species
[species."House Sparrow"]
min_confidence   = 0.90
cooldown_seconds = 120

# Save the first hit for a scarce nocturnal species
[species."Tawny Owl"]
min_detections = 1

# Lower threshold for a scarce but regular visitor
[species."Eurasian Skylark"]
min_confidence = 0.40
min_detections = 1

# Review CV disagreements instead of silently dropping
[species."Bittern"]
min_detections = 1
on_disagree    = "flag"

# Admit a vagrant that would otherwise be blocked by species_filter
[species."King Eider"]
min_confidence          = 0.10
species_status_override = true
```

Available override keys: `min_confidence`, `cooldown_seconds`,
`min_detections`, `confirmation_window_seconds`, `on_disagree`,
`species_status_override`.

#### Nocturnal filter: per-species active-hours override

To adjust an active window without editing the JSON, add `active_hours` to
a `[species."Name"]` block:

```toml
# Dynamic window: 30 min before sunset to 60 min after sunrise
[species."Tawny Owl"]
min_detections = 1
active_hours   = {type = "sunset_sunrise", sunset_offset_minutes = -30, sunrise_offset_minutes = 60}

# Fixed clock range spanning midnight
[species."European Nightjar"]
active_hours = {type = "fixed", start = "21:00", end = "04:00"}
```

Negative `offset_minutes` = before the event; positive = after.

---

## 5. Running the detector

### Combined (detector + dashboard together)

The simplest way to start everything:

```sh
source venv/bin/activate
python main.py
```

Open `http://localhost:8080` (or `http://<your-pi-ip>:8080` from another
device on the network).  Stop with `Ctrl+C`; the detector shuts down cleanly.

Options:

```sh
python main.py --port 9000            # different port
python main.py --host 127.0.0.1       # localhost only
```

### Detector only (headless capture)

```sh
source venv/bin/activate
python detect.py
```

Use this if you want to run the detector without the dashboard, or if you
are running them as separate systemd services.

---

## 6. Running as a service

The `systemd/` directory contains pre-written service files.  If you used
`bash install.sh --systemd` the services are already installed and enabled.

### Manual service installation

```sh
# Copy service files
sudo cp systemd/birdid-uk-capture.service  /etc/systemd/system/
sudo cp systemd/birdid-uk-dashboard.service /etc/systemd/system/
sudo cp systemd/birdid-uk.target            /etc/systemd/system/

# Substitute your Linux username (the account that owns the project directory)
sudo sed -i 's/%i/YOUR_USERNAME/g' \
    /etc/systemd/system/birdid-uk-capture.service \
    /etc/systemd/system/birdid-uk-dashboard.service

# Patch install path if you did not install to /opt/birdid-uk
sudo sed -i 's|/opt/birdid-uk|/home/YOUR_USERNAME/birdid-uk|g' \
    /etc/systemd/system/birdid-uk-capture.service \
    /etc/systemd/system/birdid-uk-dashboard.service

sudo systemctl daemon-reload
sudo systemctl enable --now birdid-uk.target
```

### Managing services

```sh
sudo systemctl start   birdid-uk.target
sudo systemctl stop    birdid-uk.target
sudo systemctl restart birdid-uk.target
sudo systemctl status  birdid-uk.target

# Live logs from each service
journalctl -u birdid-uk-capture   -f
journalctl -u birdid-uk-dashboard -f
journalctl -u birdid-uk-capture -u birdid-uk-dashboard -f
```

---

## 7. The dashboard

The dashboard is served at port 8080 by the FastAPI backend.  Access it in
any browser on your local network:

```
http://<your-pi-ip>:8080
```

**Sections:**

| Section | What it shows |
|---|---|
| Live feed | Detections streamed in real time via SSE.  Each card shows species, confidence, spectrogram, and audio playback. |
| Species | Per-species stats — total detections, best confidence, BTO metadata, BoCC conservation status, Wikimedia photo. |
| Analytics | Hourly activity heatmap, daily trends, top-10 species, BoCC breakdown charts. |

The frontend is pre-built — no Node.js required.

---

## 8. Understanding the terminal output

```
INFO  Inference model: birdnet  (window: 3 s)
INFO  BOU filter active — non-BOU species will be suppressed
INFO  Seasonal filter enabled — out-of-season detections will be suppressed
INFO  Nocturnal filter enabled — out-of-hours detections will be suppressed
INFO  Cross-validation enabled — secondary model: perch
```

Startup messages confirm which filters and models are active.

During operation:

```
INFO  European Robin             0.72
INFO  European Robin             0.81
INFO  European Robin             CONFIRMED  (2 hits, best=0.81)
INFO  European Robin             CV AGREE   primary=Robin  secondary=Robin  (mean_conf=0.76)
```

| Line | Meaning |
|---|---|
| `0.72` | Candidate detection passed `min_confidence`; accumulating hits toward `min_detections` |
| `CONFIRMED` | Required hit count reached; clip is being saved |
| `CV AGREE` | Secondary model confirmed the species; clip saved with mean confidence |
| `CV DROP` | Models disagreed on species; detection discarded |
| `CV FLAG` | Models disagreed; saved with `flagged = true` for manual review |
| `CV SKIP` | Primary confidence above `skip_threshold`; CV not run |

With `level = "DEBUG"`, suppressed detections are also logged:

```
DEBUG Tawny Owl          outside active hours — suppressed
DEBUG Fieldfare          out of season (week 28) — suppressed
DEBUG Ruddy Duck         status=Introduced Breeder — suppressed by species filter
```

A heartbeat line is logged roughly every 60 seconds to confirm the loop is
alive:

```
INFO  [heartbeat] window=120  top: Great Tit 0.41
```

---

## 9. Maintenance

### Log files

```sh
tail -f data/birdid-uk.log
```

Logs rotate automatically per `[log]` settings.

### Audio clips

Clips accumulate in `data/detections/<species>/` as FLAC files.  The
`[retention]` background thread handles automatic purging.  To browse:

```sh
ls data/detections/
# data/detections/European Robin/
# data/detections/Blue Tit/
```

### Database

The SQLite database is at `data/birds.db`.  To reclaim space after old clips
have been purged:

```sh
sqlite3 data/birds.db "VACUUM;"
```

There is no migration framework.  To alter the schema use `ALTER TABLE`
directly, or delete `data/birds.db` to start fresh (clips on disk are
unaffected).

### Regenerating the seasonal filter

The bundled `filters/uk_seasonal_filter.json` is derived from GBIF Great
Britain occurrence data.  To regenerate it after GBIF publishes new data:

```sh
source venv/bin/activate
python scripts/build_uk_seasonal_filter.py
```

Requires internet access to download GBIF occurrence exports.

---

## 10. Developer setup

If you want to modify the SvelteKit frontend you need Node.js 20+.

```sh
cd dashboard/frontend
npm install
npm run dev      # Vite dev server with HMR at http://localhost:5173
npm run build    # production build → dist/
npm run check    # TypeScript type-check
```

The Vite dev server proxies `/api/v1`, `/stream`, and `/audio` to
`localhost:8080`, so the backend must be running separately:

```sh
# Terminal 1 — detector
source venv/bin/activate
python detect.py

# Terminal 2 — dashboard API (auto-reload on Python changes)
source venv/bin/activate
uvicorn dashboard.app:app --host 0.0.0.0 --port 8080 --reload

# Terminal 3 — frontend (auto-reload on Svelte/TS changes)
cd dashboard/frontend
npm run dev
```

### Google Perch v2

Perch uses 5-second analysis windows and may detect species BirdNET misses,
at the cost of a larger install (~2 GB TensorFlow) and slower inference.

```sh
source venv/bin/activate
pip install 'perch-hoplite[tf]'
```

Obtain Kaggle credentials (required for the first model download only):

1. Go to [kaggle.com/settings](https://www.kaggle.com/settings) → API →
   Create New Token.
2. Save the downloaded file to `~/.config/kaggle/kaggle.json`:
   ```json
   {"username": "your-username", "key": "your-token"}
   ```

Switch to Perch in `config.toml`:

```toml
[inference]
model = "perch"
```

The model (~400 MB) downloads on first run and is cached in
`~/.cache/kagglehub/`.  Enable cross-validation to use both models together
(see [`[cross_validation]`](#cross_validation)).

---

## 11. Troubleshooting

**No detections at all**

- Check the terminal for inference lines.  If nothing passes, temporarily
  lower `min_confidence` to `0.3`.
- Run `python -m sounddevice` and confirm the correct device index is set.
- Record a short test clip to verify the microphone is working:
  ```sh
  arecord -D hw:1,0 -d 5 -f cd test.wav && aplay test.wav
  ```
  Replace `hw:1,0` with your device's ALSA identifier.
- Check `[seasonal_filter]` is not suppressing the species.  Set
  `level = "DEBUG"` in `[log]` to see filter decisions.

**Too many false positives**

- Raise `[defaults] min_confidence` (e.g. `0.75`).
- Raise `[defaults] min_detections` to `3` or `4`.
- Enable `[filter]` high-pass if wind or traffic noise is present.
- Enable `[cross_validation]` — this is the most effective single change for
  reducing false positives (requires Perch).

**A common species is flooding the log**

Add it to the global `exclude` list or use a per-species override:

```toml
[species."Common Wood-Pigeon"]
min_confidence   = 0.95
cooldown_seconds = 300
```

**Clips are very short / missing lead-in audio**

In `"window"` clip mode the clip is `window_pad_seconds` + model window
(3 s for BirdNET = 3.5 s total by default).  Increase `window_pad_seconds`
to capture more, or switch to `clip_mode = "full"` with `clip_seconds = 15`.

**Cross-validation drops almost everything**

- Confirm both models are installed and working by temporarily switching
  `[inference] model` to each one and watching the terminal.
- Ensure `cv_min_confidence = 0.01` (the default).  Perch softmax scores
  over ~10 000 classes are far smaller than BirdNET logistic scores.
- Switch to `on_disagree = "flag"` to review disagreements in the dashboard
  rather than discarding them.

**A species is suppressed as `out of season`**

The seasonal filter uses GBIF data that may not reflect unusual arrivals or
your specific location.  Add a seasonal override in
`filters/uk_seasonal_filter.json` or set `[seasonal_filter] enabled = false`.

**Dashboard shows no data / blank page**

- Confirm the backend is running: `curl http://localhost:8080/healthz`
- Confirm `data/birds.db` exists and the detector has run at least once.
- Ensure the backend was started from the project root directory so relative
  paths in `[paths]` resolve correctly.
- Check the browser console for network errors (F12 → Console).

**`[deduplication]` is flagging genuine detections**

Increase `window_seconds` or switch `on_duplicate = "flag"` so you can
review them in the database rather than losing them:

```toml
[deduplication]
window_seconds = 5    # tighten the window
on_duplicate   = "flag"
```
