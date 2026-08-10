"""Running the generator against the golden log, deterministically.

**No database, no Chroma, no embedding model, no network.** The golden log is
chunked with the same `chunk_logs` the real ingest uses, and retrieval is a
fixed selection over those chunks rather than a similarity search. That is what
makes the CI gate hermetic: it needs Python and the repository and nothing
else, so it cannot fail because Hugging Face was slow or Postgres was not up.

The cost of that choice is stated rather than buried: **the gate does not
exercise retrieval quality.** A change that makes the retriever pick worse
chunks will not move these numbers. What it does exercise is everything
downstream of retrieval — prompting, parsing, validation, the repair retry,
citation resolution and identifier checking — which is where this project's
own logic lives. The `--live` run uses the real provider; retrieval-quality
evaluation is named as future work in `EVAL.md` rather than implied.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.services.grounding import SourceChunk
from app.services.rag.chunk import chunk_logs
from app.services.report import SectionSpec

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_LOG = GOLDEN_DIR / "golden_log.csv"
GOLDEN_LABELS = GOLDEN_DIR / "golden_labels.json"

# The synthetic document id the golden log is ingested under. Fixed, because it
# is part of what makes a recorded fixture replayable: it appears in nothing the
# model sees, but it keys the chunk cache.
GOLDEN_DOCUMENT_ID = "golden-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class GoldenLabel:
    id: str
    label: str
    match_any: list[str]
    mitre: str | None = None
    why: str = ""


@lru_cache(maxsize=1)
def golden_chunks() -> list[SourceChunk]:
    """The golden log, chunked exactly as ingest would chunk it.

    Read as text and passed through `chunk_logs` with `.csv` semantics, so the
    row provenance recorded here is the same provenance a real ingest records —
    the citations in an eval run point at real row numbers in a committed file
    that anyone can open and check.
    """
    import pandas as pd

    frame = pd.read_csv(GOLDEN_LOG)
    chunks = chunk_logs({"document_id": GOLDEN_DOCUMENT_ID}, frame, ".csv")
    return [
        SourceChunk(
            chunk_id=int(chunk["metadata"]["chunk_id"]),
            content=chunk["chunk"],
            row_start=chunk["metadata"].get("row_start"),
            row_end=chunk["metadata"].get("row_end"),
            line_start=chunk["metadata"].get("line_start"),
            line_end=chunk["metadata"].get("line_end"),
        )
        for chunk in chunks
    ]


def golden_retriever(spec: SectionSpec, document_id: str) -> list[SourceChunk]:
    """Every chunk of the golden log, for every section.

    Not a similarity search. The golden log is 35 rows and fits in a prompt
    whole, so selecting a subset would only introduce a source of variation
    that has nothing to do with what is being measured — and would make a
    recorded fixture depend on the embedding model's behaviour.
    """
    return list(golden_chunks())


@lru_cache(maxsize=1)
def golden_labels() -> dict:
    return json.loads(GOLDEN_LABELS.read_text(encoding="utf-8"))


def expected_attacks() -> list[GoldenLabel]:
    return [GoldenLabel(**_label(entry)) for entry in golden_labels()["expected_attacks"]]


def expected_anomalies() -> list[GoldenLabel]:
    return [GoldenLabel(**_label(entry)) for entry in golden_labels()["expected_anomalies"]]


def must_not_report() -> list[GoldenLabel]:
    return [GoldenLabel(**_label(entry)) for entry in golden_labels()["must_not_report"]]


def _label(entry: dict) -> dict:
    return {
        "id": entry["id"],
        "label": entry["label"],
        "match_any": entry["match_any"],
        "mitre": entry.get("mitre"),
        "why": entry.get("why", ""),
    }
