"""
mqtt.py — Publishes bird detections to an MQTT broker as JSON messages.

Publishing is fire-and-forget: errors are logged as warnings and never
interrupt the classify loop. The paho-mqtt network loop runs in a background
thread, so publishes are non-blocking with automatic reconnection.

Payload schema:
{
    "timestamp":   "2026-05-07T16:20:59",   // ISO-8601 to the second
    "species":     "European Robin",         // top-confidence species
    "bto_name":    "Robin",                  // BTO British name (null if unknown)
    "confidence":  0.9211,                   // rounded to 4 dp
    "source_name": "garden-north",           // audio source name (null in single-source mode)
    "clip_path":   "data/detections/...",
    "secondary":   [                         // additional candidates (may be empty)
        {"species": "Song Thrush", "confidence": 0.4503}
    ]
}
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from config import cfg

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
    secondary: list[tuple[str, float]],
    bto_name: str | None = None,
    source_name: str | None = None,
) -> None:
    """Publish one detection event as JSON to cfg.mqtt.topic.

    Silently returns if MQTT is disabled or the client is not connected.
    Publish errors are logged at WARNING level and never interrupt the classify loop.
    """
    if _client is None:
        return

    payload = json.dumps({
        "timestamp":   ts.isoformat(timespec="seconds"),
        "species":     species,
        "bto_name":    bto_name,
        "confidence":  round(confidence, 4),
        "source_name": source_name,
        "clip_path":   str(clip_path),
        "secondary": [
            {"species": s, "confidence": round(c, 4)}
            for s, c in secondary
        ],
    })

    try:
        _client.publish(cfg.mqtt.topic, payload=payload, retain=cfg.mqtt.retain)
    except Exception as exc:
        logger.warning("[mqtt] publish failed: %s", exc)
