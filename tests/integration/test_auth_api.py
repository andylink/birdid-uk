"""
Integration tests for auth endpoints and admin route access control.

POST /api/v1/auth/login   — correct password sets cookie; wrong password → 401
POST /api/v1/auth/logout  — cookie is cleared
GET  /api/v1/auth/me      — returns authenticated state; never raises 401
Admin routes              — all return 401 without a valid session cookie

The verify_password function is patched via the bound name in dashboard.routes.auth
so tests are independent of any real password hash in config.toml.
"""

from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from dashboard.app import app
from dashboard.auth import COOKIE_NAME, create_session_cookie_value
from dashboard.database import get_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path):
    """httpx client wired to the app with a temp SQLite DB.

    The DB override prevents auth tests from failing because of a missing or
    misconfigured real database (FastAPI resolves get_db concurrently with
    require_admin, so a broken DB can mask the 401 with a 500).
    """
    db_path = tmp_path / "auth_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    async def _override_get_db() -> AsyncGenerator:
        async with engine.connect() as conn:
            yield conn

    app.dependency_overrides[get_db] = _override_get_db
    yield httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    app.dependency_overrides.clear()


# ── POST /api/v1/auth/login ───────────────────────────────────────────────────

async def test_login_correct_password_returns_200_and_sets_cookie(client):
    with patch("dashboard.routes.auth.verify_password", return_value=True):
        async with client as c:
            resp = await c.post(
                "/api/v1/auth/login", json={"password": "correcthorsebattery"}
            )
    assert resp.status_code == 200
    assert resp.json().get("authenticated") is True
    assert COOKIE_NAME in resp.cookies


async def test_login_wrong_password_returns_401_no_cookie(client):
    with patch("dashboard.routes.auth.verify_password", return_value=False):
        async with client as c:
            resp = await c.post(
                "/api/v1/auth/login", json={"password": "wrongpassword"}
            )
    assert resp.status_code == 401
    assert COOKIE_NAME not in resp.cookies


# ── POST /api/v1/auth/logout ──────────────────────────────────────────────────

async def test_logout_returns_200_and_clears_cookie(client):
    async with client as c:
        resp = await c.post("/api/v1/auth/logout")
    assert resp.status_code == 200
    assert resp.json().get("authenticated") is False
    # Starlette signals cookie deletion via the Set-Cookie header
    set_cookie = resp.headers.get("set-cookie", "")
    assert COOKIE_NAME in set_cookie


# ── GET /api/v1/auth/me ───────────────────────────────────────────────────────

async def test_me_without_cookie_returns_unauthenticated(client):
    async with client as c:
        resp = await c.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": False}


async def test_me_with_valid_cookie_returns_authenticated(client):
    token = create_session_cookie_value()
    async with client as c:
        c.cookies.set(COOKIE_NAME, token)
        resp = await c.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": True}


async def test_me_with_tampered_cookie_returns_unauthenticated(client):
    async with client as c:
        c.cookies.set(COOKIE_NAME, "tampered.bad.token")
        resp = await c.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is False


# ── Admin routes require authentication ───────────────────────────────────────

_ADMIN_ROUTES = [
    ("GET",    "/api/v1/admin/detections/count"),
    ("GET",    "/api/v1/admin/detections/export"),
    ("GET",    "/api/v1/admin/system/status"),
    ("DELETE", "/api/v1/admin/detections"),
    ("DELETE", "/api/v1/admin/detections/999"),
    ("PATCH",  "/api/v1/admin/detections/999/verification"),
    ("POST",   "/api/v1/admin/system/retention"),
    ("POST",   "/api/v1/admin/system/clear-image-cache"),
    ("POST",   "/api/v1/admin/system/reseed-species"),
]


@pytest.mark.parametrize("method,path", _ADMIN_ROUTES)
async def test_admin_route_returns_401_without_session(client, method, path):
    """Every admin endpoint must return 401 when no session cookie is present."""
    async with client as c:
        resp = await c.request(method, path)
    assert resp.status_code == 401, (
        f"{method} {path} → expected 401, got {resp.status_code}"
    )
