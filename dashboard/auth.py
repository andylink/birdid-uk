"""
Admin authentication helpers.

verify_password   — checks a plain-text password against the stored bcrypt hash.
create_session    — returns a signed value to store in the admin_session cookie.
decode_session    — validates a cookie value; returns True if valid and not expired.
get_current_admin — FastAPI dependency; returns True when a valid session cookie is present.
require_admin     — FastAPI dependency; raises 401 when no valid session cookie is present.
"""

from __future__ import annotations

import bcrypt
from fastapi import Cookie, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from dashboard.config import ADMIN_PASSWORD_HASH, SESSION_SECRET, SESSION_TTL

_serializer = URLSafeTimedSerializer(SESSION_SECRET)

COOKIE_NAME = "admin_session"


def verify_password(plain: str) -> bool:
    """Return True if plain matches the stored bcrypt hash.

    Returns False immediately when no hash is configured.
    """
    if not ADMIN_PASSWORD_HASH:
        return False
    return bcrypt.checkpw(plain.encode(), ADMIN_PASSWORD_HASH.encode())


def create_session_cookie_value() -> str:
    """Return a signed token suitable for storing in the admin_session cookie."""
    return _serializer.dumps("admin")


def decode_session(token: str) -> bool:
    """Return True if token is a valid, unexpired session cookie value."""
    try:
        _serializer.loads(token, max_age=SESSION_TTL)
        return True
    except (BadSignature, SignatureExpired):
        return False


def get_current_admin(admin_session: str | None = Cookie(default=None)) -> bool:
    """FastAPI dependency — return True when the request carries a valid session cookie."""
    return bool(admin_session and decode_session(admin_session))


def require_admin(admin_session: str | None = Cookie(default=None)) -> None:
    """FastAPI dependency — raise 401 unless the request carries a valid session cookie."""
    if not admin_session or not decode_session(admin_session):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
