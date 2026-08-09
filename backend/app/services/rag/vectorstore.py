"""Chroma vector store.

Ported from the prototype's `backend/apicc_databases/chroma_db/chroma_database.py`.
`persist_directory` and the collection name move into config (the prototype
hardcoded "./chroma_langchain_db", which resolved relative to whatever
directory the process happened to start in), and the store is built lazily
rather than at import.
"""

import threading

from langchain_chroma import Chroma

from app.core.config import settings
from app.services.rag.embed import get_embeddings

_store: Chroma | None = None
_store_lock = threading.Lock()


def get_vectorstore() -> Chroma:
    """Return the process-wide Chroma store, opening it on first use.

    Double-checked locking rather than `@lru_cache`. The five report sections
    retrieve concurrently via `asyncio.to_thread`, and `lru_cache` does not make
    the *construction* of a missing entry atomic — several threads entered this
    function at once and each tried to open the same Chroma directory, which
    failed with "Could not connect to tenant default_tenant". Only the first
    caller builds; the lock is never held on the hot path afterwards.
    """
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                settings.chroma_dir.mkdir(parents=True, exist_ok=True)
                _store = Chroma(
                    collection_name=settings.chroma_collection,
                    embedding_function=get_embeddings(),
                    persist_directory=str(settings.chroma_dir),
                )
    return _store


def add_chunks(chunked_logs: list[dict]) -> list[str]:
    """Embed and store chunks produced by `chunk.chunk_logs`.

    Returns the Chroma ids of the added texts.
    """
    if not chunked_logs:
        return []
    return get_vectorstore().add_texts(
        texts=[log["chunk"] for log in chunked_logs],
        metadatas=[log["metadata"] for log in chunked_logs],
    )


def count_chunks(document_id: str | None = None) -> int:
    """Number of stored chunks, optionally scoped to one document.

    Used by the Phase 0 ingest verification and by tests.
    """
    where = {"document_id": str(document_id)} if document_id else None
    return len(get_vectorstore().get(where=where)["ids"])
