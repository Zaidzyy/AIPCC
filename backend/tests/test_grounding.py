"""Phase 10: evidence grounding.

The claim this phase makes is that every finding in a report can be traced back
to the specific log content that produced it, and that a citation the model
made up is detected rather than believed. Both halves are tested here, and the
second matters more: a grounding feature that trusts the model has added a
decoration, not a control.
"""

from __future__ import annotations

import asyncio
import uuid

import pandas as pd
import pytest
from sqlalchemy import select

from app.db import models
from app.schemas.report import (
    STORAGE_EXCLUDED,
    AttackTypeItem,
    AttackTypeSection,
    ReportSections,
    json_skeleton,
)
from app.services.grounding import SourceChunk, render_context, resolve
from app.services.rag.chunk import chunk_logs, line_offsets, serialize
from app.services.rag.vectorstore import chunk_key
from app.services.report import SECTION_SPECS_BY_NAME, generate_section
from app.services.report_storage import load_evidence, load_report_detail, store_report
from tests.conftest import STUB_CHUNKS
from tests.test_report import FakeProvider

# --- Chunk identity -------------------------------------------------------


class TestChunkIdentity:
    def test_the_key_is_document_scoped(self):
        """Two documents both have a chunk 0; only the pair identifies one."""
        assert chunk_key("doc-a", 0) != chunk_key("doc-b", 0)
        assert chunk_key("doc-a", 0) == "doc-a:0"

    def test_chunking_is_deterministic_across_runs(self):
        """The whole citation scheme rests on this.

        `(document_id, chunk_id)` is only a usable key if the same bytes
        produce the same chunk at the same index every time — otherwise a
        citation stored today points somewhere else after a re-ingest.
        """
        text = "\n".join(f"line {i} with some content to split on" for i in range(300))
        metadata = {"document_id": "doc-1"}

        first = chunk_logs(metadata, text, ".log")
        second = chunk_logs(metadata, text, ".log")

        assert [c["chunk"] for c in first] == [c["chunk"] for c in second]
        assert [c["metadata"]["chunk_id"] for c in first] == list(range(len(first)))


# --- Row and line provenance ----------------------------------------------


