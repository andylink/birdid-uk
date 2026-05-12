"""
dashboard/stream.py — SSE stream that polls the SQLite DB every 2 s and
pushes new detections as named 'detection' events.

The generator seeds `last_id` from the current DB maximum so only detections
that arrive *after* the client connects are streamed (no replay on reconnect).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator

import aiosqlite

from dashboard.config import DB_PATH, SSE_POLL_SECONDS
from dashboard.utils import to_utc_iso


def _row_to_dict(row: aiosqlite.Row) -> dict:
    d = dict(row)
    clip_path = d.get("clip_path")
    d["filename"] = Path(clip_path).name if clip_path else None
    d["timestamp"] = to_utc_iso(d.get("timestamp"))
    return d


async def detection_generator() -> AsyncGenerator[dict, None]:
    """Yield SSE-formatted dicts for each new detection row."""
    last_id: int = 0

    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")

        # Seed last_id so we don't replay history on initial connect.
        async with conn.execute("SELECT COALESCE(MAX(id), 0) FROM detections") as cur:
            row = await cur.fetchone()
            if row:
                last_id = int(row[0])

        while True:
            async with conn.execute(
                """
                SELECT d.id, d.timestamp, d.species, d.bto_name, d.confidence, d.clip_path,
                       d.model,
                       d.primary_confidence, d.cross_validated,
                       d.cv_secondary_model, d.cv_species, d.cv_bto_name,
                       d.cv_confidence, d.cv_agree, d.flagged,
                       si.scientific_name, si.group_name, si.uk_bocc, si.species_status,
                       si.bto_2letter_code, si.bto_5letter_code
                FROM detections d
                LEFT JOIN species_info si ON si.name = d.bto_name
                WHERE d.id > ? ORDER BY d.id ASC
                """,
                (last_id,),
            ) as cur:
                rows = await cur.fetchall()

            for row in rows:
                d = _row_to_dict(row)
                last_id = d["id"]
                yield {"event": "detection", "data": json.dumps(d)}

            await asyncio.sleep(SSE_POLL_SECONDS)
