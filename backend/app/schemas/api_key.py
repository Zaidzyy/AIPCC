"""API key schemas.

`ApiKeyCreated` is the only schema that ever carries the secret, and it is
returned exactly once — from the create call. Everything else describes a key
without being able to reconstruct it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # Null means the key does not expire, which is the point for a scheduled
    # workflow: it is retired by revoking it, not by outliving a clock.
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKey(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key_id: uuid.UUID
    name: str
    prefix: str
    user_id: uuid.UUID
    created_at: datetime | None = None
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked: bool


class ApiKeyCreated(ApiKey):
    """The create response. `secret` is shown once and never stored in clear."""

    secret: str
