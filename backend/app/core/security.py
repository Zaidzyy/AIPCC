"""Password hashing and JWT access tokens.

CLAUDE.md hard rule #3: passwords are bcrypt-hashed, never stored plaintext.
The prototype wrote `password_hash = new_user.password` and seeded an admin
with `password_hash="123456789"`, despite bcrypt already being in its
requirements.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

ALGORITHM = settings.jwt_algorithm

# bcrypt truncates at 72 bytes and raises on longer input in modern versions.
# Reject early with a clear message rather than surfacing a library error.
MAX_PASSWORD_BYTES = 72


class TokenError(Exception):
    """The token is missing, malformed, expired, or not ours."""


def hash_password(password: str) -> str:
    """Return a bcrypt hash of `password`."""
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"password must be at most {MAX_PASSWORD_BYTES} bytes when UTF-8 encoded"
        )
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check `password` against a stored bcrypt hash.

    Returns False rather than raising on a malformed stored hash, so a corrupt
    row cannot turn into a 500 on the login path.
    """
    try:
        return bcrypt.checkpw(
            password.encode("utf-8")[:MAX_PASSWORD_BYTES],
            password_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: uuid.UUID | str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Mint a signed access token for `subject`."""
    now = datetime.now(timezone.utc)
    expires = now + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "iat": now,
        "exp": expires,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify and decode a token, or raise TokenError."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError(f"invalid token: {exc}") from exc

    if payload.get("type") != "access":
        raise TokenError("not an access token")
    if not payload.get("sub"):
        raise TokenError("token has no subject")
    return payload
