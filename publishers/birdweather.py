"""
birdweather.py — Uploads bird detections to app.birdweather.com.

Call post_detection() after each confirmed detection. It returns immediately;
the HTTP work runs on a daemon thread and errors are silently logged so the
classify loop is never interrupted.

Each detection is posted in two steps:
1. If upload_audio = true and the FLAC clip exists, POST the audio to the
   soundscapes endpoint and capture the returned soundscapeId.
2. POST the detection metadata (including the soundscapeId if step 1 succeeded)
   to the detections endpoint.

Scientific names are resolved from the BirdNET labels file (IOC common names)
and supplemented by filters/uk_species_filter.json for BTO British-name aliases.
If a species can't be resolved, it's posted without a scientificName field.

Configure in config.toml:

    [birdweather]
    enabled      = true
    token        = "your-station-token"   # from app.birdweather.com → Station → Token
    upload_audio = true                   # upload FLAC clip as a soundscape (recommended)

Set enabled = false (the default) to disable. When disabled, post_detection()
does nothing and no network requests are made.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from config import cfg

logger = logging.getLogger(__name__)

_API_BASE = "https://app.birdweather.com"

# ---------------------------------------------------------------------------
# Scientific-name lookup — built once from filters/uk_species_filter.json
# ---------------------------------------------------------------------------

def _build_sci_name_map() -> dict[str, str]:
    """Build a {common_name_lower: scientific_name} lookup from two sources.

    Source 1 — uk_species_filter.json: covers BTO British names and
    international_english_name aliases.

    Source 2 — BirdNET labels file: covers every IOC common name BirdNET can
    return (e.g. "Eurasian Blackbird") and takes priority over source 1.
    """
    result: dict[str, str] = {}

    # Source 1: uk_species_filter.json
    json_path = Path(__file__).parent.parent / "filters" / "uk_species_filter.json"
    try:
        with open(json_path, encoding="utf-8") as fh:
            species: list[dict] = json.load(fh)
        for entry in species:
            sci = entry.get("scientific_name", "")
            if not sci:
                continue
            for key in ("name", "international_english_name"):
                val = entry.get(key, "")
                if val:
                    result[val.lower()] = sci
    except Exception as exc:  # noqa: BLE001
        logger.warning("[birdweather] could not load species JSON for scientific name lookup: %s", exc)

    # Source 2: BirdNET labels file — entries here override source 1.
    try:
        import pathlib as _pathlib
        import birdnet_analyzer as _bna  # type: ignore[import-untyped]
        labels_path = _pathlib.Path(_bna.__file__).parent / "checkpoints" / "V2.4" / "BirdNET_GLOBAL_6K_V2.4_Labels.txt"
        if labels_path.exists():
            for line in labels_path.read_text(encoding="utf-8").splitlines():
                label = line.strip()
                if not label or "_" not in label:
                    continue
                scientific, _, common = label.partition("_")
                if scientific and common:
                    result[common.lower()] = scientific.strip()
        else:
            logger.debug("[birdweather] BirdNET labels file not found at %s", labels_path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[birdweather] could not load BirdNET labels for scientific name lookup: %s", exc)

    return result


# Built lazily on first use so importing this module is cheap.
_sci_name_map: dict[str, str] | None = None
_sci_name_lock = threading.Lock()


def _get_scientific_name(common_name: str) -> str | None:
    global _sci_name_map
    if _sci_name_map is None:
        with _sci_name_lock:
            if _sci_name_map is None:
                _sci_name_map = _build_sci_name_map()
    sci = _sci_name_map.get(common_name.lower())
    if sci is None:
        logger.debug("[birdweather] no scientific name found for %r", common_name)
    return sci


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def post_detection(
    ts: datetime,
    species: str,
    confidence: float,
    clip_path: Path | None,
) -> None:
    """Schedule a background POST to BirdWeather and return immediately.

    Does nothing if cfg.birdweather.enabled is False or if transmission fails.

    Args:
        ts:         Detection timestamp (naive or timezone-aware).
        species:    Detected species common name (IOC / BTO label).
        confidence: Confidence score in the range 0.0–1.0.
        clip_path:  Path to the saved FLAC clip, or None if not saved.
    """
    if not cfg.birdweather.enabled:
        return
    threading.Thread(
        target=_send,
        args=(ts, species, confidence, clip_path),
        daemon=True,
    ).start()


# ---------------------------------------------------------------------------
# Internal worker
# ---------------------------------------------------------------------------

def _iso8601(ts: datetime) -> str:
    """Return a local-time ISO 8601 string with the station's UTC offset.

    BirdWeather displays the time component of the submitted timestamp as-is,
    so we use the configured local timezone (e.g. Europe/London) rather than
    UTC.  This means UK submissions show BST (+01:00) in summer and GMT
    (+00:00) in winter, matching other UK stations on the platform.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    local_tz = ZoneInfo(cfg.general.timezone)
    return ts.astimezone(local_tz).isoformat(timespec="seconds")


