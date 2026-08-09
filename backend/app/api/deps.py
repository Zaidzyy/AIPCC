"""Shared route dependencies.

`get_current_user` is the *only* way a route learns who is calling. There is no
module-level `current_user` anywhere in this codebase — the prototype assigned
one as a side effect of hitting `POST /api/user`, so every other route raised
NameError until that endpoint happened to be called first.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import TokenError, decode_access_token
from app.db import models
from app.db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

ADMIN_ROLE = "admin"

_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.Users:
    """Resolve the caller from their bearer token."""
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
    if user.status.lower() != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"account is {user.status}")
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
