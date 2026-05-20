# Docker Compose Installation

This guide covers running BirdID-UK as a Docker container using Docker Compose.

## Prerequisites

- [Docker Engine](https://docs.docker.com/engine/install/) 24+ and [Docker Compose](https://docs.docker.com/compose/install/) v2
- An audio source reachable from the container:
  - **RTSP stream** (recommended) — any IP camera or network microphone
  - **USB microphone** — requires extra device passthrough (see below)

---

## Quick start

### 1. Configure

Copy the Docker config template and edit it:

```bash
cp docker/config.docker.toml config.toml
```

At minimum set:

| Section | Key | Description |
|---|---|---|
| `[general]` | `timezone` | IANA timezone, e.g. `Europe/London` |
| `[location]` | `lat`, `lon` | Your WGS-84 coordinates |
| `[audio]` | `source` | `"rtsp"` or `"sounddevice"` |
| `[audio.rtsp]` | `url` | Your RTSP stream URL |
| `[admin]` | `password_hash`, `session_secret` | See below |

Generate the admin credentials:

```bash
# bcrypt password hash
python3 -c "from passlib.hash import bcrypt; print(bcrypt.hash('your-password'))"

# random session secret
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Build and start

```bash
docker compose up -d --build
```

First build takes a few minutes (installs Python dependencies and builds the frontend). Subsequent starts are fast.

### 3. Open the dashboard

```
http://localhost:8080
```

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
device = 0   # run `python -m sounddevice` on the host to find the right index
```

---

## Optional services

### MQTT broker (Mosquitto)

Uncomment the `mosquitto` service block in `docker-compose.yml` and the `depends_on` entry under `birdid`. In `config.toml`:

```toml
[mqtt]
enabled = true
broker  = "mosquitto"   # container service name resolves automatically
port    = 1883
topic   = "birds/detections"
```

### PostgreSQL / TimescaleDB

Uncomment the `postgres` service block and its `depends_on` entry. In `config.toml`:

```toml
[database]
type     = "postgresql"
host     = "postgres"      # Docker Compose service name
port     = 5432
name     = "birds"
username = "birdid"
password = "changeme"      # match POSTGRES_PASSWORD in docker-compose.yml
```

---

## Data persistence

All runtime data (SQLite database, audio clips, spectrograms, logs) is stored in the `birdid_data` named Docker volume, mounted at `/app/data` inside the container.

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

# Stop everything
docker compose down

# Stop and remove data volumes (destructive!)
docker compose down -v

# Rebuild after code changes
docker compose up -d --build
```

---

## Upgrading

```bash
git pull
docker compose up -d --build
```

The `birdid_data` volume is preserved across rebuilds; no data is lost.

---

## Troubleshooting

**Container exits immediately**
Check logs: `docker compose logs birdid`. The most common cause is a missing or invalid `config.toml`.

**No detections / audio errors**
- RTSP: verify the stream URL is reachable from the host (`ffplay rtsp://...`).
- sounddevice: confirm the correct device index and that `/dev/snd` is passed through.

**Dashboard shows "no data"**
The BirdNET model loads on startup. Wait ~60 seconds after first start before expecting detections.

**Permission denied on `/dev/snd`**
Ensure the container has the `audio` group (`group_add: [audio]`) and the device is mounted.
