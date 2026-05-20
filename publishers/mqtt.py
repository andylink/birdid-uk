"""
mqtt.py — Publishes bird detections to an MQTT broker as JSON messages.

Publishing is fire-and-forget: errors are logged as warnings and never
interrupt the classify loop. The paho-mqtt network loop runs in a background
thread, so publishes are non-blocking with automatic reconnection.

Payload schema:
{
    "timestamp":    "2026-05-07T16:20:59+01:00",  // ISO-8601 with UTC offset
    "species":      "European Robin",              // top-confidence species
    "bto_name":     "Robin",                       // BTO British name (null if unknown)
    "confidence":   0.9211,                        // rounded to 4 dp
    "model":        "BirdNET",                     // inference model name (null if unknown)
    "source_name":  "garden-north",                // audio source (null in single-source mode)
    "station_name": "My Garden",                   // [general] station_name from config
    "clip_path":    "data/detections/...",
    "weather": {                                   // null when weather is disabled
        "temperature":    12.3,
        "humidity":       78.0,
        "wind_speed":     5.1,
        "wind_direction": 220.0,
        "pressure":       1013.0,
        "condition":      "Partly cloudy",
        "precipitation":  0.0,
        "provider":       "open_meteo"
    },
    "cross_validation": {                          // null when CV is disabled or didn't run
        "performed":        true,
        "secondary_model":  "Perch",
        "secondary_species": "European Robin",
        "cv_confidence":    0.88,
        "agree":            true,
        "flagged":          false
    }
}
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from config import cfg

if TYPE_CHECKING:
    from weather import WeatherData

logger = logging.getLogger(__name__)

_client = None  # paho mqtt.Client once initialised, else None


def init_mqtt() -> None:
    """Connect to the MQTT broker and start the background network loop.

    No-op when [mqtt] enabled = false. Logs an error and leaves _client as
    None if paho-mqtt is not installed or the broker is unreachable, making
    publish_detection a silent no-op.
    """
    global _client

    if not cfg.mqtt.enabled:
        return

    try:
        import paho.mqtt.client as _mqtt
    except ImportError:
        logger.error("[mqtt] paho-mqtt is not installed — run: pip install paho-mqtt")
        return

    def _on_connect(client, userdata, flags, *args) -> None:
        # paho v1 passes rc as int; paho v2 passes a ReasonCode — both equal 0 on success.
        rc = args[0] if args else 0
        if rc == 0:
            logger.info("[mqtt] connected to %s:%d", cfg.mqtt.broker, cfg.mqtt.port)
        else:
            logger.warning("[mqtt] connection refused (rc=%s)", rc)

    def _on_disconnect(client, userdata, *args) -> None:
        # Signature differs between paho v1 and v2; check first arg for error code.
        rc = args[0] if args else 0
        if rc != 0:
            logger.warning("[mqtt] disconnected unexpectedly (rc=%s) — will reconnect", rc)

    # CallbackAPIVersion.VERSION2 was added in paho-mqtt 2.0; fall back for older installs.
    try:
        client = _mqtt.Client(
            _mqtt.CallbackAPIVersion.VERSION2,
            client_id="bird-detector",
        )
    except AttributeError:
        client = _mqtt.Client(client_id="bird-detector")

    client.on_connect    = _on_connect
    client.on_disconnect = _on_disconnect

    if cfg.mqtt.username:
        client.username_pw_set(cfg.mqtt.username, cfg.mqtt.password or None)

    try:
        client.connect(cfg.mqtt.broker, cfg.mqtt.port, keepalive=60)
        client.loop_start()
        _client = client
    except Exception as exc:
        logger.warning("[mqtt] could not connect to %s:%d — %s",
                       cfg.mqtt.broker, cfg.mqtt.port, exc)


def publish_detection(
    ts: datetime,
    species: str,
    confidence: float,
    clip_path: Path,
    bto_name: str | None = None,
    source_name: str | None = None,
    model_name: str | None = None,
    station_name: str | None = None,
    weather: WeatherData | None = None,
    cv_result=None,
) -> None:
    """Publish one detection event as JSON to cfg.mqtt.topic.

    Silently returns if MQTT is disabled, the client is not connected, or
    the detection falls below cfg.mqtt.min_confidence.
    Publish errors are logged at WARNING level and never interrupt the classify loop.

    Args:
        ts:           Detection timestamp.
        species:      Detected species common name.
        confidence:   Confidence score 0.0–1.0.
        clip_path:    Path to the saved FLAC clip.
        bto_name:     BTO British name (None if not resolved).
        source_name:  Audio source identifier (None in single-source mode).
        model_name:   Inference model name, e.g. "BirdNET" or "Perch".
        station_name: Station display name from [general] config.
        weather:      WeatherData snapshot at detection time, or None.
        cv_result:    CrossValidationResult, or None if CV didn't run.
    """
    if _client is None:
        return
    if cfg.mqtt.min_confidence is not None and confidence < cfg.mqtt.min_confidence:
        logger.debug("[mqtt] detection below min_confidence — skipping publish")
        return

    # Build weather block — null when weather is disabled or unavailable.
    weather_block = None
    if weather is not None:
        weather_block = {
            "temperature":    weather.temperature,
            "humidity":       weather.humidity,
            "wind_speed":     weather.wind_speed,
            "wind_direction": weather.wind_direction,
            "pressure":       weather.pressure,
            "condition":      weather.condition,
            "precipitation":  weather.precipitation,
            "provider":       weather.provider,
        }

    # Build cross-validation block — null when CV is disabled or didn't run.
    cv_block = None
    if cv_result is not None:
        cv_block = {
            "performed":         cv_result.performed,
            "secondary_model":   cv_result.secondary_model_name,
            "secondary_species": cv_result.secondary_species,
            "cv_confidence":     cv_result.secondary_confidence,
            "agree":             cv_result.agree,
            "flagged":           cv_result.action == "flag",
        }

    payload = json.dumps({
        "timestamp":        ts.isoformat(timespec="seconds"),
        "species":          species,
        "bto_name":         bto_name,
        "confidence":       round(confidence, 4),
        "model":            model_name,
        "source_name":      source_name,
        "station_name":     station_name,
        "clip_path":        str(clip_path),
        "weather":          weather_block,
        "cross_validation": cv_block,
    })

    try:
        _client.publish(cfg.mqtt.topic, payload=payload, retain=cfg.mqtt.retain)
    except Exception as exc:
        logger.warning("[mqtt] publish failed: %s", exc)
