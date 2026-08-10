"""API key management. Admin-only, and human-only.

`require_human_admin` rather than `require_admin`: these routes mint
credentials, and the whole point of containing an API key is that holding one
cannot produce another. A leaked n8n key can read and write the data its
account owns; it cannot bootstrap itself into a second, quieter credential.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_human_admin
from app.core import api_key as api_key_utils
from app.db import models
from app.db.session import get_db
from app.schemas.api_key import ApiKey, ApiKeyCreate, ApiKeyCreated
from app.services import audit

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyCreated, status_code=201)
def create_api_key(
    payload: ApiKeyCreate,
    request: Request,
    admin: models.Users = Depends(require_human_admin),
    db: Session = Depends(get_db),
) -> ApiKeyCreated:
    """Mint a key for the calling admin's account.

    The secret is in this response and nowhere else — only its SHA-256 is
    stored. There is deliberately no endpoint that can show it again.
    """
    generated = api_key_utils.generate_key()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)
        if payload.expires_in_days
        else None
    )

    record = models.ApiKey(
        name=payload.name,
        prefix=generated.prefix,
        key_hash=generated.key_hash,
        user_id=admin.user_id,
        expires_at=expires_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    audit.record(
        db,
        action=audit.API_KEY_CREATE,
        request=request,
        actor=admin,
        target_type="api_key",
        target_id=record.key_id,
        # The clear prefix, never the secret — it is the uniquely indexed
        # lookup component and is exactly what identifies the key later, both
        # in this log and in the list view.
        detail={"name": record.name, "prefix": record.prefix, "expires_at": expires_at},
    )

    return ApiKeyCreated(
        **ApiKey.model_validate(record).model_dump(), secret=generated.secret
    )


@router.get("", response_model=list[ApiKey])
def list_api_keys(
    _: models.Users = Depends(require_human_admin),
    db: Session = Depends(get_db),
) -> list[ApiKey]:
    keys = db.scalars(
        select(models.ApiKey).order_by(models.ApiKey.created_at.desc())
    ).all()
    return [ApiKey.model_validate(key) for key in keys]


@router.delete("/{key_id}", status_code=204)
def revoke_api_key(
    key_id: uuid.UUID,
    request: Request,
    admin: models.Users = Depends(require_human_admin),
    db: Session = Depends(get_db),
) -> None:
    """Revoke a key.

    The row is kept rather than deleted: `last_used_at` on a revoked key is the
    only record of when a credential you have just turned off was last active,
    which is the first thing anyone asks after revoking one in anger.
    """
    record = db.get(models.ApiKey, key_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"api key {key_id} not found")
    record.revoked = True
    db.commit()

    audit.record(
        db,
        action=audit.API_KEY_REVOKE,
        request=request,
        actor=admin,
        target_type="api_key",
        target_id=record.key_id,
        # `last_used_at` is the question everyone asks straight after revoking
        # a key in anger, so it goes in the record of the revocation itself
        # rather than only in a row somebody has to think to go and read.
        detail={
            "name": record.name,
            "prefix": record.prefix,
            "last_used_at": record.last_used_at,
        },
    )
