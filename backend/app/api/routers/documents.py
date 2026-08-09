"""Document upload and retrieval.

The owner is always the authenticated caller — never a value taken from the
request body, and never a module-level global.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import authorize_owner, get_current_user, is_admin
from app.core.config import settings
from app.db import models
from app.db.session import get_db
from app.schemas.document import DocumentDetail, DocumentSummary, LatestDocumentContent
from app.services.rag.ingest import SUPPORTED_EXTENSIONS, ingest

router = APIRouter(tags=["documents"])

# Cap uploads so a stray multi-GB file cannot fill the disk.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


@router.post("/upload_file", response_model=DocumentDetail, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    """Store a log file, register it, and ingest it into the vector store."""
    if not file.filename:
        raise HTTPException(400, "file has no filename")

    extension = Path(file.filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            400,
            f"unsupported file type {extension!r}. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"file exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit"
        )
    if not payload:
        raise HTTPException(400, "file is empty")

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    # Prefix with a UUID so two uploads of "auth.log" cannot overwrite one
    # another, and so a crafted filename cannot escape the upload directory.
    stored_name = f"{uuid.uuid4().hex}_{Path(file.filename).name}"
    destination = settings.upload_dir / stored_name
    destination.write_bytes(payload)

    now = datetime.now(timezone.utc)
    document = models.Document(
        document_name=Path(file.filename).name,
        document_size=float(len(payload)),
        document_extension=extension,
        document_path=str(destination),
        created_at=now,
        modified_at=now,
        uploaded_at=now,
        user_id=user.user_id,
    )
    db.add(document)
    db.flush()

    try:
        chunk_count = ingest(destination, extension, str(document.document_id))
    except Exception as exc:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise HTTPException(500, f"ingestion failed: {exc}") from exc

    db.commit()
    db.refresh(document)

    return DocumentDetail.model_validate(
        {**_as_dict(document), "chunk_count": chunk_count}
    )


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentSummary]:
    statement = select(models.Document).order_by(models.Document.uploaded_at.desc())
    if not is_admin(user):
        statement = statement.where(models.Document.user_id == user.user_id)
    return [DocumentSummary.model_validate(d) for d in db.scalars(statement).all()]


@router.get("/get_latest_document_content", response_model=LatestDocumentContent)
def get_latest_document_content(
    max_chars: int = 200_000,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LatestDocumentContent:
    """Return the caller's most recently uploaded document as raw text.

    Called by the n8n AI Security Report Orchestrator, which previously
    pointed at this path with nothing behind it.
    """
    statement = select(models.Document).order_by(models.Document.uploaded_at.desc())
    if not is_admin(user):
        statement = statement.where(models.Document.user_id == user.user_id)

    document = db.scalars(statement.limit(1)).first()
    if document is None:
        raise HTTPException(404, "no documents have been uploaded")

    path = Path(document.document_path)
    if not path.exists():
        raise HTTPException(
            410, f"document {document.document_id} is registered but its file is missing"
        )

    content = path.read_text(encoding="utf-8", errors="replace")
    truncated = len(content) > max_chars

    return LatestDocumentContent(
        document_id=document.document_id,
        document_name=document.document_name,
        document_extension=document.document_extension,
        uploaded_at=document.uploaded_at,
        truncated=truncated,
        content=content[:max_chars],
    )


@router.get("/documents/{document_id}", response_model=DocumentSummary)
def get_document(
    document_id: uuid.UUID,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentSummary:
    document = db.get(models.Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"document {document_id} not found")
    authorize_owner(user, document.user_id)
    return DocumentSummary.model_validate(document)


def _as_dict(document: models.Document) -> dict:
    return {
        "document_id": document.document_id,
        "document_name": document.document_name,
        "document_size": document.document_size,
        "document_extension": document.document_extension,
        "uploaded_at": document.uploaded_at,
        "user_id": document.user_id,
    }
