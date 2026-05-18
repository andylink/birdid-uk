# BirdID-UK

<p align="center">
  <em>Real-time UK garden bird classifier for Raspberry Pi and Linux</em>
</p>

<p align="center">
  <a href="https://github.com/andylink/birdid-uk/releases">
    <img src="https://img.shields.io/github/v/release/andylink/birdid-uk?include_prereleases&style=flat-square&color=blue" alt="Latest release">
  </a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-green?style=flat-square&logo=python" alt="Python 3.11+">
  <img src="https://badgen.net/badge/OS/Linux%20%2F%20Raspberry%20Pi/blue" alt="Linux / Raspberry Pi">
  <a href="https://github.com/andylink/birdid-uk/actions">
    <img src="https://img.shields.io/github/actions/workflow/status/andylink/birdid-uk/tests.yml?style=flat-square&label=tests" alt="Tests">
  </a>
</p>

BirdID-UK listens to your garden through a microphone, identifies bird calls in real time using AI, and streams confirmed detections to a live web dashboard — all running locally on a Raspberry Pi.

---

## Features

**Detection pipeline**
- Continuous 24/7 audio capture from USB microphones or RTSP IP camera streams
- AI inference using **BirdNET GLOBAL 6K V2.4** (3-second sliding windows)
- Optional **Google Perch v2** as an alternative or cross-validation model
- Butterworth high-pass filter to reduce wind and traffic noise before inference
- Confirmation filter — requires multiple hits within a configurable window to suppress false positives
- Per-species configurable confidence thresholds, cooldowns, and detection counts

**UK-specific filtering stack**
1. **BOU allowlist** — enforces the British Ornithologists' Union British List; approximately 255 vagrant species suppressed by default
2. **Seasonal filter** — species excluded outside their expected UK season using GBIF ISO-week occurrence data
3. **Nocturnal filter** — owls, nightjars and similar species gated to appropriate hours via astronomical sunset/sunrise calculations
4. **Privacy filter** — Silero VAD neural network discards any clip containing human speech before saving

**Multi-source audio**
- Up to 8 simultaneous microphones or RTSP streams
- Cross-source deduplication prevents duplicate database entries for the same bird

**Live web dashboard** (FastAPI + SvelteKit)
- Real-time detection feed via Server-Sent Events — no page refresh needed
- Each card shows species name, confidence score, spectrogram, and audio playback
- Species browser with BTO metadata, BoCC conservation status, and photos
- Analytics: hourly heatmap, daily trends, top-10 species, conservation status breakdown
- Served on port 8080; Node.js is **not** required at runtime

