"""Chat request/response schemas.

Field names match `app.db.models.Chat` / `models.Message` column names, for the
same reason the report schema does: storage is a straight construction from the
validated object, with no mapping step that can drift.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AttachedDocument(BaseModel):
    """One document a chat is grounded in.

    Stored in `chats.attached_documents` (JSON), so the shape is pinned here
    rather than being an untyped dict built at three different call sites — the
    prototype's version was assembled inline and read back with `doc["..."]`.
    """

    document_id: uuid.UUID
    document_name: str


class ChatMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: uuid.UUID
    role: str
    context: str
    status: str
    created_at: datetime


class ChatSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chat_id: uuid.UUID
    chat_name: str
    user_id: uuid.UUID
    updated_at: datetime
    attached_documents: list[AttachedDocument] = Field(default_factory=list)


class ChatDetail(ChatSummary):
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatCreate(BaseModel):
    """Open a new conversation, optionally grounded in uploaded documents."""

    chat_name: str | None = Field(default=None, max_length=255)
    document_ids: list[uuid.UUID] = Field(default_factory=list)


class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class Source(BaseModel):
    """A retrieved chunk the answer was grounded in.

    Returned to the client so the UI can show what the answer was based on.
    An assistant that cites nothing is indistinguishable from one that made it
    up, which is the whole risk with RAG over security logs.
    """

    document_id: uuid.UUID
    document_name: str
    excerpt: str


class SendMessageResponse(BaseModel):
    chat_id: uuid.UUID
    user_message: ChatMessage
    assistant_message: ChatMessage
    sources: list[Source] = Field(default_factory=list)
