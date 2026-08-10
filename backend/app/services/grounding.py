"""Evidence grounding: tying every finding to the log content that produced it.

A security analyst will not act on an unsourced claim from a language model.
This module is what turns "the model says there was a brute-force attempt" into
"the model says that, and here are the four log rows it read".

**Three rules, and the third is the one that matters.**

1. The model is shown numbered chunks and asked to cite the numbers it used.
2. Every citation is then *resolved against what it was actually shown*. A
   citation to a chunk that does not exist in that document is a fabrication;
   so is a citation to a chunk that exists but was never retrieved for that
   section, because the model could not have read it. Both are counted and
   neither is stored.
3. **A finding with no valid evidence is flagged, never dropped.** Dropping it
   would make the report look cleaner than the model's actual output, which is
   the same failure as an empty section reported as a success — and it would
   make the grounding rate unmeasurable, since the ungrounded findings would no
   longer exist to count. An analyst is better served by "the model claims this
   and could not point at anything" than by silence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# How much of a chunk is kept as the excerpt shown beside a finding. Long
# enough to be readable in the UI without a second request; short enough that a
# report with sixty findings does not carry the whole log file in its response.
EXCERPT_CHARS = 800


@dataclass(frozen=True)
class SourceChunk:
    """One retrieved chunk, with the provenance recorded at ingest."""

    chunk_id: int
    content: str
    row_start: int | None = None
    row_end: int | None = None
    line_start: int | None = None
    line_end: int | None = None

    @classmethod
    def from_document(cls, document) -> SourceChunk:
        """Build from a LangChain `Document` as Chroma returns it."""
        metadata = document.metadata or {}
        return cls(
            chunk_id=int(metadata.get("chunk_id", -1)),
            content=document.page_content,
            row_start=_optional_int(metadata.get("row_start")),
            row_end=_optional_int(metadata.get("row_end")),
            line_start=_optional_int(metadata.get("line_start")),
            line_end=_optional_int(metadata.get("line_end")),
        )

    def locator(self) -> str:
        """How this chunk is described to a person: rows if known, else lines."""
        if self.row_start is not None:
            if self.row_end is not None and self.row_end != self.row_start:
                return f"rows {self.row_start}–{self.row_end}"
            return f"row {self.row_start}"
        if self.line_start is not None:
            if self.line_end is not None and self.line_end != self.line_start:
                return f"lines {self.line_start}–{self.line_end}"
            return f"line {self.line_start}"
        return "unlocated"


@dataclass
class EvidenceRecord:
    """One resolved citation, on its way to `finding_evidence`."""

    section: str
    item_index: int
    chunk_id: int
    excerpt: str
    row_start: int | None = None
    row_end: int | None = None
    line_start: int | None = None
    line_end: int | None = None


@dataclass
class GroundingResult:
    """What resolving one section's citations produced."""

    records: list[EvidenceRecord] = field(default_factory=list)
    # Cited chunks that do not exist in this document at all — the clearest
    # form of fabricated source.
    unknown_citations: int = 0
    # Cited chunks that exist but were not retrieved for this section. Still a
    # fabrication: the model was never shown them, so it cannot have read them.
    unseen_citations: int = 0
    # Findings that ended up with nothing valid to point at.
    ungrounded_items: int = 0

    @property
    def invalid_citations(self) -> int:
        return self.unknown_citations + self.unseen_citations

    def merge(self, other: GroundingResult) -> None:
        self.records.extend(other.records)
        self.unknown_citations += other.unknown_citations
        self.unseen_citations += other.unseen_citations
        self.ungrounded_items += other.ungrounded_items


def render_context(chunks: list[SourceChunk]) -> str:
    """The retrieved chunks, numbered so the model can cite them.

    The number shown is the chunk's *document-wide* index, not its position in
    this retrieval — so a citation means the same thing in every section of the
    report and can be resolved without knowing which query produced it.
    """
    return "\n--\n".join(
        f"[chunk {chunk.chunk_id}]\n{chunk.content}" for chunk in chunks
    )


def resolve(
    section: str,
    items: list,
    retrieved: list[SourceChunk],
    document_chunk_ids: set[int] | None = None,
) -> GroundingResult:
    """Validate each item's citations and turn the survivors into records.

    `document_chunk_ids` is only used to tell the two kinds of bad citation
    apart in the counters; validity is decided by `retrieved` alone. Pass None
    and every invalid citation is counted as unknown.
    """
    by_id = {chunk.chunk_id: chunk for chunk in retrieved}
    result = GroundingResult()

    for index, item in enumerate(items):
        cited = list(getattr(item, "evidence", []) or [])
        valid = 0

        for chunk_id in cited:
            chunk = by_id.get(chunk_id)
            if chunk is None:
                if document_chunk_ids is not None and chunk_id in document_chunk_ids:
                    result.unseen_citations += 1
                else:
                    result.unknown_citations += 1
                continue

            valid += 1
            result.records.append(
                EvidenceRecord(
                    section=section,
                    item_index=index,
                    chunk_id=chunk_id,
                    excerpt=chunk.content[:EXCERPT_CHARS],
                    row_start=chunk.row_start,
                    row_end=chunk.row_end,
                    line_start=chunk.line_start,
                    line_end=chunk.line_end,
                )
            )

        if valid == 0:
            # Flagged by its absence from the evidence table, not by a column
            # and not by deletion. See the module docstring.
            result.ungrounded_items += 1

    if result.invalid_citations:
        logger.warning(
            "section cited chunks it was not given",
            extra={
                "section": section,
                "unknown_citations": result.unknown_citations,
                "unseen_citations": result.unseen_citations,
            },
        )
    return result


def _optional_int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
