"""Ingestion: load a log file, extract metadata, chunk it, embed it.

Ported from the prototype's `backend/ai/rag/ingest_data.py`. Changes:

- **The `from backend.main import *` circular import is gone.** That line made
  the RAG package import the FastAPI app, which imported the DB module, which
  dropped every table at import time.
- `ingest()` takes a path, an extension and a document id rather than a
  SQLAlchemy `Document` instance, so ingestion has no dependency on the ORM
  and can be tested without a database.
- Metadata values are coerced to Chroma-safe scalars; Chroma rejects `None`
  and non-primitive metadata values.

Loader behaviour and the metadata field set are otherwise unchanged.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from app.services.rag.chunk import chunk_logs
from app.services.rag.vectorstore import add_chunks

SUPPORTED_EXTENSIONS = {".csv", ".json", ".txt", ".log"}


# --- Loaders -------------------------------------------------------------


def normalize_json(file: Any) -> pd.DataFrame:
    """Flatten nested JSON into a DataFrame."""
    if isinstance(file, list):
        return pd.json_normalize(file)
    if isinstance(file, dict):
        return pd.json_normalize([file])
    raise ValueError(f"Unsupported JSON top-level type: {type(file).__name__}")


def load_json(path: str | Path) -> pd.DataFrame:
    with open(path, encoding="utf-8") as json_file:
        return normalize_json(json.load(json_file))


def load_csv(path: str | Path) -> pd.DataFrame:
    with open(path, encoding="utf-8") as csv_file:
        return pd.read_csv(csv_file)


def load_txt_log(path: str | Path) -> str:
    with open(path, encoding="utf-8") as txt_log:
        return txt_log.read()


def load_file(path: str | Path, extension: str) -> pd.DataFrame | str:
    """Dispatch to the loader for `extension`."""
    if extension == ".json":
        return load_json(path)
    if extension == ".csv":
        return load_csv(path)
    if extension in (".log", ".txt"):
        return load_txt_log(path)
    raise ValueError(
        f"Unsupported extension {extension!r}. Supported: {sorted(SUPPORTED_EXTENSIONS)}"
    )


# --- Metadata ------------------------------------------------------------


def extract_metadata(
    loaded_file: pd.DataFrame | str,
    extension: str,
    document_id: str,
    path: str | Path,
) -> dict[str, Any]:
    """Build the per-chunk metadata describing the source file."""
    path = Path(path)
    metadata: dict[str, Any] = {
        "source": str(path),
        "file_name": path.name,
        "file_size": os.path.getsize(path) if path.exists() else None,
        "extension": extension,
        "document_id": str(document_id),
    }

    if extension in (".csv", ".json") and isinstance(loaded_file, pd.DataFrame):
        df = loaded_file
        metadata.update(
            {
                "data_type": "structured",
                "row_count": len(df),
                "column_count": len(df.columns),
                "user_id": "user_id" in df.columns,
                "timestamps": any(
                    "time" in col.lower() or "date" in col.lower() for col in df.columns
                ),
                "main_columns": str(list(df.columns[:5])),
            }
        )
    elif extension in (".txt", ".log"):
        lines = loaded_file.split("\n") if isinstance(loaded_file, str) else loaded_file
        metadata.update({"data_type": "text", "row_count": len(lines)})

    return _chroma_safe(metadata)


def _chroma_safe(metadata: dict[str, Any]) -> dict[str, Any]:
    """Drop `None`s and stringify anything Chroma can't store as metadata."""
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        safe[key] = value if isinstance(value, (str, int, float, bool)) else str(value)
    return safe


# --- Execution order -----------------------------------------------------


def ingest(path: str | Path, extension: str, document_id: str) -> int:
    """Load, chunk and embed a file. Returns the number of chunks stored."""
    loaded_file = load_file(path, extension)

    if isinstance(loaded_file, pd.DataFrame):
        loaded_file = loaded_file.copy()
        loaded_file["row_id"] = loaded_file.index

    metadata = extract_metadata(loaded_file, extension, document_id, path)
    chunked_logs = chunk_logs(metadata, loaded_file, extension)
    add_chunks(chunked_logs)
    return len(chunked_logs)
