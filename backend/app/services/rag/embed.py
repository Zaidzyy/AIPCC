"""Embedding model.

Ported from the prototype's `backend/ai/rag/embed_data.py`. Two changes: the
model name and device come from config instead of module constants, and the
model is loaded lazily. The prototype instantiated `HuggingFaceEmbeddings` at
import time, which downloads/loads ~90MB of MiniLM weights before the app can
serve its first request — and on every test collection.
"""

from functools import lru_cache

from langchain_huggingface import HuggingFaceEmbeddings

from app.core.config import settings


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    """Return the process-wide embedding model, loading it on first use."""
    return HuggingFaceEmbeddings(
        model_name=settings.embedding_model,
        model_kwargs={"device": settings.embedding_device},
    )
