"""Chunking.

Ported essentially as-is from the prototype's `backend/ai/rag/chunk_data.py`
(PORTING.md judged the splitter logic sound). Only change: chunk size and
overlap come from config.
"""

from typing import Any

import pandas as pd
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings

# Extensions whose loaded form is a DataFrame and must be serialized to text
# before splitting.
TABULAR_EXTENSIONS = {".csv", ".json"}


def chunk_logs(
    metadata: dict[str, Any],
    loaded_file: pd.DataFrame | str,
    extension: str,
) -> list[dict[str, Any]]:
    """Split a loaded file into chunks, each carrying a copy of the metadata."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )

    if extension in TABULAR_EXTENSIONS and isinstance(loaded_file, pd.DataFrame):
        text = loaded_file.to_csv(index=False)
    else:
        text = loaded_file

    chunked_logs: list[dict[str, Any]] = []
    for i, chunk in enumerate(splitter.split_text(text)):
        chunk_metadata = {**metadata, "chunk_id": i, "type": "text"}
        chunked_logs.append({"chunk": chunk, "metadata": chunk_metadata})

    return chunked_logs