def _upload_soundscape(token: str, ts: datetime, clip_path: Path) -> int | None:
    """POST the audio clip to BirdWeather; return the soundscapeId or None on failure."""
    timestamp_param = urllib.request.quote(_iso8601(ts))
    url = f"{_API_BASE}/api/v1/stations/{token}/soundscapes?timestamp={timestamp_param}"
    try:
        audio_bytes = clip_path.read_bytes()
        req = urllib.request.Request(
            url,
            data=audio_bytes,
            headers={"Content-Type": "audio/flac"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
            if body.get("success") and "soundscape" in body:
                sc_id = body["soundscape"]["id"]
                logger.debug("[birdweather] soundscape uploaded id=%s for %s", sc_id, clip_path.name)
                return int(sc_id)
            logger.warning("[birdweather] soundscape upload unexpected response: %s", body)
    except urllib.error.HTTPError as exc:
        logger.warning("[birdweather] soundscape upload HTTP %d: %s", exc.code, exc.reason)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[birdweather] soundscape upload error: %s", exc)
    return None


def _send(
    ts: datetime,
    species: str,
    confidence: float,
    clip_path: Path | None,
) -> None:
    """Blocking worker — runs on a daemon thread; all exceptions are caught."""
    try:
        bw = cfg.birdweather
        token = bw.token.strip()
        if not token:
            logger.warning("[birdweather] token is not set — skipping post")
            return

        scientific_name = _get_scientific_name(species)

        # Step 1: upload audio clip if configured.
        soundscape_id: int | None = None
        if bw.upload_audio and clip_path and clip_path.exists():
            soundscape_id = _upload_soundscape(token, ts, clip_path)

        # Step 2: post detection metadata.
        payload: dict = {
            "timestamp":  _iso8601(ts),
            "commonName": species,
            "lat":        cfg.location.lat,
            "lon":        cfg.location.lon,
            "confidence": round(float(confidence), 6),
        }
        if scientific_name:
            payload["scientificName"] = scientific_name
        if soundscape_id is not None:
            payload["soundscapeId"] = soundscape_id
            # BirdWeather uses start/end times for playback offset within the soundscape.
            # We report the standard BirdNET 3-second window (start=0, end=3).
            payload["soundscapeStartTime"] = 0
            payload["soundscapeEndTime"]   = 3

        data = json.dumps(payload).encode()
        url  = f"{_API_BASE}/api/v1/stations/{token}/detections"

        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            if body.get("success"):
                det_id = body.get("detection", {}).get("id", "?")
                logger.debug(
                    "[birdweather] posted %s %.2f → detection id=%s", species, confidence, det_id
                )
            else:
                logger.warning("[birdweather] API rejected detection for %s: %s", species, body)

    except urllib.error.HTTPError as exc:
        logger.warning("[birdweather] HTTP %d posting %s: %s", exc.code, species, exc.reason)
    except urllib.error.URLError as exc:
        logger.debug("[birdweather] network error posting %s: %s", species, exc.reason)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[birdweather] unexpected error posting %s: %s", species, exc)
