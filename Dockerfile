# ── BirdID-UK Dockerfile ──────────────────────────────────────────────────────
#
# Multi-stage build:
#   1. frontend  — Node.js build of the SvelteKit dashboard
#   2. app       — Python runtime with compiled frontend baked in
#
# Audio source options inside a container:
#   - "rtsp"        — recommended; point at an IP camera/mic stream (no device passthrough needed)
#   - "sounddevice" — requires --device /dev/snd and privileged access to the host sound system
#
# ── Stage 1: build the SvelteKit frontend ─────────────────────────────────────
FROM node:22-slim AS frontend

WORKDIR /build/dashboard/frontend

COPY dashboard/frontend/package*.json ./
RUN npm ci

COPY dashboard/frontend/ ./
RUN npm run build


# ── Stage 2: Python runtime ────────────────────────────────────────────────────
FROM python:3.12-slim AS app

# System packages:
#   portaudio19-dev  — PortAudio headers for sounddevice (USB mic support)
#   ffmpeg           — required for RTSP audio streams
#   libsndfile1      — soundfile / librosa dependency
#   curl             — healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        portaudio19-dev \
        ffmpeg \
        libsndfile1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies before copying source (better layer caching)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Bake in the pre-built frontend (overwrite the empty/dev dist directory)
COPY --from=frontend /build/dashboard/frontend/dist/ ./dashboard/frontend/dist/

# Runtime data directories (will normally be bind-mounted or named volumes)
RUN mkdir -p data/detections data/spectrograms

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -sf http://localhost:8080/api/detections?limit=1 || exit 1

# Default: combined detector + dashboard process
# Override CMD or use docker-compose to run detect.py (detector only) instead
CMD ["python", "main.py", "--host", "0.0.0.0", "--port", "8080"]
