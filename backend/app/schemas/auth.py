"""Auth and user schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserPublic(BaseModel):
    """A user as returned by the API. Never includes password_hash.

    `email` is a plain `str` here, not `EmailStr`, on purpose. Addresses are
    validated strictly on the way *in* (UserCreate). Re-validating on the way
    *out* means one historical row with an address the validator dislikes —
    a reserved domain like `.local`, say — raises inside the list endpoint and
    takes down the listing for every user, not just that one.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    role: str
    status: str
    organization: str
    location: str
    bio: str | None = None
    phone_number: str | None = None
    mfa: bool
    last_login_at: datetime | None = None
    created_at: datetime


class UserCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    phone_number: str | None = Field(default=None, max_length=50)
    organization: str = "-"
    location: str = "UAE"


class AdminUserCreate(UserCreate):
    """Admin-created users may be given a role directly."""

    role: str = "analyst"


class UserRoleUpdate(BaseModel):
    role: str = Field(min_length=1, max_length=50)


class UserStatusUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=50)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=72)
