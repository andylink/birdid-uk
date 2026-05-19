"""
Auth endpoints — login, logout, and session check.

POST /api/v1/auth/login   — verify password; set an HTTP-only session cookie on success.
POST /api/v1/auth/logout  — clear the session cookie.
GET  /api/v1/auth/me      — return { "authenticated": bool }; never returns 401.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from dashboard.auth import (
    COOKIE_NAME,
    create_session_cookie_value,
    get_current_admin,
    verify_password,
)
from dashboard.config import SESSION_TTL

router = APIRouter()


class LoginRequest(BaseModel):
    password: str


@router.post("/api/v1/auth/login")
async def login(body: LoginRequest, response: Response):
    """Check the password and set an HTTP-only session cookie on success."""
    if not verify_password(body.password):
        # Return 401 with a generic message; do not reveal why auth failed.
        response.status_code = 401
        return {"detail": "Invalid password"}

    token = create_session_cookie_value()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=False,   # HTTP-only deployment; set True if serving over HTTPS
    )
    return {"authenticated": True}


@router.post("/api/v1/auth/logout")
async def logout(response: Response):
    """Clear the session cookie."""
    response.delete_cookie(key=COOKIE_NAME, samesite="lax")
    return {"authenticated": False}


@router.get("/api/v1/auth/me")
async def me(authenticated: bool = Depends(get_current_admin)):
    """Return whether the current request is authenticated.  Never raises 401."""
    return {"authenticated": authenticated}
