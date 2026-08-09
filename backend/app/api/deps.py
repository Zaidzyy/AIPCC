"""Shared route dependencies.

`get_current_user` is the *only* way a route learns who is calling. There is no
module-level `current_user` anywhere in this codebase — the prototype assigned
one as a side effect of hitting `POST /api/user`, so every other route raised
NameError until that endpoint happened to be called first.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import api_key as api_key_utils
from app.core.security import TokenError, decode_access_token
from app.db import models
from app.db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

ADMIN_ROLE = "admin"

_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}

# `last_used_at` is useful for spotting a key nothing uses any more, but it is
# not an audit log. Writing it on literally every request would turn a read
# endpoint into a write; a minute of resolution is plenty to answer "is this
# key still live?".
LAST_USED_RESOLUTION = timedelta(minutes=1)


def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.Users:
    """Resolve the caller from their bearer credential.

    Two credential types share the `Authorization: Bearer` header: a
    short-lived JWT for humans and a long-lived API key for machines. They are
    told apart by the key's `aipcc_` prefix, which a JWT can never have. The
    method is recorded on the request so `require_human` can refuse a machine
    credential on the routes that manage credentials.
    """
    if api_key_utils.looks_like_api_key(token):
        user = _user_from_api_key(db, token)
        request.state.auth_method = "api_key"
    else:
        user = _user_from_jwt(db, token)
        request.state.auth_method = "jwt"

    if user.status.lower() != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"account is {user.status}")
    return user


def _user_from_jwt(db: Session, token: str) -> models.Users:
    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, str(exc), headers=_UNAUTHORIZED
        ) from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "malformed token subject", headers=_UNAUTHORIZED
        ) from exc

    user = db.get(models.Users, user_id)
    if user is None:
        # Token signature is valid but the account is gone.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "user no longer exists", headers=_UNAUTHORIZED
        )
    return user


def _user_from_api_key(db: Session, secret: str) -> models.Users:
    """Resolve an API key to its owner.

    Every failure below answers with the same message. A caller holding a bad
    key learns that it does not work, and nothing else — not whether the prefix
    exists, not whether it was revoked rather than expired.
    """
    prefix = api_key_utils.extract_prefix(secret)
    record = (
        db.scalar(select(models.ApiKey).where(models.ApiKey.prefix == prefix))
        if prefix
        else None
    )

    now = datetime.now(timezone.utc)
    valid = (
        record is not None
        and not record.revoked
        and (record.expires_at is None or record.expires_at > now)
        and api_key_utils.verify_key(secret, record.key_hash)
    )
    if not valid:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "invalid API key", headers=_UNAUTHORIZED
        )

    if record.last_used_at is None or now - record.last_used_at > LAST_USED_RESOLUTION:
        record.last_used_at = now
        db.commit()

    return record.user


def require_human(request: Request, user: models.Users = Depends(get_current_user)) -> models.Users:
    """Reject a machine credential.

    Applied to the routes that manage users and API keys. An n8n key is pasted
    into a workflow, lives in a credential store and is long-lived by design —
    if one leaks it must not be able to mint more credentials or create an
    admin. Containing that costs one dependency; not containing it costs the
    whole account.
    """
    if getattr(request.state, "auth_method", "jwt") == "api_key":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "this endpoint requires a user session; API keys cannot manage credentials",
        )
    return user


def require_role(*roles: str) -> Callable[[models.Users], models.Users]:
    """Dependency factory gating a route to the given roles."""

    allowed = {role.lower() for role in roles}

    def dependency(user: models.Users = Depends(get_current_user)) -> models.Users:
        if user.role.lower() not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"requires one of: {', '.join(sorted(allowed))}",
            )
        return user

    return dependency


require_admin = require_role(ADMIN_ROLE)


def require_human_admin(user: models.Users = Depends(require_human)) -> models.Users:
    """Admin, and holding a user session rather than an API key."""
    if not is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires {ADMIN_ROLE}")
    return user


def is_admin(user: models.Users) -> bool:
    return user.role.lower() == ADMIN_ROLE


def authorize_owner(user: models.Users, owner_id: uuid.UUID) -> None:
    """Allow access only to the owner, or to an admin.

    Raises 404 rather than 403 for non-owners: telling a stranger "this exists
    but is not yours" leaks that the id is real.
    """
    if is_admin(user) or user.user_id == owner_id:
        return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
