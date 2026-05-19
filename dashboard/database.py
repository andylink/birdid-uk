"""
Async database access for the dashboard, supporting SQLite and PostgreSQL.

A single async SQLAlchemy engine is created at startup and shared across all
requests.  The correct driver is chosen automatically based on DB_URL from
dashboard/config.py:
    sqlite     → sqlite+aiosqlite
    postgresql → postgresql+asyncpg

All queries use SQLAlchemy text() with :name bound parameters.  Rows come back
as RowMapping objects (dict-like, keyed by column name) via .mappings().all()
or .mappings().first().
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from dashboard.config import DB_TYPE, DB_URL

# ── Engine ────────────────────────────────────────────────────────────────────
# Initialised by startup_db(); None until then.
_engine: AsyncEngine | None = None


def _make_engine() -> AsyncEngine:
    """Create the async engine for the configured database backend."""
    if DB_TYPE == "sqlite":
        engine = create_async_engine(DB_URL, connect_args={"check_same_thread": False})

        # Enable WAL mode so the dashboard can read while the detector is writing.
        @event.listens_for(engine.sync_engine, "connect")
        def _set_wal(dbapi_conn, _record) -> None:
            dbapi_conn.execute("PRAGMA journal_mode=WAL")

        return engine

    # PostgreSQL / TimescaleDB
    return create_async_engine(DB_URL, pool_size=5, max_overflow=10)


# ── Lifecycle ─────────────────────────────────────────────────────────────────

async def startup_db() -> None:
    """Create the async engine. Called from the FastAPI lifespan hook."""
    global _engine
    _engine = _make_engine()


async def shutdown_db() -> None:
    """Close all connections and dispose the engine on shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def get_engine() -> AsyncEngine:
    """Return the live engine. Raises if startup_db() hasn't been called yet."""
    if _engine is None:
        raise RuntimeError("Database engine not initialised — was startup_db() called?")
    return _engine


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncConnection, None]:
    """FastAPI dependency that yields an async database connection per request."""
    async with get_engine().connect() as conn:
        yield conn