class TestProvenance:
    def _frame(self, rows: int = 200) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "timestamp": [f"2026-01-01T00:{i % 60:02d}:00Z" for i in range(rows)],
                "user": [f"user{i}" for i in range(rows)],
                "action": ["failed_login" for _ in range(rows)],
                "src_ip": [f"10.0.0.{i % 255}" for i in range(rows)],
            }
        )

    def test_tabular_chunks_carry_row_spans(self):
        chunks = chunk_logs({"document_id": "d"}, self._frame(), ".csv")

        assert len(chunks) > 1, "the fixture must be big enough to split"
        for chunk in chunks:
            metadata = chunk["metadata"]
            assert metadata["row_start"] is not None
            assert metadata["row_end"] >= metadata["row_start"]

        # Contiguous and complete: every row is covered by some chunk, which is
        # what makes "show me the rows behind this finding" answerable.
        assert chunks[0]["metadata"]["row_start"] == 0
        assert chunks[-1]["metadata"]["row_end"] == 199

    def test_row_spans_point_at_the_right_rows(self):
        """The assertion that catches an off-by-one in the header offset.

        A CSV's first line is the header, so data row N is on line N + 2. Get
        that wrong and every citation is one row out — which looks completely
        plausible and is completely useless.
        """
        frame = self._frame(rows=200)
        chunks = chunk_logs({"document_id": "d"}, frame, ".csv")

        for chunk in chunks[:3]:
            metadata = chunk["metadata"]
            first_user = frame.iloc[metadata["row_start"]]["user"]
            assert first_user in chunk["chunk"], (
                f"row {metadata['row_start']} claims to start this chunk but "
                f"{first_user} is not in it"
            )

    def test_text_chunks_carry_line_spans_and_no_rows(self):
        text = "\n".join(f"line {i} of a log file with enough text to split" for i in range(400))
        chunks = chunk_logs({"document_id": "d"}, text, ".log")

        assert chunks[0]["metadata"]["line_start"] == 1, "1-based, as an editor numbers them"
        for chunk in chunks:
            assert chunk["metadata"]["line_end"] >= chunk["metadata"]["line_start"]
            # A log file has no rows, and inventing them would be a lie a
            # citation could not be checked against.
            assert "row_start" not in chunk["metadata"]

    def test_row_provenance_is_omitted_rather_than_wrong(self):
        """A field containing a newline breaks the one-line-per-row assumption.

        `to_csv` quotes it, so the row spans several physical lines and every
        row number after it is off. The assumption is checked, and when it does
        not hold the spans are absent — not guessed. A citation that points at
        the wrong log rows is worse than one that admits it cannot point.
        """
        frame = pd.DataFrame(
            {
                "message": ["fine", "has\nan embedded newline", "fine again"] * 60,
                "user": [f"u{i}" for i in range(180)],
            }
        )
        chunks = chunk_logs({"document_id": "d"}, frame, ".csv")

        assert chunks, "chunking must still succeed"
        assert all("row_start" not in c["metadata"] for c in chunks)
        # Line spans are still exact — they describe the serialised text, which
        # is what was actually split.
        assert all(c["metadata"]["line_start"] >= 1 for c in chunks)

    def test_repeated_content_does_not_collapse_offsets(self):
        """Log files repeat. The offset search must not rewind to the first match."""
        text = "\n".join("IDENTICAL LINE OF LOG TEXT THAT REPEATS" for _ in range(400))
        chunks = chunk_logs({"document_id": "d"}, text, ".log")

        starts = [c["metadata"]["char_start"] for c in chunks]
        assert starts == sorted(starts)
        assert len(set(starts)) == len(starts), "offsets collapsed onto one another"

    def test_line_offsets_are_correct(self):
        assert line_offsets("a\nbb\nccc") == [0, 2, 5]

    def test_serialisation_is_platform_independent(self):
        """`to_csv` defaults to `os.linesep` — CRLF on Windows, LF on Linux.

        Every downstream number moves with it: chunk boundaries, chunk ids,
        character offsets and row spans. A citation recorded on a developer's
        Windows machine would point at different rows inside the Linux
        container, so Phase 10's "the same bytes produce the same chunk at the
        same index" was false across platforms while looking true on each one.

        Found by CI: the Phase 11 evaluation fixtures were recorded on Windows
        and every single section missed on the Linux runner, because the
        replay key is a hash of a prompt containing this text.
        """
        text = serialize(self._frame(rows=5), ".csv")
        assert "\r" not in text
        assert text.count("\n") == 6, "one header line plus five rows"

    def test_chunking_is_identical_whatever_the_platform_would_do(self):
        """The property the citation scheme actually depends on."""
        frame = self._frame(rows=120)
        first = chunk_logs({"document_id": "d"}, frame, ".csv")
        # Same frame, serialised again — must produce byte-identical chunks
        # with identical spans, or a re-ingest moves every existing citation.
        second = chunk_logs({"document_id": "d"}, frame, ".csv")

        assert [c["chunk"] for c in first] == [c["chunk"] for c in second]
        assert [c["metadata"]["row_start"] for c in first] == [
            c["metadata"]["row_start"] for c in second
        ]


# --- Citation validation --------------------------------------------------


class TestCitationValidation:
    def test_a_valid_citation_resolves_to_its_chunk(self):
        items = [AttackTypeItem(attack_name="Brute force", evidence=[1])]
        result = resolve("attack_types", items, STUB_CHUNKS)

        assert result.invalid_citations == 0
        assert result.ungrounded_items == 0
        assert len(result.records) == 1
        record = result.records[0]
        assert record.chunk_id == 1
        assert record.excerpt == "more log context"
        assert (record.row_start, record.row_end) == (5, 9)

    def test_a_fabricated_citation_is_rejected(self):
        """A chunk index the model was never given is a made-up source."""
        items = [AttackTypeItem(attack_name="Brute force", evidence=[99])]
        result = resolve("attack_types", items, STUB_CHUNKS)

        assert result.records == []
        assert result.unknown_citations == 1
        assert result.ungrounded_items == 1

    def test_a_real_but_unretrieved_chunk_is_still_a_fabrication(self):
        """It exists in the document, but this section was never shown it.

        Counted separately so the two failure modes stay distinguishable — one
        is inventing a number, the other is claiming to have read something it
        could not have.
        """
        items = [AttackTypeItem(attack_name="X", evidence=[7])]
        result = resolve("attack_types", items, STUB_CHUNKS, document_chunk_ids={0, 1, 7})

        assert result.records == []
        assert result.unseen_citations == 1
        assert result.unknown_citations == 0

    def test_a_finding_with_no_valid_evidence_is_flagged_not_dropped(self):
        """The project's stance: an absence must never look like a clean result.

        Dropping the finding would make the report look better than the model's
        actual output *and* make the grounding rate unmeasurable, because the
        ungrounded findings would no longer exist to count.
        """
        items = [
            AttackTypeItem(attack_name="Grounded", evidence=[0]),
            AttackTypeItem(attack_name="Invented", evidence=[42]),
            AttackTypeItem(attack_name="Uncited"),
        ]
        result = resolve("attack_types", items, STUB_CHUNKS)

        assert result.ungrounded_items == 2
        assert len(result.records) == 1
        # The findings themselves are untouched — resolve() reports, it does
        # not edit the section.
        assert len(items) == 3

    def test_mixed_valid_and_invalid_keeps_the_valid_half(self):
        items = [AttackTypeItem(attack_name="X", evidence=[0, 99, 1])]
        result = resolve("attack_types", items, STUB_CHUNKS)

        assert {r.chunk_id for r in result.records} == {0, 1}
        assert result.unknown_citations == 1
        assert result.ungrounded_items == 0, "one good citation is enough to be grounded"

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ([0, 3], [0, 3]),
            (["0", "3"], [0, 3]),
            ("0, 3", [0, 3]),
            ("chunk 3", [3]),
            (3, [3]),
            ([{"chunk_id": 2}], [2]),
            ([0, 0, 1], [0, 1]),
            (None, []),
            ("none of them", []),
            (True, []),
        ],
    )
    def test_whatever_shape_the_model_emits_is_coerced(self, raw, expected):
        """Models write citations six different ways; none is worth failing on.

        The check that matters happens next, against the document.
        """
        assert AttackTypeItem(evidence=raw).evidence == expected

    def test_evidence_alone_does_not_rescue_an_empty_finding(self):
        """Otherwise a stray `"evidence": [0]` reopens the all-null hole."""
        assert AttackTypeItem(evidence=[0]).is_empty()
        assert not AttackTypeItem(attack_name="X").is_empty()


