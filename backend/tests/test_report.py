"""Phase 1 tests: schema alignment, parse/retry, storage round trip.

The alignment test is the important one. It is what makes the prototype's #1
bug — generator keys drifting from storage keys — impossible to reintroduce
without a red test.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect

from app.db import models
from app.schemas.report import (
    AnomalyItem,
    AttackTypeItem,
    ReportSections,
    json_skeleton,
)
from app.services.llm.base import LLMError, LLMProvider, extract_text
from app.services.report import (
    SECTION_SPECS,
    SECTION_SPECS_BY_NAME,
    extract_json,
    generate_report,
    generate_section,
)
from app.services.report_storage import (
    SECTION_TABLES,
    load_report_sections,
    resolve_status,
    store_report,
)


# --- Fakes ----------------------------------------------------------------


class FakeProvider(LLMProvider):
    """Returns canned responses in order; records every prompt it saw."""

    name = "fake"

    def __init__(self, *responses: str | Exception, delay: float = 0.0):
        self._responses = list(responses)
        self.prompts: list[str] = []
        self.delay = delay

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.delay:
            await asyncio.sleep(self.delay)
        if not self._responses:
            raise AssertionError("FakeProvider ran out of responses")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


VALID_ATTACK_JSON = """{
  "attack_types": [
    {
      "attack_name": "Spyware Implant",
      "attack_mitre_technique_id": "T1105",
      "attack_mitre_technique_name": "Ingress Tool Transfer",
      "attack_description": "Malicious binary written to /tmp.",
      "risk_name": "Device compromise",
      "risk_description": "Full device takeover.",
      "risk_level": "Critical",
      "impact": "Total loss of confidentiality.",
      "likelihood": "High",
      "mitigation": "Isolate and reimage the device."
    }
  ]
}"""


@pytest.fixture
def attack_spec():
    return SECTION_SPECS_BY_NAME["attack_types"]


@pytest.fixture
def no_retrieval(monkeypatch):
    """Bypass Chroma; these tests are about parsing, not retrieval."""
    monkeypatch.setattr(
        "app.services.report.retrieve_context",
        lambda spec, document_id: "some log context",
    )


# --- The alignment guarantee ---------------------------------------------


class TestSchemaAlignment:
    """Schema field names must equal ORM column names, for every section."""

    @pytest.mark.parametrize("section_name", list(SECTION_TABLES))
    def test_every_schema_field_is_a_column(self, section_name):
        model_cls, _, item_model = SECTION_TABLES[section_name]
        columns = {c.key for c in inspect(model_cls).columns}
        schema_fields = set(item_model.model_fields)
        missing = schema_fields - columns
        assert not missing, (
            f"{item_model.__name__} has fields with no column on "
            f"{model_cls.__name__}: {sorted(missing)}"
        )

    @pytest.mark.parametrize("section_name", list(SECTION_TABLES))
    def test_storage_uses_no_literal_field_names(self, section_name):
        """model_dump() must be directly constructible into the ORM model."""
        model_cls, _, item_model = SECTION_TABLES[section_name]
        row = model_cls(report_id=uuid.uuid4(), **item_model().model_dump())
        assert row is not None

    def test_sections_cover_every_spec(self):
        assert {s.name for s in SECTION_SPECS} == set(SECTION_TABLES)
        assert set(ReportSections.model_fields) == set(SECTION_TABLES)

    def test_prompt_skeleton_matches_schema(self, attack_spec):
        skeleton = json_skeleton(attack_spec.envelope)
        for name in AttackTypeItem.model_fields:
            assert f'"{name}"' in skeleton

    def test_nested_risk_assessment_is_not_reintroduced(self):
        """The prototype nested these; the table stores them flat."""
        assert "risk_assessment" not in AttackTypeItem.model_fields
        assert "risk_name" in AttackTypeItem.model_fields


# --- Parsing --------------------------------------------------------------


class TestExtractJson:
    def test_bare_object(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_markdown_fenced(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_fenced_without_language(self):
        assert extract_json('```\n{"a": 1}\n```') == {"a": 1}

    def test_surrounded_by_prose(self):
        raw = 'Sure! Here is the JSON:\n{"a": 1}\nHope that helps.'
        assert extract_json(raw) == {"a": 1}

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            extract_json("   ")

    def test_no_object_raises(self):
        with pytest.raises(ValueError, match="no JSON object"):
            extract_json("I cannot help with that.")

    def test_array_rejected(self):
        with pytest.raises(ValueError, match="expected a JSON object"):
            extract_json("[1, 2, 3]")


class TestExtractText:
    def test_plain_string(self):
        assert extract_text("hello") == "hello"

    def test_content_blocks(self):
        """The shape the prototype assumed unconditionally."""
        assert extract_text([{"type": "text", "text": "hi"}]) == "hi"

    def test_none_raises(self):
        with pytest.raises(LLMError):
            extract_text(None)


# --- Generation, retry, typed errors -------------------------------------


class TestSectionGeneration:
    def test_valid_response_parses(self, attack_spec, no_retrieval):
        provider = FakeProvider(VALID_ATTACK_JSON)
        outcome = asyncio.run(generate_section(attack_spec, "doc-1", provider))

        assert outcome.error is None
        assert len(outcome.items) == 1
        assert outcome.items[0].attack_name == "Spyware Implant"
        assert outcome.items[0].risk_level == "Critical"
        assert len(provider.prompts) == 1

    def test_malformed_then_valid_recovers_via_retry(self, attack_spec, no_retrieval):
        provider = FakeProvider("not json at all", VALID_ATTACK_JSON)
        outcome = asyncio.run(generate_section(attack_spec, "doc-1", provider))

        assert outcome.error is None
        assert len(outcome.items) == 1
        assert len(provider.prompts) == 2
        # The repair prompt must show the model what it got wrong.
        assert "could not be used" in provider.prompts[1]
        assert "not json at all" in provider.prompts[1]

    def test_two_failures_yield_typed_error(self, attack_spec, no_retrieval):
        provider = FakeProvider("garbage", "still garbage")
        outcome = asyncio.run(generate_section(attack_spec, "doc-1", provider))

        assert outcome.items == []
        assert outcome.error is not None
        assert outcome.error.section == "attack_types"
        assert outcome.error.stage == "parse"
        assert "failed after retry" in outcome.error.detail
        assert outcome.error.raw_output is not None

    def test_wrong_shape_is_a_validation_error(self, attack_spec, no_retrieval):
        provider = FakeProvider(
            '{"attack_types": "not a list"}', '{"attack_types": "still not a list"}'
        )
        outcome = asyncio.run(generate_section(attack_spec, "doc-1", provider))

        assert outcome.error is not None
        assert outcome.error.stage == "validation"

    def test_llm_failure_is_not_retried(self, attack_spec, no_retrieval):
        provider = FakeProvider(LLMError("api key rejected"))
        outcome = asyncio.run(generate_section(attack_spec, "doc-1", provider))

        assert outcome.error is not None
        assert outcome.error.stage == "llm"
        assert "api key rejected" in outcome.error.detail
        # Re-prompting cannot fix a bad credential.
        assert len(provider.prompts) == 1

    def test_missing_context_reports_clearly(self, attack_spec, monkeypatch):
        monkeypatch.setattr(
            "app.services.report.retrieve_context", lambda spec, document_id: ""
        )
        provider = FakeProvider()
        outcome = asyncio.run(generate_section(attack_spec, "doc-1", provider))

        assert outcome.error is not None
        assert "ingested" in outcome.error.detail

    def test_unknown_keys_are_dropped(self, attack_spec, no_retrieval):
        raw = """{"attack_types": [{"attack_name": "X", "hallucinated_field": "y"}]}"""
        provider = FakeProvider(raw)
        outcome = asyncio.run(generate_section(attack_spec, "doc-1", provider))

        assert outcome.error is None
        assert outcome.items[0].attack_name == "X"
        assert not hasattr(outcome.items[0], "hallucinated_field")

    def test_placeholder_strings_become_null(self, attack_spec, no_retrieval):
        raw = """{"attack_types": [{"attack_name": "X", "cve_id": "N/A",
                  "risk_level": "unknown", "attack_description": ""}]}"""
        provider = FakeProvider(raw)
        outcome = asyncio.run(generate_section(attack_spec, "doc-1", provider))

        item = outcome.items[0]
        assert item.risk_level is None
        assert item.attack_description is None

    def test_all_null_skeleton_is_rejected_and_retried(self, attack_spec, no_retrieval):
        """A model echoing the template back is not a successful section.

        Observed live with ollama/dolphin-llama3: valid JSON, valid schema,
        every field null. Without this it stored an empty row and reported
        "complete".
        """
        skeleton = json_skeleton(attack_spec.envelope)
        provider = FakeProvider(skeleton, VALID_ATTACK_JSON)
        outcome = asyncio.run(generate_section(attack_spec, "doc-1", provider))

        assert len(provider.prompts) == 2, "the empty skeleton should trigger a retry"
        assert "every item was empty" in provider.prompts[1]
        assert outcome.error is None
        assert outcome.items[0].attack_name == "Spyware Implant"

    def test_persistent_skeleton_becomes_a_typed_error(self, attack_spec, no_retrieval):
        skeleton = json_skeleton(attack_spec.envelope)
        provider = FakeProvider(skeleton, skeleton)
        outcome = asyncio.run(generate_section(attack_spec, "doc-1", provider))

        assert outcome.items == []
        assert outcome.error is not None
        assert outcome.error.stage == "validation"

    def test_partially_filled_items_are_kept(self, attack_spec, no_retrieval):
        """Only *entirely* empty items are dropped; one field is enough."""
        raw = '{"attack_types": [{"attack_name": "X"}, {"attack_name": null}]}'
        provider = FakeProvider(raw)
        outcome = asyncio.run(generate_section(attack_spec, "doc-1", provider))

        assert outcome.error is None
        assert len(outcome.items) == 1
        assert outcome.items[0].attack_name == "X"

    def test_genuinely_empty_section_is_allowed(self, attack_spec, no_retrieval):
        """"No findings" is a real answer and must not be retried."""
        provider = FakeProvider('{"attack_types": []}')
        outcome = asyncio.run(generate_section(attack_spec, "doc-1", provider))

        assert outcome.error is None
        assert outcome.items == []
        assert len(provider.prompts) == 1

    def test_counted_coerces_to_int(self):
        assert AnomalyItem(counted="42").counted == 42
        assert AnomalyItem(counted="many").counted is None
        assert AnomalyItem(counted=None).counted is None


class TestFullReport:
    def test_sections_run_concurrently(self, no_retrieval, monkeypatch):
        """Five 0.1s calls must take ~0.1s total, not ~0.5s."""

        async def fake_complete(self, prompt):
            await asyncio.sleep(0.1)
            return _valid_for_prompt(prompt)

        monkeypatch.setattr(FakeProvider, "complete", fake_complete)
        provider = FakeProvider()

        async def run():
            start = asyncio.get_event_loop().time()
            result = await generate_report("doc-1", provider)
            return result, asyncio.get_event_loop().time() - start

        result, elapsed = asyncio.run(run())

        assert result.errors == [], result.errors
        assert elapsed < 0.35, f"sections appear serial: {elapsed:.2f}s for 5x0.1s"

    def test_one_bad_section_does_not_sink_the_report(self, no_retrieval, monkeypatch):
        async def fake_complete(self, prompt):
            if "attack_types" in prompt:
                return "garbage"
            return _valid_for_prompt(prompt)

        monkeypatch.setattr(FakeProvider, "complete", fake_complete)
        result = asyncio.run(generate_report("doc-1", FakeProvider()))

        assert [e.section for e in result.errors] == ["attack_types"]
        assert result.partial
        assert result.sections.timeline, "other sections should still be populated"
        assert not result.sections.is_empty()


def _valid_for_prompt(prompt: str) -> str:
    """Produce a minimally valid response for whichever section is asked.

    The item must carry at least one non-null value: an entirely empty item is
    the all-null skeleton, which is deliberately rejected and retried.
    """
    import json as _json

    for spec in SECTION_SPECS:
        if f'"{spec.name}"' in prompt:
            first_field = next(iter(spec.item_model.model_fields))
            return _json.dumps({spec.name: [{first_field: "something"}]})
    raise AssertionError("prompt matched no known section")


# --- Storage --------------------------------------------------------------


@pytest.fixture
def owner_and_document(db):
    from app.core.security import hash_password

    user = models.Users(
        first_name="Test",
        last_name="Analyst",
        email=f"test-{uuid.uuid4().hex[:8]}@aipcc.io",
        role="analyst",
        status="Active",
        password_hash=hash_password("x"),
    )
    db.add(user)
    db.flush()

    now = datetime.now(timezone.utc)
    document = models.Document(
        document_name="sample.csv",
        document_size=1.0,
        document_extension=".csv",
        document_path="/tmp/sample.csv",
        created_at=now,
        modified_at=now,
        uploaded_at=now,
        user_id=user.user_id,
    )
    db.add(document)
    db.flush()
    return user, document


class TestStorage:
    def test_report_id_is_populated(self, db, owner_and_document):
        """The prototype never passed report_id into Report(...); commit failed."""
        user, document = owner_and_document
        report = store_report(
            db,
            document_id=document.document_id,
            user_id=user.user_id,
            report_name="R1",
            classification="Internal",
            sections=ReportSections(),
        )
        assert report.report_id is not None
        assert isinstance(report.report_id, uuid.UUID)

    def test_round_trip_populates_every_field(self, db, owner_and_document):
        user, document = owner_and_document
        sections = ReportSections(
            attack_types=[
                AttackTypeItem(
                    attack_name="Spyware Implant",
                    attack_mitre_technique_id="T1105",
                    attack_mitre_technique_name="Ingress Tool Transfer",
                    attack_description="Binary dropped in /tmp.",
                    risk_name="Device compromise",
                    risk_description="Full takeover.",
                    risk_level="Critical",
                    impact="Confidentiality loss.",
                    likelihood="High",
                    mitigation="Reimage.",
                )
            ],
            anomalies=[
                AnomalyItem(
                    anomaly_id="A-1",
                    anomaly_name="Unknown process",
                    user_id="1",
                    user_name="jdoe",
                    source_ip="192.168.1.49",
                    destination_ip="10.0.0.9",
                    protocol="HTTPS",
                    counted=7,
                    first_occurrence="2023-10-17T06:18",
                    last_occurrence="2023-10-18T09:02",
                )
            ],
        )

        report = store_report(
            db,
            document_id=document.document_id,
            user_id=user.user_id,
            report_name="Full",
            classification="Confidential",
            sections=sections,
        )

        loaded = load_report_sections(db, report.report_id)

        # Every field that went in comes back — no silent nulls.
        original = sections.attack_types[0]
        restored = loaded.attack_types[0]
        for name in AttackTypeItem.model_fields:
            assert getattr(restored, name) == getattr(original, name), (
                f"attack_types.{name} did not survive the round trip"
            )

        assert loaded.anomalies[0].counted == 7
        assert loaded.anomalies[0].source_ip == "192.168.1.49"

    def test_status_reflects_errors(self, db, owner_and_document):
        from app.schemas.report import SectionError

        user, document = owner_and_document
        errors = [SectionError(section="timeline", stage="parse", detail="bad json")]

        report = store_report(
            db,
            document_id=document.document_id,
            user_id=user.user_id,
            report_name="Partial",
            classification="Internal",
            sections=ReportSections(attack_types=[AttackTypeItem(attack_name="X")]),
            errors=errors,
        )
        assert report.status == "partial"
        assert "timeline" in report.error_detail

    def test_resolve_status(self):
        from app.schemas.report import SectionError

        err = [SectionError(section="x", stage="parse", detail="d")]
        assert resolve_status(ReportSections(), []) == "complete"
        assert resolve_status(ReportSections(), err) == "failed"
        assert (
            resolve_status(ReportSections(attack_types=[AttackTypeItem()]), err)
            == "partial"
        )
