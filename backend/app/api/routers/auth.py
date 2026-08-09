"""Authentication: login, self-registration, profile."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db import models
from app.db.session import get_db
from app.schemas.auth import PasswordChange, Token, UserCreate, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])

# Deliberately identical for "no such email" and "wrong password" so the
# endpoint cannot be used to enumerate registered addresses.
_BAD_CREDENTIALS = "incorrect email or password"


def _find_by_email(db: Session, email: str) -> models.Users | None:
    return db.scalar(
        select(models.Users).where(func.lower(models.Users.email) == email.lower())
    )


@router.post("/login", response_model=Token)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    """OAuth2 password flow. `username` is the user's email."""
    user = _find_by_email(db, form.username)

    # Verify even when the user is missing, so a wrong email and a wrong
    # password take comparable time and cannot be told apart by latency.
    stored_hash = user.password_hash if user else _DUMMY_HASH
    password_ok = verify_password(form.password, stored_hash)

    if user is None or not password_ok:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            _BAD_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.status.lower() != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"account is {user.status}")

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    return Token(
        access_token=create_access_token(user.user_id, user.role),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/register", response_model=UserPublic, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> UserPublic:
    """Self-registration. Always creates a non-privileged account.

    Roles are never taken from the request body — see users.py for the
    admin-only path that can set one.
    """
    if _find_by_email(db, payload.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "email is already registered")

    user = models.Users(
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        role="analyst",
        status="Active",
        phone_number=payload.phone_number,
        password_hash=hash_password(payload.password),
        organization=payload.organization,
        location=payload.location,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserPublic.model_validate(user)


@router.get("/me", response_model=UserPublic)
def read_me(user: models.Users = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(user)


@router.post("/change-password", status_code=204)
def change_password(
    payload: PasswordChange,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    db.commit()


# A real bcrypt hash of a random string, compared against when the email is
# unknown so that path does the same work as a genuine verification.
_DUMMY_HASH = hash_password("not-a-real-password-placeholder")