# --- Prompt ---------------------------------------------------------------


class TestPrompt:
    def test_the_skeleton_teaches_the_evidence_shape(self):
        """A model told `"evidence": null` returns null, and nothing is grounded."""
        skeleton = json_skeleton(AttackTypeSection)
        assert '"evidence"' in skeleton
        assert '"evidence": null' not in skeleton

    def test_the_context_is_numbered_so_citations_are_possible(self):
        rendered = render_context(STUB_CHUNKS)
        assert "[chunk 0]" in rendered
        assert "[chunk 1]" in rendered
        assert "some log context" in rendered

    def test_the_chunk_number_is_document_wide_not_positional(self):
        """So a citation means the same thing in every section of the report."""
        rendered = render_context([SourceChunk(chunk_id=17, content="x")])
        assert "[chunk 17]" in rendered


# --- End to end through generation and storage ----------------------------


class TestGenerationGrounding:
    def test_a_generated_section_carries_resolved_evidence(self, no_retrieval):
        response = (
            '{"attack_types": [{"attack_name": "Brute force", "evidence": [1]}]}'
        )
        outcome = asyncio.run(
            generate_section(SECTION_SPECS_BY_NAME["attack_types"], "doc-1", FakeProvider(response))
        )

        assert outcome.error is None
        assert outcome.grounding.records[0].chunk_id == 1
        assert outcome.grounding.ungrounded_items == 0

    def test_a_generated_section_reports_fabricated_citations(self, no_retrieval):
        response = (
            '{"attack_types": [{"attack_name": "Brute force", "evidence": [404]}]}'
        )
        outcome = asyncio.run(
            generate_section(SECTION_SPECS_BY_NAME["attack_types"], "doc-1", FakeProvider(response))
        )

        # The finding survives; the citation does not.
        assert len(outcome.items) == 1
        assert outcome.grounding.invalid_citations == 1
        assert outcome.grounding.ungrounded_items == 1


