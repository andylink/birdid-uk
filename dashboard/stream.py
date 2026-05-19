"""
SSE stream that polls the database every 2 seconds and pushes new detections
to connected clients as named 'detection' events.

Reconnect support: if the client sends a `Last-Event-ID` header (standard SSE
reconnect behaviour), the stream resumes from that detection ID so no events
are missed.

Keepalive: a comment-style ping is emitted when no detections arrive in a
poll cycle, preventing proxies from closing idle connections after 30–60 s.

Works with both SQLite and PostgreSQL.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from dashboard.config import SSE_POLL_SECONDS
from dashboard.database import get_engine
from dashboard.utils import to_utc_iso

_log = logging.getLogger(__name__)


def _row_to_dict(row: dict) -> dict:
    d = dict(row)
    clip_path = d.get("clip_path")
    d["filename"] = Path(clip_path).name if clip_path else None
    d["timestamp"] = to_utc_iso(d.get("timestamp"))
    # PostgreSQL returns booleans; SQLite returns integers.
    # Normalise to integers so frontend === 1 checks work on both backends.
    for key in ("cross_validated", "cv_agree"):
        if key in d and isinstance(d[key], bool):
            d[key] = int(d[key])
    # Ensure verification_status is never NULL in the payload.
    if not d.get("verification_status"):
        d["verification_status"] = "unverified"
    return d


async def detection_generator(last_event_id: str | None = None) -> AsyncGenerator[dict, None]:
    """Yield SSE-formatted dicts for each new detection row.

    Args:
        last_event_id: If the client reconnects with a ``Last-Event-ID`` header,
            pass that value here so the stream resumes from that detection ID
            rather than the current maximum.  ``None`` means start from now.
    """
    # Honour Last-Event-ID for reconnecting clients.
    if last_event_id is not None:
        try:
            last_id = int(last_event_id)
        except (TypeError, ValueError):
            last_id = 0
    else:
        last_id = 0

    if last_event_id is None:
        # New connection — start from the current max ID so we don't replay history.
        try:
            async with get_engine().connect() as conn:
                row = (
                    await conn.execute(text("SELECT COALESCE(MAX(id), 0) AS m FROM detections"))
                ).one()
                last_id = int(row[0])
        except OperationalError:
            _log.warning("SSE stream: DB OperationalError reading max(id) (table may not exist yet)")

    while True:
        rows = []
        try:
            # Acquire and release the connection on every poll cycle so we never
            # hold a connection idle between polls (prevents pool exhaustion with
            # many simultaneous clients).
            async with get_engine().connect() as conn:
                rows = (
                    await conn.execute(
                        text("""
                            SELECT d.id, d.timestamp, d.species, d.bto_name, d.confidence,
                                   d.clip_path, d.model,
                                   d.primary_confidence, d.cross_validated,
                                   d.cv_secondary_model, d.cv_species, d.cv_bto_name,
                                   d.cv_confidence, d.cv_agree,
                                   COALESCE(d.verification_status, 'unverified') AS verification_status,
                                   si.scientific_name, si.group_name, si.uk_bocc,
                                   si.species_status, si.bto_2letter_code, si.bto_5letter_code
                            FROM detections d
                            LEFT JOIN species_info si ON si.name = d.bto_name
                            WHERE d.id > :last_id
                            ORDER BY d.id ASC
                        """),
                        {"last_id": last_id},
                    )
                ).mappings().all()
        except OperationalError:
            _log.warning("SSE stream: DB OperationalError (table may not exist yet), retrying")
            rows = []

        if rows:
            for row in rows:
                d = _row_to_dict(dict(row))
                last_id = d["id"]
                yield {"event": "detection", "data": json.dumps(d), "id": str(last_id)}
        else:
            # No new detections — send a keepalive comment so proxies don't drop
            # the connection after their idle timeout (typically 30–60 s).
            yield {"event": "ping", "data": ""}

        await asyncio.sleep(SSE_POLL_SECONDS)
