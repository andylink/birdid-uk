"""
mqtt.py — MQTT publishing for bird detections.

Each detection is serialised as a JSON message and published to the
configured broker topic.  Publishing is fire-and-forget: failures are logged
as warnings and never raise into the classify loop.

The paho-mqtt client runs its network loop in a background thread
(``loop_start``), so publishes are non-blocking.  The client reconnects
automatically if the broker drops the connection.

Payload schema
--------------
{
    "timestamp":  "2026-05-07T16:20:59",   // ISO-8601 to the second
    "species":    "European Robin",         // top-confidence species
    "confidence": 0.9211,                  // rounded to 4 dp
    "clip_path":  "data/detections/...",
    "secondary":  [                         // additional candidates (may be empty)
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

_client = None   # paho mqtt.Client once initialised, else None


def init_mqtt() -> None:
    """
    Connect to the MQTT broker and start the background network loop.

    No-op when ``[mqtt] enabled = false``.  Logs a clear error and leaves
    ``_client`` as ``None`` if paho-mqtt is not installed or the broker is
    unreachable; ``publish_detection`` becomes a silent no-op in that case.
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
        # args[0] is rc (int) in paho v1, ReasonCode in paho v2 — both compare
        # equal to 0 on success.
        rc = args[0] if args else 0
        if rc == 0:
            logger.info("[mqtt] connected to %s:%d", cfg.mqtt.broker, cfg.mqtt.port)
        else:
            logger.warning("[mqtt] connection refused (rc=%s)", rc)

    def _on_disconnect(client, userdata, *args) -> None:
        # Signature varies between paho v1 (rc) and v2 (disconnect_flags, reason_code, properties).
        rc = args[0] if args else 0
        if rc != 0:
            logger.warning("[mqtt] disconnected unexpectedly (rc=%s) — will reconnect", rc)

    # Instantiate client — handle paho-mqtt v1 (< 2.0) and v2 (>= 2.0).
    try:
        client = _mqtt.Client(
            _mqtt.CallbackAPIVersion.VERSION2,
            client_id="bird-detector",
        )
    except AttributeError:
        # paho-mqtt < 2.0 does not have CallbackAPIVersion
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
) -> None:
    """
    Publish one detection event as JSON to ``cfg.mqtt.topic``.

    Silently returns if MQTT is disabled or the client is not connected.
    Any publish error is logged at WARNING level and swallowed so it never
    interrupts the classify loop.
    """
    if _client is None:
        return

    payload = json.dumps({
        "timestamp":  ts.isoformat(timespec="seconds"),
        "species":    species,
        "confidence": round(confidence, 4),
        "clip_path":  str(clip_path),
        "secondary": [
            {"species": s, "confidence": round(c, 4)}
            for s, c in secondary
        ],
    })

    try:
        _client.publish(cfg.mqtt.topic, payload=payload, retain=cfg.mqtt.retain)
    except Exception as exc:
        logger.warning("[mqtt] publish failed: %s", exc)