class TestEvidenceStorage:
    def _store(self, db, analyst, document, evidence, **kwargs):
        from app.services.grounding import EvidenceRecord

        return store_report(
            db,
            document_id=document.document_id,
            user_id=analyst.user_id,
            report_name="Grounded",
            classification="Internal",
            sections=ReportSections(
                attack_types=[
                    AttackTypeItem(attack_name="Brute force"),
                    AttackTypeItem(attack_name="Exfiltration"),
                ]
            ),
            evidence=[EvidenceRecord(**record) for record in evidence],
            **kwargs,
        )

    def test_evidence_survives_the_round_trip_and_binds_to_its_finding(
        self, db, analyst, document
    ):
        report = self._store(
            db,
            analyst,
            document,
            [
                {
                    "section": "attack_types", "item_index": 0, "chunk_id": 3,
                    "excerpt": "10.0.0.1 failed_login", "row_start": 12, "row_end": 14,
                    "line_start": 14, "line_end": 16,
                },
                {
                    "section": "attack_types", "item_index": 1, "chunk_id": 8,
                    "excerpt": "10.0.0.9 large transfer",
                },
            ],
            ungrounded_findings=0,
            invalid_citations=0,
        )

        rows = load_evidence(db, report.report_id)
        assert len(rows) == 2

        detail = load_report_detail(db, report)
        findings = {item.attack_name: item.id for item in detail.sections.attack_types}
        by_item = {}
        for row in detail.evidence:
            by_item.setdefault(row.item_id, []).append(row)

        # The join the UI performs: each finding's evidence, found by item id.
        assert by_item[findings["Brute force"]][0].chunk_id == 3
        assert by_item[findings["Brute force"]][0].row_start == 12
        assert by_item[findings["Exfiltration"]][0].chunk_id == 8
        # Row provenance the ingest could not establish stays null, not zero.
        assert by_item[findings["Exfiltration"]][0].row_start is None

    def test_the_excerpt_is_a_copy_not_a_reference(self, db, analyst, document):
        """Chroma is a separate volume and can be rebuilt.

        A report that could no longer show what it was based on because the
        vector store was wiped would be a report whose evidence evaporated.
        """
        report = self._store(
            db, analyst, document,
            [{"section": "attack_types", "item_index": 0, "chunk_id": 3,
              "excerpt": "the actual log line"}],
        )
        assert load_evidence(db, report.report_id)[0].excerpt == "the actual log line"

    def test_grounding_counters_are_null_when_not_measured(self, db, analyst, document):
        """An n8n-stored report was not grounded by this process.

        Zero would read as "this report fabricated nothing", which is a claim
        nobody made. Same rule as the Phase 9 cost columns.
        """
        report = self._store(db, analyst, document, [])
        assert report.ungrounded_findings is None
        assert report.invalid_citations is None

    def test_evidence_dies_with_its_report(self, db, analyst, document):
        report = self._store(
            db, analyst, document,
            [{"section": "attack_types", "item_index": 0, "chunk_id": 1, "excerpt": "x"}],
        )
        report_id = report.report_id
        db.delete(report)
        db.commit()

        remaining = db.scalars(
            select(models.FindingEvidence).where(
                models.FindingEvidence.report_id == report_id
            )
        ).all()
        assert remaining == []

    def test_evidence_for_an_item_that_does_not_exist_is_skipped(
        self, db, analyst, document
    ):
        """Rather than written against a null item id — evidence attached to nothing."""
        report = self._store(
            db, analyst, document,
            [{"section": "attack_types", "item_index": 99, "chunk_id": 1, "excerpt": "x"}],
        )
        assert load_evidence(db, report.report_id) == []

    def test_section_rows_load_in_a_stable_order(self, db, analyst, document):
        """Evidence is bound by item id, but the *display* order must not drift.

        Without an ORDER BY, Postgres may return the findings in a different
        sequence on each load, so the exported PDF would stop matching what the
        screen showed.
        """
        report = self._store(db, analyst, document, [])
        first = [i.id for i in load_report_detail(db, report).sections.attack_types]
        second = [i.id for i in load_report_detail(db, report).sections.attack_types]
        assert first == second


class TestEndpoint:
    def test_report_detail_exposes_evidence(self, api, analyst_auth, analyst_report):
        body = api.get(f"/reports/{analyst_report}", headers=analyst_auth).json()
        assert "evidence" in body
        assert isinstance(body["evidence"], list)

    def test_findings_carry_the_id_the_client_joins_on(
        self, api, db, analyst, analyst_auth, document
    ):
        store_report(
            db,
            document_id=document.document_id,
            user_id=analyst.user_id,
            report_name="With ids",
            classification="Internal",
            sections=ReportSections(attack_types=[AttackTypeItem(attack_name="X")]),
        )
        listed = api.get("/reports", headers=analyst_auth).json()
        report_id = next(r["report_id"] for r in listed if r["report_name"] == "With ids")

        body = api.get(f"/reports/{report_id}", headers=analyst_auth).json()
        finding = body["sections"]["attack_types"][0]
        assert uuid.UUID(finding["id"])

    def test_the_model_is_never_shown_the_id_field(self):
        """It would invent one. Both exclusions are asserted, not assumed."""
        from app.services.report import build_prompt

        prompt = build_prompt(SECTION_SPECS_BY_NAME["attack_types"], "ctx")
        assert '"id"' not in prompt
        assert "evidence" in prompt
        assert "id" in STORAGE_EXCLUDED
