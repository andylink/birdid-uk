"""
birdmap.py — fire-and-forget uploader for birdmap.co.uk

After each detection, call ``post_detection()`` once.  The function returns
immediately; the HTTP POST runs on a daemon thread and is silently dropped
on any network or server error.

Controlled entirely by the ``[birdmap]`` section of config.toml::

    [birdmap]
    enabled      = true
    api_url      = "https://api.birdmap.co.uk"
    api_key      = "bm_xxxxxxxxxxxx..."
    station_id   = "norfolk-garden"
    upload_audio = true

Set ``enabled = false`` (the default) to disable without removing the
section.  When disabled, ``post_detection()`` is a no-op and no network
activity occurs.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from config import cfg

logger = logging.getLogger(__name__)

_SOURCE = "bird-detector/1.0"
_MAX_AUDIO_BYTES = 2 * 1024 * 1024  # 2 MB


def post_detection(
    ts: datetime,
    species: str,
    confidence: float,
    clip_path: Path | None,
) -> None:
    """Schedule a background POST to birdmap.co.uk and return immediately.

    Silently no-ops if ``cfg.birdmap.enabled`` is ``False`` or if any error
    occurs during transmission (network unavailable, bad credentials, etc.).

    Args:
        ts:         Timestamp of the detection (naive or aware datetime).
        species:    Detected species common name.
        confidence: Detection confidence in the range 0.0–1.0.
        clip_path:  Path to the saved FLAC clip, or None if not saved.
    """
    if not cfg.birdmap.enabled:
        return
    threading.Thread(
        target=_send,
        args=(ts, species, confidence, clip_path),
        daemon=True,
    ).start()


def _send(
    ts: datetime,
    species: str,
    confidence: float,
    clip_path: Path | None,
) -> None:
    """Blocking HTTP POST — runs on a daemon thread; all exceptions are caught."""
    try:
        bm = cfg.birdmap

        # Optionally base64-encode the audio clip
        audio_b64: str | None = None
        if bm.upload_audio and clip_path and clip_path.exists():
            size = clip_path.stat().st_size
            if size <= _MAX_AUDIO_BYTES:
                audio_b64 = base64.b64encode(clip_path.read_bytes()).decode()
            else:
                logger.debug(
                    "birdmap: clip too large to upload (%d B > %d B), skipping audio",
                    size,
                    _MAX_AUDIO_BYTES,
                )

        # Normalise timestamp to UTC ISO 8601 with Z suffix
        if ts.tzinfo is None:
            ts_utc = ts.astimezone(timezone.utc)
        else:
            ts_utc = ts.astimezone(timezone.utc)
        timestamp = ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        payload: dict = {
            "station_id": bm.station_id,
            "timestamp": timestamp,
            "species": species,
            "confidence": round(float(confidence), 4),
            "lat": None,
            "lon": None,
            "source_software": _SOURCE,
        }
        if audio_b64 is not None:
            payload["audio"] = audio_b64

        data = json.dumps(payload).encode()
        url = f"{bm.api_url.rstrip('/')}/api/v1/detections"

        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": bm.api_key,
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 201):
                logger.debug(
                    "birdmap: posted %s %.2f → HTTP %d", species, confidence, resp.status
                )
            else:
                logger.warning("birdmap: unexpected HTTP %d for %s", resp.status, species)

    except urllib.error.HTTPError as exc:
        logger.warning("birdmap: HTTP %d posting %s: %s", exc.code, species, exc.reason)
    except urllib.error.URLError as exc:
        logger.debug("birdmap: network error posting %s: %s", species, exc.reason)
    except Exception as exc:  # noqa: BLE001
        logger.debug("birdmap: unexpected error posting %s: %s", species, exc)
