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


def chunk_key(document_id: str, chunk_id: int) -> str:
    """The stable identity of one chunk — Phase 10's citation key.

    `(document_id, chunk_id)` is stable across re-ingest because the splitter
    is deterministic: the same bytes and the same chunk size produce the same
    chunk at the same index. What was *not* stable was Chroma's own id, which
    `add_texts` generated randomly, so re-ingesting the same file appended a
    second copy of every chunk under new ids rather than replacing it.

    Using this as the Chroma id makes re-ingest an upsert, makes a citation
    resolvable by direct lookup instead of a metadata scan, and makes the Phase
    7 idempotency guard a second line of defence rather than the only one.
    """
    return f"{document_id}:{chunk_id}"


def add_chunks(chunked_logs: list[dict]) -> list[str]:
    """Embed and store chunks produced by `chunk.chunk_logs`.

    Returns the Chroma ids of the added texts.
    """
    if not chunked_logs:
        return []
    ids = [
        chunk_key(str(log["metadata"]["document_id"]), int(log["metadata"]["chunk_id"]))
        for log in chunked_logs
    ]
    return get_vectorstore().add_texts(
        texts=[log["chunk"] for log in chunked_logs],
        metadatas=[log["metadata"] for log in chunked_logs],
        ids=ids,
    )


def count_chunks(document_id: str | None = None) -> int:
    """Number of stored chunks, optionally scoped to one document.

    Used by the Phase 0 ingest verification and by tests.
    """
    where = {"document_id": str(document_id)} if document_id else None
    return len(get_vectorstore().get(where=where)["ids"])


def get_chunks(document_id: str, chunk_ids: list[int] | None = None) -> dict[int, dict]:
    """Load chunks for one document, keyed by `chunk_id`.

    With `chunk_ids`, fetched by primary key — which is the whole point of
    making the id deterministic. Without, the document's whole chunk set, used
    to answer "does chunk N exist here" when a model cites one.

    Chroma returns ids it was not asked for as absent rather than raising, so a
    fabricated citation simply does not come back — no exception handling, and
    no way for a missing chunk to be mistaken for a present one.
    """
    store = get_vectorstore()
    if chunk_ids is not None:
        if not chunk_ids:
            return {}
        result = store.get(ids=[chunk_key(str(document_id), i) for i in chunk_ids])
    else:
        result = store.get(where={"document_id": str(document_id)})

    chunks: dict[int, dict] = {}
    for content, metadata in zip(
        result.get("documents") or [], result.get("metadatas") or [], strict=False
    ):
        metadata = metadata or {}
        if "chunk_id" not in metadata:
            continue
        chunks[int(metadata["chunk_id"])] = {"content": content, "metadata": metadata}
    return chunks


def chunk_ids_for(document_id: str) -> set[int]:
    """Every chunk index that exists for this document.

    This set is the arbiter of whether a citation is real. A model citing an
    index outside it has fabricated a source, which is the specific failure
    Phase 10 exists to catch.
    """
    return set(get_chunks(document_id).keys())
