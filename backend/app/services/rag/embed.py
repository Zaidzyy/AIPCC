"""Embedding model.

Ported from the prototype's `backend/ai/rag/embed_data.py`. Two changes: the
model name and device come from config instead of module constants, and the
model is loaded lazily. The prototype instantiated `HuggingFaceEmbeddings` at
import time, which downloads/loads ~90MB of MiniLM weights before the app can
serve its first request — and on every test collection.
"""

import threading

from langchain_huggingface import HuggingFaceEmbeddings

from app.core.config import settings

_embeddings: HuggingFaceEmbeddings | None = None
_embeddings_lock = threading.Lock()


def get_embeddings() -> HuggingFaceEmbeddings:
    """Return the process-wide embedding model, loading it on first use.

    Locked for the same reason as the vector store: concurrent retrieval would
    otherwise have several threads each loading MiniLM's weights at once.
    """
    global _embeddings
    if _embeddings is None:
        with _embeddings_lock:
            if _embeddings is None:
                _embeddings = HuggingFaceEmbeddings(
                    model_name=settings.embedding_model,
                    model_kwargs={"device": settings.embedding_device},
                )
    return _embeddings