**Integrations**
- **MQTT** — publishes each detection as JSON to any MQTT broker
- **BirdWeather** — forwards detections and audio to [app.birdweather.com](https://app.birdweather.com)
- **BirdMap UK** — forwards detections to [birdmap.co.uk](https://birdmap.co.uk)
- **Weather metadata** — attaches conditions to every detection row (Open-Meteo, OpenWeatherMap, Yr.no, WeatherFlow Tempest, or Meteobridge)

**Storage and operations**
- SQLite (default, zero-config) or PostgreSQL / TimescaleDB
- Audio clips saved as FLAC in `data/detections/`
- Automatic retention management — age-based and disk-usage-based cleanup with a configurable per-species minimum
- systemd service units for production deployment with automatic restart

---

## Requirements

**Hardware**
- A microphone positioned outdoors or near a window — an omnidirectional USB condenser mic works well
- Any modern 64-bit Linux machine:
  - Raspberry Pi 4 (2 GB+ RAM) — 1–2 microphones
  - Raspberry Pi 5 — 3–4 microphones
  - Any 64-bit x86 server or desktop

**Software**
- Python 3.11 or newer
- Debian / Ubuntu-based OS (the installer uses `apt-get`)

---

## Installation

### One-line install (recommended)

```sh
curl -fsSL https://raw.githubusercontent.com/andylink/birdid-uk/main/install.sh | bash
```

This clones the repository, installs all system and Python dependencies, and launches an interactive setup wizard to configure your microphone, location, and timezone.

### Manual install

```sh
git clone https://github.com/andylink/birdid-uk.git
cd birdid-uk
bash install.sh
```

### What the installer does

1. Installs system packages (`portaudio19-dev`, `ffmpeg`, etc.) via `apt-get`
2. Creates a Python virtual environment at `venv/`
3. Installs all Python dependencies — this may take several minutes on a Raspberry Pi
4. Creates `data/detections/` and `data/species_images/`
5. Copies `config.toml.example` → `config.toml` if no config exists
6. Runs the interactive setup wizard

---

## Configuration

Configuration lives entirely in `config.toml`. Copy the annotated template to get started:

```sh
cp config.toml.example config.toml
```

Key settings:

```toml
[general]
timezone     = "Europe/London"   # handles GMT/BST automatically
station_name = "My Garden"

[location]
lat = 52.5    # decimal degrees — used for sunrise/sunset filtering
lon = -1.5

[audio]
source      = "sounddevice"   # or "rtsp" for IP camera audio
sample_rate = 48000
hop_seconds = 1               # analysis window advance step

[inference]
model = "birdnet"             # "birdnet", "perch", or "both"

[filter]
confidence = 0.7              # minimum score to record a detection
```

Run `python -m sounddevice` to list available audio device indices.

See [docs/USER_GUIDE.md](docs/USER_GUIDE.md) for the complete configuration reference.

---

## Running

**Combined detector + dashboard (development)**

```sh
source venv/bin/activate
python main.py
```

Open `http://localhost:8080` in a browser.

**Detector only (headless)**

```sh
source venv/bin/activate
python detect.py
```

**As systemd services (production)**

The installer can set up two independent services that start at boot:

```sh
sudo systemctl enable --now birdid-uk.target
```

- `birdid-uk-capture.service` — runs the detector daemon
- `birdid-uk-dashboard.service` — runs the web dashboard

---

## Dashboard

The dashboard provides a live view of detections as they happen, with audio playback and spectrograms for each bird identified. The species browser includes British conservation status (BoCC Red/Amber/Green) and BTO metadata. The analytics page shows detection patterns over time.

---

## Google Perch (optional)

Google Perch v2 can be used instead of or alongside BirdNET as a cross-validation model. It requires Kaggle credentials to download the model weights on first run:

1. Create a free account at [kaggle.com](https://kaggle.com) and generate an API token
2. Save the token to `~/.config/kaggle/kaggle.json`, or export `KAGGLE_USERNAME` and `KAGGLE_KEY` as environment variables
3. Set `model = "perch"` or `model = "both"` in `[inference]` in your `config.toml`

The model is downloaded automatically on the first inference run.

---

## Related Projects

- [BirdNET-Analyzer](https://github.com/birdnet-team/BirdNET-Analyzer) — upstream project providing the BirdNET AI model used for bird sound identification
- [BirdNET-Go](https://github.com/tphakala/birdnet-go) — Go implementation of a BirdNET-based continuous monitoring system

---

## Attributions

**BirdNET GLOBAL 6K V2.4** is developed by the K. Lisa Yang Center for Conservation Bioacoustics at the Cornell Lab of Ornithology in collaboration with Chemnitz University of Technology.
Stefan Kahl, Connor Wood, Maximilian Eibl, Holger Klinck.

> S. Kahl, C. M. Wood, M. Eibl, H. Klinck, *BirdNET: A deep learning solution for avian diversity monitoring*, Ecological Informatics, 2021.

**Google Perch v2** is a bird sound embedding model developed by Google Research. When enabled, the model weights are downloaded from the [Kaggle perch-hoplite dataset](https://www.kaggle.com/models/google/bird-vocalization-classifier).

**Seasonal filter data** is derived from [GBIF](https://www.gbif.org) occurrence data for Great Britain (open data, CC BY 4.0).

**Species metadata** (BOU status, BoCC conservation ratings) is sourced from the [British Trust for Ornithology (BTO)](https://www.bto.org).

---

## License

This project is released under the [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-nc-sa/4.0/) licence, consistent with the non-commercial licence of the BirdNET model on which it depends.

---

## Author

Andy ([andylink](https://github.com/andylink))
