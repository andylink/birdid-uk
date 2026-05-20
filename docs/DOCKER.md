# Docker Compose Installation

This guide covers running BirdID-UK as a Docker container using Docker Compose.
No local copy of the source code is required — the pre-built image is pulled
automatically from GitHub Container Registry (GHCR).

## Prerequisites

- [Docker Engine](https://docs.docker.com/engine/install/) 24+ and [Docker Compose](https://docs.docker.com/compose/install/) v2
- An audio source reachable from the container:
  - **RTSP stream** (recommended) — any IP camera or network microphone
  - **USB microphone** — requires extra device passthrough (see below)

---

## Installation

### 1. Download the two required files

You only need `docker-compose.yml` and the config template — no source checkout needed.

```bash
curl -O https://raw.githubusercontent.com/andylink/birdid-uk/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/andylink/birdid-uk/main/docker/config.docker.toml
mv config.docker.toml config.toml
```

### 2. Edit config.toml

Open `config.toml` and set at minimum:

| Section | Key | Description |
|---|---|---|
| `[general]` | `timezone` | IANA timezone, e.g. `Europe/London` |
| `[location]` | `lat`, `lon` | Your WGS-84 coordinates ([find yours](https://www.latlong.net)) |
| `[audio]` | `source` | `"rtsp"` (recommended) or `"sounddevice"` |
| `[audio.rtsp]` | `url` | Your RTSP stream URL |
| `[admin]` | `password_hash`, `session_secret` | See below |

**Generate admin credentials** — requires Python 3 with `bcrypt` installed, or
you can leave both fields empty to disable auth entirely:

```bash
# bcrypt password hash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'your-password', bcrypt.gensalt()).decode())"

# random session secret
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Paste the output values into `config.toml`:

```toml
[admin]
password_hash  = "$2b$12$..."
session_secret = "abc123..."
```

### 3. Start the container

```bash
docker compose up -d
```

Docker pulls the image from GHCR automatically on first run (~1–2 GB download).
Subsequent starts are instant.

### 4. Open the dashboard

```
http://localhost:8080
```

The BirdNET model loads on startup — allow ~60 seconds before expecting detections.

---

## Audio source options

### RTSP stream (recommended)

No host device passthrough is needed. Set in `config.toml`:

```toml
[audio]
source = "rtsp"

[audio.rtsp]
url = "rtsp://192.168.1.100:554/audio"
```

### USB microphone

Uncomment the `devices` and `group_add` lines in `docker-compose.yml`:

```yaml
devices:
  - /dev/snd:/dev/snd
group_add:
  - audio
```

Set in `config.toml`:

```toml
[audio]
source = "sounddevice"
device = 0   # run `python -m sounddevice` on the host to find the correct index
```

---

## Optional services

### MQTT broker (Mosquitto)

Uncomment the `mosquitto` service block in `docker-compose.yml` and the
`depends_on` entry under `birdid`. Download the bundled Mosquitto config:

```bash
mkdir -p docker
curl -o docker/mosquitto.conf \
  https://raw.githubusercontent.com/andylink/birdid-uk/main/docker/mosquitto.conf
```

In `config.toml`:

```toml
[mqtt]
enabled = true
broker  = "mosquitto"   # Docker Compose service name — resolves automatically
port    = 1883
topic   = "birds/detections"
```

### PostgreSQL / TimescaleDB

Uncomment the `postgres` service block and its `depends_on` entry in
`docker-compose.yml`. In `config.toml`:

```toml
[database]
type     = "postgresql"
host     = "postgres"      # Docker Compose service name
port     = 5432
name     = "birds"
username = "birdid"
password = "changeme"      # must match POSTGRES_PASSWORD in docker-compose.yml
```

---

## Data persistence

All runtime data (SQLite database, audio clips, spectrograms, logs) is stored
in the `birdid_data` named Docker volume, mounted at `/app/data` inside the
container. Data is preserved across container restarts and upgrades.

To use a host directory instead, replace the volume entry in `docker-compose.yml`:

```yaml
volumes:
  - /opt/birdid-uk/data:/app/data
```

---

## Common commands

```bash
# View live logs
docker compose logs -f birdid

# Restart after editing config.toml
docker compose restart birdid

# Stop everything (data preserved)
docker compose down

# Stop and delete all data (destructive!)
docker compose down -v
```

---

## Upgrading

Pull the latest image and restart:

```bash
docker compose pull
docker compose up -d
```

The `birdid_data` volume is preserved; no data is lost.

To pin to a specific release instead of `latest`, edit the `image:` line in
`docker-compose.yml`:

```yaml
image: ghcr.io/andylink/birdid-uk:v0.1.0
```

---

## Troubleshooting

**Container exits immediately**
Check logs: `docker compose logs birdid`. The most common cause is a missing
or invalid `config.toml`.

**Image pull fails (`unauthorized` or `not found`)**
The GHCR package may not be public yet. Check:
`https://github.com/andylink?tab=packages` — the `birdid-uk` package visibility
should be set to **Public**.

**No detections / audio errors**
- RTSP: verify the stream URL is reachable from the host with `ffplay rtsp://...`
- sounddevice: confirm the correct device index and that `/dev/snd` is passed through

**Dashboard loads but shows no data**
The BirdNET model loads on startup. Wait ~60 seconds after first start.

**Permission denied on `/dev/snd`**
Ensure the container has the `audio` group (`group_add: [audio]`) and the
device is mounted (`devices: [/dev/snd:/dev/snd]`).
