"""
dashboard/database.py — read-only async database access (aiosqlite).

FastAPI dependency `get_db` yields an aiosqlite connection with WAL mode
enabled; the dashboard never writes to the database.
"""

from __future__ import annotations

from typing import AsyncGenerator

import aiosqlite

from dashboard.config import DB_PATH


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """FastAPI dependency: yield a read-only aiosqlite connection."""
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        # WAL allows concurrent reads alongside the detector's write engine.
        await conn.execute("PRAGMA journal_mode=WAL")
        yield conn
