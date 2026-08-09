"""User management. Admin-only."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_human_admin
from app.core.security import hash_password
from app.db import models
from app.db.session import get_db
from app.schemas.auth import (
    AdminUserCreate,
    UserPublic,
    UserRoleUpdate,
    UserStatusUpdate,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserPublic])
def list_users(
    _: models.Users = Depends(require_human_admin),
    db: Session = Depends(get_db),
) -> list[UserPublic]:
    users = db.scalars(select(models.Users).order_by(models.Users.created_at)).all()
    return [UserPublic.model_validate(u) for u in users]


@router.post("", response_model=UserPublic, status_code=201)
def create_user(
    payload: AdminUserCreate,
    _: models.Users = Depends(require_human_admin),
    db: Session = Depends(get_db),
) -> UserPublic:
    existing = db.scalar(
        select(models.Users).where(
            func.lower(models.Users.email) == payload.email.lower()
        )
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "email is already registered")

    user = models.Users(
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        role=payload.role,
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


@router.get("/{user_id}", response_model=UserPublic)
def get_user(
    user_id: uuid.UUID,
    _: models.Users = Depends(require_human_admin),
    db: Session = Depends(get_db),
) -> UserPublic:
    user = db.get(models.Users, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id} not found")
    return UserPublic.model_validate(user)


@router.patch("/{user_id}/role", response_model=UserPublic)
def update_role(
    user_id: uuid.UUID,
    payload: UserRoleUpdate,
    admin: models.Users = Depends(require_human_admin),
    db: Session = Depends(get_db),
) -> UserPublic:
    user = _get_or_404(db, user_id)
    if user.user_id == admin.user_id and payload.role.lower() != "admin":
        # Otherwise the last admin can lock everyone out of user management.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "you cannot remove your own admin role"
        )
    user.role = payload.role
    db.commit()
    db.refresh(user)
    return UserPublic.model_validate(user)


@router.patch("/{user_id}/status", response_model=UserPublic)
def update_status(
    user_id: uuid.UUID,
    payload: UserStatusUpdate,
    admin: models.Users = Depends(require_human_admin),
    db: Session = Depends(get_db),
) -> UserPublic:
    user = _get_or_404(db, user_id)
    if user.user_id == admin.user_id and payload.status.lower() != "active":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "you cannot deactivate your own account"
        )
    user.status = payload.status
    db.commit()
    db.refresh(user)
    return UserPublic.model_validate(user)


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: uuid.UUID,
    admin: models.Users = Depends(require_human_admin),
    db: Session = Depends(get_db),
) -> None:
    user = _get_or_404(db, user_id)
    if user.user_id == admin.user_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "you cannot delete your own account"
        )
    db.delete(user)
    db.commit()


def _get_or_404(db: Session, user_id: uuid.UUID) -> models.Users:
    user = db.get(models.Users, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id} not found")
    return user
