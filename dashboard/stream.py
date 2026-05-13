"""
dashboard/stream.py — SSE stream that polls the DB every 2 s and pushes new
detections as named 'detection' events.

Uses SQLAlchemy asyncio (via get_engine()) so it works with both SQLite and
PostgreSQL backends.  The generator seeds ``last_id`` from the current DB
maximum so only detections that arrive *after* the client connects are streamed
(no replay on reconnect).
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
    # Normalise boolean fields to integers so the frontend === 1 checks hold
    # for both SQLite (returns int) and PostgreSQL (returns bool via asyncpg).
    for key in ("flagged", "cross_validated", "cv_agree"):
        if key in d and isinstance(d[key], bool):
            d[key] = int(d[key])
    return d


async def detection_generator() -> AsyncGenerator[dict, None]:
    """Yield SSE-formatted dicts for each new detection row."""
    last_id: int = 0

    async with get_engine().connect() as conn:
        # Seed last_id so we don't replay history on initial connect.
        # Guard against a race where detect.py hasn't created the schema yet.
        try:
            row = (
                await conn.execute(text("SELECT COALESCE(MAX(id), 0) AS m FROM detections"))
            ).one()
            last_id = int(row[0])
        except OperationalError:
            pass  # table not yet created; last_id stays 0

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
                rows = []  # table not yet created; wait and retry next cycle

            for row in rows:
                d = _row_to_dict(dict(row))
                last_id = d["id"]
                yield {"event": "detection", "data": json.dumps(d)}

            await asyncio.sleep(SSE_POLL_SECONDS)
