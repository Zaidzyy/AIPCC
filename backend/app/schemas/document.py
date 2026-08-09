"""Document request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    document_name: str
    document_size: float
    document_extension: str
    uploaded_at: datetime
    user_id: uuid.UUID


class DocumentDetail(DocumentSummary):
    chunk_count: int


class LatestDocumentContent(BaseModel):
    """Payload for GET /get_latest_document_content (consumed by n8n)."""

    document_id: uuid.UUID
    document_name: str
    document_extension: str
    uploaded_at: datetime
    truncated: bool
    content: str
