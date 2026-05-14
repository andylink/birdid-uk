# BirdID-UK

Real-time garden bird classifier for Raspberry Pi and Linux servers. Records audio continuously, runs BirdNET inference on a sliding window, and serves a live detection dashboard in your browser.

- **BirdNET GLOBAL 6K V2.4** inference (Google Perch v2 optional)
- UK-focused: BOU/BTO species allowlist, GBIF-derived seasonal filter, nocturnal/crepuscular time-of-day gate
- Live dashboard with species cards, spectrograms, analytics, and SSE-streamed detections
- FLAC clip recording, automatic retention management
- Optional: MQTT publish, BirdWeather forwarding, cross-validation with a second model, multi-microphone support

---

## Requirements

| Requirement | Notes |
|---|---|
| Python 3.11+ | 3.12 works; 3.10 and below do not |
| PortAudio | `portaudio19-dev` on Debian/Ubuntu |
| Microphone | USB recommended; any PortAudio device works |
| RAM | 1 GB minimum; 2 GB+ recommended on Pi 4/5 |
| Disk | 1 GB+ free for clips (configurable retention) |

Raspberry Pi 4 (2 GB+) and Pi 5 are the primary targets. Any 64-bit Debian/Ubuntu-based Linux works.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/andylink/birdid-uk.git
cd birdid-uk
```

### 2. Run the installer

```bash
bash install.sh
```

This will:
- Install system packages (`portaudio19-dev`, `ffmpeg`, etc.) via `apt-get`
- Create a Python virtual environment at `venv/`
- Install all Python dependencies
- Create `data/detections/` and `data/species_images/` directories
- Copy `config.toml.example` → `config.toml` (if not already present)

> **Raspberry Pi note:** `birdnet-analyzer` includes a C extension that compiles from source. On a Pi 4 this typically takes 3–5 minutes on the first install.

To also install and enable systemd services for running at boot:

```bash
bash install.sh --systemd
```

### 3. Configure

Edit `config.toml` — at minimum, set these three values:

```toml
[general]
timezone     = "Europe/London"   # your IANA timezone
station_name = "My Garden"

[location]
lat = 52.5    # your latitude  (https://www.latlong.net)
lon = -1.5    # your longitude

[audio]
device = 0    # run: python -m sounddevice  to find your mic index
```

See [Configuration reference](#configuration-reference) below for all options.

### 4. Run

```bash
source venv/bin/activate
python main.py
```

Open the dashboard at `http://<your-pi-ip>:8080` in a browser.

---

## Finding your microphone

```bash
source venv/bin/activate
python -m sounddevice
```

This lists all available audio devices with their index numbers. Set `device = N` in `config.toml` under `[audio]`.

For RTSP audio sources (IP cameras or network microphones), set `source = "rtsp"` and configure `[audio.rtsp]`.

---

## Running as a service (systemd)

If you ran `bash install.sh --systemd`, the service is already enabled. Otherwise:

```bash
sudo cp systemd/birddetector-*.service systemd/birddetector.target /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now birddetector.target
```

Useful commands:

```bash
sudo systemctl status birddetector.target
journalctl -u birddetector-capture -f    # detector logs
journalctl -u birddetector-dashboard -f  # dashboard logs
sudo systemctl stop birddetector.target
```

---

## Configuration reference

All settings live in `config.toml`. The file is extensively commented. Key sections:

| Section | Purpose |
|---|---|
| `[general]` | Timezone and station name |
| `[location]` | Latitude/longitude for sunrise/sunset calculations |
| `[audio]` | Microphone device, sample rate, clip mode, RTSP |
| `[inference]` | Model selection (`birdnet` or `perch`) |
| `[defaults]` | Confidence threshold, cooldown, confirmation filter |
| `[seasonal_filter]` | GBIF-derived week-by-week species presence |
| `[nocturnal_filter]` | Time-of-day gate for owls, nightjars, etc. |
| `[species_filter]` | BOU/BTO allowlist and `exclude_status` tokens |
| `[retention]` | Automatic clip cleanup by age and disk usage |
| `[mqtt]` | Publish detections to an MQTT broker |
| `[birdweather]` | Forward detections to app.birdweather.com |
| `[cross_validation]` | Dual-model agreement check (requires Perch) |
| `[weather]` | Attach weather metadata to detections |
| `[species."Name"]` | Per-species confidence/cooldown overrides |

### Tuning detection sensitivity

```toml
[defaults]
min_confidence   = 0.6    # lower = more detections, more false positives
min_detections   = 2      # hits required within confirmation_window_seconds
cooldown_seconds = 30     # minimum gap between clips of the same species
```

### Suppressing common species

```toml
[defaults]
exclude = ["Common Wood-Pigeon", "Carrion Crow"]
```

Or lower sensitivity per-species:

```toml
[species."House Sparrow"]
min_confidence   = 0.75
cooldown_seconds = 120
```

---

## Multiple microphones

Set up `[[audio.sources]]` blocks instead of a single `source =` line:

```toml
[[audio.sources]]
name = "garden-east"
type = "sounddevice"
device = 0

[[audio.sources]]
name = "garden-west"
type = "rtsp"
url  = "rtsp://192.168.1.10:554/audio"
```

Pi 4 handles 2 sources comfortably. Pi 5 can manage 3–4.

---

## Optional: Google Perch v2 model

Perch uses 5-second windows and eBird labels. It requires TensorFlow and a Kaggle account:

```bash
pip install 'perch-hoplite[tf]'
# place Kaggle API token at ~/.config/kaggle/kaggle.json
```

Then in `config.toml`:

```toml
[inference]
model = "perch"
```

The model (~400 MB) downloads automatically on first run and is cached in `~/.cache/kagglehub/`.

---

## Dashboard

The dashboard is served by FastAPI at port 8080. It provides:

- **Live feed** — SSE-streamed detections with spectrograms and audio playback
- **Species** — per-species stats, BTO metadata, Wikimedia photos, BoCC conservation status
- **Analytics** — hourly activity, top species, BoCC breakdown, daily trends

The frontend is pre-built in this repository — no Node.js required to run it.

---

## Developer setup

To modify the frontend you need Node.js 20+:

```bash
cd dashboard/frontend
npm install
npm run dev          # Vite dev server, proxies API to localhost:8080
npm run build        # production build → dist/
npm run check        # type-check
```

The API backend must be running separately when using the Vite dev server:

```bash
source venv/bin/activate
uvicorn dashboard.app:app --host 0.0.0.0 --port 8080 --reload
```

---

## Licence

MIT
