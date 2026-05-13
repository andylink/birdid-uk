"""
dashboard/database.py — async database access via SQLAlchemy asyncio.

Supports both SQLite (default) and PostgreSQL, driven by [database] type in
config.toml.  The async engine is created once at startup and shared across
all requests via a module-level instance.

Driver selection is handled by the DB_URL constructed in dashboard/config.py:
    sqlite      → sqlite+aiosqlite:///path/to/birds.db
    postgresql  → postgresql+asyncpg://user:pass@host:port/db

All queries use SQLAlchemy ``text()`` with ``:name`` bound parameters, which
SQLAlchemy translates to the correct wire format for each driver (``?`` for
aiosqlite, ``$1…`` for asyncpg).

Rows are returned as ``RowMapping`` objects (dict-like, keyed by column name)
from ``.mappings().all()`` / ``.mappings().first()``.
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from dashboard.config import DB_TYPE, DB_URL

# ── Engine ────────────────────────────────────────────────────────────────────
# Created once at import time; startup_db() / shutdown_db() manage its lifecycle.
_engine: AsyncEngine | None = None


def _make_engine() -> AsyncEngine:
    """Build the async engine appropriate for the configured backend."""
    if DB_TYPE == "sqlite":
        engine = create_async_engine(DB_URL, connect_args={"check_same_thread": False})

        # WAL mode: allow concurrent reads alongside the detector's write engine.
        @event.listens_for(engine.sync_engine, "connect")
        def _set_wal(dbapi_conn, _record) -> None:
            dbapi_conn.execute("PRAGMA journal_mode=WAL")

        return engine

    # PostgreSQL / TimescaleDB
    return create_async_engine(DB_URL, pool_size=5, max_overflow=10)


# ── Lifecycle ─────────────────────────────────────────────────────────────────

async def startup_db() -> None:
    """Initialise the async engine.  Called from the FastAPI lifespan hook."""
    global _engine
    _engine = _make_engine()


async def shutdown_db() -> None:
    """Dispose the async engine and release all connections."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def get_engine() -> AsyncEngine:
    """Return the live engine; raises if startup_db() has not been called."""
    if _engine is None:
        raise RuntimeError("Database engine not initialised — was startup_db() called?")
    return _engine


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncConnection, None]:
    """FastAPI dependency: yield a read-only async database connection.

    Rows returned by ``conn.execute(text(sql), params).mappings().all()`` are
    ``RowMapping`` objects that support dict-like column-name access and
    ``dict(row)`` conversion, for both SQLite and PostgreSQL backends.
    """
    async with get_engine().connect() as conn:
        yield conn
