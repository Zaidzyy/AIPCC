"""Chat over ingested documents.

Ported in spirit from the prototype's `backend/ai/chatbot.py`, rebuilt around
the same rules the report generator follows:

- **No database access in here.** The prototype's `answer_prompt` opened a
  module-level `session`, wrote `Chat` and `Message` rows, mutated
  `attached_documents` and called the LLM, all inside one function wrapped in a
  bare `except` that returned `(chat_id, None)` on any failure — so a retrieval
  bug and a provider outage were indistinguishable. Persistence lives in the
  router; this module takes plain values and returns plain values, which makes
  it testable with no DB and no vector store.
- **Provider failures surface.** `LLMError` propagates rather than becoming a
  silent `None`.
- **History is passed in, not fetched.** No `RunnableWithMessageHistory`, no
  hidden second query.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from app.services.llm import LLMProvider, get_llm_provider

logger = logging.getLogger(__name__)

# How many chunks to pull per attached document.
RETRIEVAL_K = 6

# How much prior conversation to replay into the prompt. Chat history is
# unbounded in the database; the prompt is not.
HISTORY_LIMIT = 12

# Longest excerpt returned to the client per source.
EXCERPT_CHARS = 400

SYSTEM_RULES = """You are AIPCC, a cybersecurity analysis assistant.

- Answer questions about security, the user's ingested log data, and their reports.
- If the question is not related to cybersecurity or to the data below, say so briefly
  and do not answer it.
- Ground every factual claim in the CONTEXT below. If the context does not contain
  the answer, say that plainly rather than guessing.
- Never provide instructions for exploiting or damaging a system.
- Be concise and direct. Prefer specifics from the data over general advice."""


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: uuid.UUID
    document_name: str
    content: str


@dataclass(frozen=True)
class ChatTurn:
    """One prior message, as stored: role is "human" or "assistant"."""

    role: str
    context: str


def retrieve_chunks(
    question: str,
    documents: list[tuple[uuid.UUID, str]],
    k: int = RETRIEVAL_K,
) -> list[RetrievedChunk]:
    """Fetch chunks relevant to `question` from each attached document.

    `documents` is a list of (document_id, document_name). Retrieval is scoped
    per document so an answer can name its source, and so a chat attached to
    nothing retrieves nothing rather than searching every user's logs.
    """
    if not documents:
        return []

    from app.services.rag.vectorstore import get_vectorstore

    store = get_vectorstore()
    chunks: list[RetrievedChunk] = []
    seen: set[str] = set()

    for document_id, document_name in documents:
        hits = store.similarity_search(
            question, k=k, filter={"document_id": str(document_id)}
        )
        for hit in hits:
            if hit.page_content in seen:
                continue
            seen.add(hit.page_content)
            chunks.append(
                RetrievedChunk(
                    document_id=document_id,
                    document_name=document_name,
                    content=hit.page_content,
                )
            )
    return chunks


def build_prompt(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[ChatTurn],
) -> str:
    """Assemble the single prompt string the provider contract accepts.

    `LLMProvider.complete()` is deliberately text-in/text-out (see
    `services/llm/base.py`), so the system rules, retrieved context and history
    are flattened here rather than leaking LangChain message types outward.
    """
    if chunks:
        context = "\n--\n".join(
            f"from '{chunk.document_name}': {chunk.content}" for chunk in chunks
        )
    else:
        context = "(no documents are attached to this conversation)"

    recent = history[-HISTORY_LIMIT:]
    if recent:
        transcript = "\n".join(
            f"{'User' if turn.role == 'human' else 'Assistant'}: {turn.context}"
            for turn in recent
        )
    else:
        transcript = "(this is the first message)"

    return f"""{SYSTEM_RULES}

CONTEXT
-------
{context}

CONVERSATION SO FAR
-------------------
{transcript}

USER
----
{question}

Answer as the assistant. Return prose only — no JSON, no markdown code fences.
"""


async def answer(
    question: str,
    documents: list[tuple[uuid.UUID, str]],
    history: list[ChatTurn],
    provider: LLMProvider | None = None,
) -> tuple[str, list[RetrievedChunk]]:
    """Answer `question`, returning the reply and the chunks it was grounded in.

    Raises `LLMError` if the provider fails — the caller decides what that means
    for the stored conversation.
    """
    provider = provider or get_llm_provider()

    import asyncio

    chunks = await asyncio.to_thread(retrieve_chunks, question, documents)
    reply = await provider.complete(build_prompt(question, chunks, history))
    return reply.strip(), chunks


def derive_chat_name(first_message: str, limit: int = 60) -> str:
    """Name a new chat from its opening message.

    The prototype spent a whole extra LLM round trip on this, which meant a
    provider hiccup could fail chat *creation* rather than just the answer.
    Truncating the first line is good enough for a sidebar label and cannot
    fail.
    """
    cleaned = " ".join(first_message.split())
    if not cleaned:
        return "New chat"
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"
