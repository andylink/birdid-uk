"""
SSE stream that polls the database every 2 seconds and pushes new detections
to connected clients as named 'detection' events.

Only detections that arrive after the client connects are sent — no history
is replayed on reconnect. Works with both SQLite and PostgreSQL.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from dashboard.config import SSE_POLL_SECONDS
from dashboard.database import get_engine
from dashboard.utils import to_utc_iso


def _row_to_dict(row: dict) -> dict:
    d = dict(row)
    clip_path = d.get("clip_path")
    d["filename"] = Path(clip_path).name if clip_path else None
    d["timestamp"] = to_utc_iso(d.get("timestamp"))
    # PostgreSQL returns booleans; SQLite returns integers.
    # Normalise to integers so frontend === 1 checks work on both backends.
    for key in ("flagged", "cross_validated", "cv_agree"):
        if key in d and isinstance(d[key], bool):
            d[key] = int(d[key])
    return d


async def detection_generator() -> AsyncGenerator[dict, None]:
    """Yield SSE-formatted dicts for each new detection row."""
    last_id: int = 0

    async with get_engine().connect() as conn:
        # Start from the current max ID so we don't send existing detections on connect.
        # Silently skip if the detections table doesn't exist yet.
        try:
            row = (
                await conn.execute(text("SELECT COALESCE(MAX(id), 0) AS m FROM detections"))
            ).one()
            last_id = int(row[0])
        except OperationalError:
            pass

        while True:
            try:
                rows = (
                    await conn.execute(
                        text("""
                            SELECT d.id, d.timestamp, d.species, d.bto_name, d.confidence,
                                   d.clip_path, d.model,
                                   d.primary_confidence, d.cross_validated,
                                   d.cv_secondary_model, d.cv_species, d.cv_bto_name,
                                   d.cv_confidence, d.cv_agree, d.flagged,
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
                rows = []  # table not yet created; retry next cycle

            for row in rows:
                d = _row_to_dict(dict(row))
                last_id = d["id"]
                yield {"event": "detection", "data": json.dumps(d)}

            await asyncio.sleep(SSE_POLL_SECONDS)
