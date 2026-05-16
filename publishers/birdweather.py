"""
birdweather.py — fire-and-forget uploader for app.birdweather.com

After each confirmed detection, call ``post_detection()`` once.  The function
returns immediately; all HTTP work runs on a daemon thread and any error is
silently logged so the classify loop is never interrupted.

The flow per detection is:

1. If ``upload_audio = true`` and the FLAC clip exists, POST the raw audio to
   ``/api/v1/stations/{token}/soundscapes?timestamp=<ISO8601>`` and capture the
   returned ``soundscapeId``.
2. POST the detection metadata (including the soundscape reference when step 1
   succeeded) to ``/api/v1/stations/{token}/detections``.

Scientific names are resolved first from the BirdNET labels file (which maps
every IOC common name BirdNET can return to its scientific name) and
supplemented by ``filters/uk_species_filter.json`` for BTO British-name
aliases.  Species unresolvable from both sources are posted without a
``scientificName`` and a DEBUG log entry is emitted.

Controlled entirely by the ``[birdweather]`` section of config.toml::

    [birdweather]
    enabled      = true
    token        = "your-station-token"   # from app.birdweather.com → Station → Token
    upload_audio = true                   # upload FLAC clip as a soundscape (recommended)

Set ``enabled = false`` (the default) to disable without removing the section.
When disabled, ``post_detection()`` is a no-op and no network activity occurs.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from config import cfg

logger = logging.getLogger(__name__)

_API_BASE = "https://app.birdweather.com"

# ---------------------------------------------------------------------------
# Scientific-name lookup — built once from filters/uk_species_filter.json
# ---------------------------------------------------------------------------

def _build_sci_name_map() -> dict[str, str]:
    """Return {common_name_lower: scientific_name}.

    Built from two sources (applied in order; later entries win):

    1. ``filters/uk_species_filter.json`` — covers BTO British names and
       ``international_english_name`` aliases.
    2. The BirdNET labels file (``Scientific name_Common name`` format) — gives
       exact mappings for every IOC common name BirdNET can return (e.g.
       "Eurasian Blackbird") and takes priority over the JSON aliases.
    """
    result: dict[str, str] = {}

    # Source 1: uk_species_filter.json (BTO name + international alias)
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

    # Source 2: BirdNET labels file — overrides JSON entries and covers every
    # IOC name that BirdNET can actually return (the exact names passed here).
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


# Module-level map; built lazily on first use so import is cheap.
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

    Silently no-ops if ``cfg.birdweather.enabled`` is ``False`` or if any
    error occurs during transmission.

    Args:
        ts:         Timestamp of the detection (naive or aware datetime).
        species:    Detected species common name (IOC / BTO label).
        confidence: Detection confidence in the range 0.0–1.0.
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
    """Return an ISO 8601 string with UTC offset, e.g. ``2026-05-14T09:31:00+00:00``."""
    if ts.tzinfo is None:
        ts = ts.astimezone(timezone.utc)
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _upload_soundscape(token: str, ts: datetime, clip_path: Path) -> int | None:
    """Upload *clip_path* as a soundscape; return the soundscapeId or None on failure."""
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

        # ── Step 1: optional soundscape upload ────────────────────────────────
        soundscape_id: int | None = None
        if bw.upload_audio and clip_path and clip_path.exists():
            soundscape_id = _upload_soundscape(token, ts, clip_path)

        # ── Step 2: post detection ─────────────────────────────────────────────
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
            # The clip covers exactly the model analysis window; BirdNET uses 3 s,
            # Perch uses 5 s.  We don't have the window length here, so report
            # the standard BirdNET window (3 s) as start=0/end=3 — BirdWeather
            # uses these only for playback offset, not for re-analysis.
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
