"""Chat over ingested documents.

Every route resolves its caller through `get_current_user`, and every chat is
ownership-scoped exactly like documents and reports: a non-owner gets 404, not
403, so ids cannot be probed for existence.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import authorize_owner, get_current_user, is_admin
from app.db import models
from app.db.session import get_db
from app.schemas.chat import (
    AttachedDocument,
    ChatCreate,
    ChatDetail,
    ChatMessage,
    ChatSummary,
    SendMessageRequest,
    SendMessageResponse,
    Source,
)
from app.services.chatbot import EXCERPT_CHARS, ChatTurn, answer, derive_chat_name
from app.services.llm import LLMError

router = APIRouter(tags=["chat"])


@router.get("/chats", response_model=list[ChatSummary])
def list_chats(
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ChatSummary]:
    statement = select(models.Chat).order_by(models.Chat.updated_at.desc())
    if not is_admin(user):
        statement = statement.where(models.Chat.user_id == user.user_id)
    return [ChatSummary.model_validate(chat) for chat in db.scalars(statement).all()]


@router.post("/chats", response_model=ChatDetail, status_code=201)
def create_chat(
    payload: ChatCreate,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatDetail:
    """Open a conversation, optionally grounded in documents the caller owns."""
    attached = [
        AttachedDocument(
            document_id=document.document_id, document_name=document.document_name
        )
        for document in _resolve_documents(db, user, payload.document_ids)
    ]

    chat = models.Chat(
        chat_name=payload.chat_name or "New chat",
        user_id=user.user_id,
        attached_documents=[item.model_dump(mode="json") for item in attached],
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return ChatDetail.model_validate(chat)


@router.get("/chats/{chat_id}", response_model=ChatDetail)
def get_chat(
    chat_id: uuid.UUID,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatDetail:
    chat = _get_authorized_chat(db, user, chat_id)
    return ChatDetail.model_validate(chat)


@router.delete("/chats/{chat_id}", status_code=204)
def delete_chat(
    chat_id: uuid.UUID,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    chat = _get_authorized_chat(db, user, chat_id)
    db.delete(chat)
    db.commit()


@router.post("/chats/{chat_id}/messages", response_model=SendMessageResponse)
async def send_message(
    chat_id: uuid.UUID,
    payload: SendMessageRequest,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SendMessageResponse:
    """Answer a question in this chat and persist both sides of the turn.

    The user's message is stored before the provider is called, so a provider
    outage loses the answer but never the question. The prototype stored both
    only on success, inside the same `try` as the LLM call.
    """
    chat = _get_authorized_chat(db, user, chat_id)

    documents = [
        (uuid.UUID(str(item["document_id"])), str(item["document_name"]))
        for item in (chat.attached_documents or [])
    ]
    history = [ChatTurn(role=m.role, context=m.context) for m in chat.messages]

    user_message = models.Message(
        chat_id=chat.chat_id, role="human", context=payload.message, status="complete"
    )
    db.add(user_message)

    # Name the chat from its opening question rather than leaving "New chat".
    if not chat.messages and chat.chat_name == "New chat":
        chat.chat_name = derive_chat_name(payload.message)

    db.commit()
    db.refresh(user_message)

    try:
        reply, chunks = await answer(payload.message, documents, history)
    except LLMError as exc:
        # Record the failed turn so the conversation shows what happened
        # instead of silently dropping the question.
        user_message.status = "failed"
        db.commit()
        raise HTTPException(502, f"the language model is unavailable: {exc}") from exc

    assistant_message = models.Message(
        chat_id=chat.chat_id, role="assistant", context=reply, status="complete"
    )
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)

    return SendMessageResponse(
        chat_id=chat.chat_id,
        user_message=ChatMessage.model_validate(user_message),
        assistant_message=ChatMessage.model_validate(assistant_message),
        sources=[
            Source(
                document_id=chunk.document_id,
                document_name=chunk.document_name,
                excerpt=chunk.content[:EXCERPT_CHARS],
            )
            for chunk in chunks
        ],
    )


def _resolve_documents(
    db: Session, user: models.Users, document_ids: list[uuid.UUID]
) -> list[models.Document]:
    """Load the requested documents, rejecting any the caller may not read."""
    documents: list[models.Document] = []
    for document_id in dict.fromkeys(document_ids):
        document = db.get(models.Document, document_id)
        if document is None:
            raise HTTPException(404, f"document {document_id} not found")
        authorize_owner(user, document.user_id)
        documents.append(document)
    return documents


def _get_authorized_chat(
    db: Session, user: models.Users, chat_id: uuid.UUID
) -> models.Chat:
    chat = db.scalar(
        select(models.Chat)
        .where(models.Chat.chat_id == chat_id)
        .options(selectinload(models.Chat.messages))
    )
    if chat is None:
        raise HTTPException(404, f"chat {chat_id} not found")
    authorize_owner(user, chat.user_id)
    return chat
