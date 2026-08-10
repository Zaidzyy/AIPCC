"""Chunking, and the provenance that survives it.

The splitter logic is the prototype's (PORTING.md judged it sound); chunk size
and overlap come from config. What Phase 10 adds is the part the prototype
threw away: **which source rows or lines each chunk actually covers**.

That mapping exists at this moment and nowhere else. `chunk_logs` serialises a
DataFrame to CSV text and hands the text to a character splitter, so once the
chunks come back there is no way to recover which rows produced them. Recording
it here is what lets a finding cite chunk 7 and the UI show the analyst the
three log rows chunk 7 was made of.

**The row mapping is exact or absent, never approximate.** For tabular sources
it assumes `to_csv` writes exactly one physical line per row, which is true
unless a field contains a newline. That assumption is *checked* — if the data
line count does not equal the row count, row provenance is omitted for that
document and a warning is logged. A citation that points at the wrong log rows
is worse than one that admits it cannot point at any.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings

logger = logging.getLogger(__name__)

# Extensions whose loaded form is a DataFrame and must be serialized to text
# before splitting.
TABULAR_EXTENSIONS = {".csv", ".json"}


def serialize(loaded_file: pd.DataFrame | str, extension: str) -> str:
    if extension in TABULAR_EXTENSIONS and isinstance(loaded_file, pd.DataFrame):
        return loaded_file.to_csv(index=False)
    return loaded_file


def line_offsets(text: str) -> list[int]:
    """Character offset at which each line starts.

    Built once per document and reused for every chunk, so locating a chunk's
    line span is a binary search rather than a re-scan of the whole file.
    """
    offsets = [0]
    for index, char in enumerate(text):
        if char == "\n":
            offsets.append(index + 1)
    return offsets


def _line_at(offsets: list[int], position: int) -> int:
    """0-based line number containing `position`."""
    low, high = 0, len(offsets) - 1
    while low < high:
        mid = (low + high + 1) // 2
        if offsets[mid] <= position:
            low = mid
        else:
            high = mid - 1
    return low


def chunk_logs(
    metadata: dict[str, Any],
    loaded_file: pd.DataFrame | str,
    extension: str,
) -> list[dict[str, Any]]:
    """Split a loaded file into chunks, each carrying provenance and metadata.

    Every chunk's metadata gains `char_start`/`char_end` and
    `line_start`/`line_end` (1-based, inclusive), and — for a tabular source
    whose serialisation is verifiably one line per row — `row_start`/`row_end`
    as 0-based DataFrame row indices.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )

    text = serialize(loaded_file, extension)
    offsets = line_offsets(text)

    tabular = extension in TABULAR_EXTENSIONS and isinstance(loaded_file, pd.DataFrame)
    rows_mappable = tabular and _rows_are_one_line_each(loaded_file, text, metadata)

    chunked_logs: list[dict[str, Any]] = []
    # Chunks come back in document order, so the search for each one starts
    # where the last ended. Searching from zero would mis-locate a chunk whose
    # text repeats earlier in the file — common in logs, where a hundred lines
    # can be byte-identical.
    cursor = 0
    for i, chunk in enumerate(splitter.split_text(text)):
        found = text.find(chunk, cursor)
        if found == -1:
            # The splitter strips whitespace at chunk boundaries, so a chunk is
            # not always a literal substring. Fall back to the cursor rather
            # than recording an offset that is wrong.
            found = cursor
        char_start = found
        char_end = found + len(chunk)
        cursor = char_end

        first_line = _line_at(offsets, char_start)
        last_line = _line_at(offsets, max(char_start, char_end - 1))

        chunk_metadata = {
            **metadata,
            "chunk_id": i,
            "type": "text",
            "char_start": char_start,
            "char_end": char_end,
            # 1-based and inclusive, because these are shown to a person next
            # to a log file, and no text editor numbers its first line 0.
            "line_start": first_line + 1,
            "line_end": last_line + 1,
        }

        if rows_mappable:
            # Line 1 is the CSV header, so data row N lives on line N + 2.
            start_row = max(0, first_line - 1)
            end_row = max(start_row, last_line - 1)
            chunk_metadata["row_start"] = start_row
            chunk_metadata["row_end"] = min(end_row, len(loaded_file) - 1)

        chunked_logs.append({"chunk": chunk, "metadata": chunk_metadata})

    return chunked_logs


def _rows_are_one_line_each(
    frame: pd.DataFrame, text: str, metadata: dict[str, Any]
) -> bool:
    """Verify the assumption row provenance rests on, rather than trusting it.

    `to_csv` quotes a field containing a newline instead of escaping it, so the
    row lands across several physical lines and every row number after it is
    wrong. Checking the counts costs one comparison and is the difference
    between "no row provenance for this file" and "confidently wrong row
    numbers", which is much worse: a citation is only useful if it can be
    trusted without checking.
    """
    data_lines = text.count("\n")
    if text and not text.endswith("\n"):
        data_lines += 1
    data_lines -= 1  # the header

    if data_lines == len(frame):
        return True

    logger.warning(
        "row provenance unavailable: serialised line count does not match row count",
        extra={
            "document_id": metadata.get("document_id"),
            "rows": len(frame),
            "lines": data_lines,
        },
    )
    return False
