"""Phase 13 — streaming report generation over SSE.

What is worth testing about a progress stream is not that events arrive. It is
that they arrive **in an order a client can rely on**, that a section which
cannot be produced says so instead of leaving a row spinning forever, that the
retry — the one event this feature exists to show — is actually emitted, and
that hanging up costs the events and not the report.

The last one is the reason generation does not live in the response body, so
it gets a test that closes the stream halfway and then checks the database.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app.db import models
from app.services import report_stream
from app.services.report import SECTION_SPECS, generate_report

from .test_report import FakeProvider, _valid_for_prompt

SECTION_NAMES = [spec.name for spec in SECTION_SPECS]


# --- Harness --------------------------------------------------------------


class _NoCloseSession:
    """The test session, with `close()` disarmed.

    The generation task owns and closes its session, which is correct in
    production and would end the fixture's transaction here.
    """

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


@pytest.fixture
def stream_session(db, monkeypatch):
    monkeypatch.setattr(report_stream, "open_session", lambda: _NoCloseSession(db))
    return db


def use_provider(monkeypatch, invoke):
    """Install a fake provider for both the streaming and non-streaming paths."""

    monkeypatch.setattr(FakeProvider, "_invoke", invoke)
    provider = FakeProvider()
    monkeypatch.setattr("app.services.report.get_llm_provider", lambda: provider)
    return provider


async def always_valid(self, prompt):
    return _valid_for_prompt(prompt), self.usage


def parse_sse(body: str) -> list[tuple[str, dict]]:
    """Frames as (event name, payload), comments dropped."""
    frames = []
    for block in body.split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if name is not None:
            frames.append((name, data))
    return frames


def generate(api, headers, document_id, name="Streamed report"):
    response = api.post(
        "/generate_report/stream",
        json={
            "document_id": str(document_id),
            "report_name": name,
            "classification": "Internal",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return response, parse_sse(response.text)


# --- Ordering -------------------------------------------------------------


class TestEventOrder:
    def test_started_then_sections_then_exactly_one_terminal_frame(
        self, api, analyst_auth, document, stream_session, no_retrieval, monkeypatch
    ):
        use_provider(monkeypatch, always_valid)
        _, frames = generate(api, analyst_auth, document.document_id)
        names = [name for name, _ in frames]

        assert names[0] == "started"
        assert names[-1] == "stored"
        # Exactly one of each, or a client cannot know when it is finished.
        assert names.count("started") == 1
        assert names.count("stored") == 1
        assert set(names) == {"started", "section", "stored"}

    def test_every_section_is_announced_before_it_reports(
        self, api, analyst_auth, document, stream_session, no_retrieval, monkeypatch
    ):
        use_provider(monkeypatch, always_valid)
        _, frames = generate(api, analyst_auth, document.document_id)

        started_at, finished_at = {}, {}
        for index, (name, payload) in enumerate(frames):
            if name != "section":
                continue
            if payload["state"] == "started":
                started_at[payload["section"]] = index
            elif payload["state"] in {"completed", "failed"}:
                finished_at[payload["section"]] = index

        assert set(started_at) == set(SECTION_NAMES)
        assert set(finished_at) == set(SECTION_NAMES)
        for section in SECTION_NAMES:
            assert started_at[section] < finished_at[section]

    def test_the_opening_frame_names_every_section_up_front(
        self, api, analyst_auth, document, stream_session, no_retrieval, monkeypatch
    ):
        use_provider(monkeypatch, always_valid)
        _, frames = generate(api, analyst_auth, document.document_id)
        opening = frames[0][1]

        # So the UI can render five pending rows rather than growing a list as
        # results land, which hides how much is still outstanding.
        assert opening["sections"] == SECTION_NAMES
        assert uuid.UUID(opening["report_id"])

    def test_terminal_frame_matches_what_was_stored(
        self, api, analyst_auth, document, stream_session, no_retrieval, monkeypatch
    ):
        use_provider(monkeypatch, always_valid)
        _, frames = generate(api, analyst_auth, document.document_id)
        stored = frames[-1][1]

        report = stream_session.get(models.Report, uuid.UUID(stored["report_id"]))
        assert report.status == stored["status"] == "complete"
        assert report.attack_types, "sections were not persisted"
        assert stored["report_id"] == frames[0][1]["report_id"]


# --- The retry ------------------------------------------------------------


class TestRetryIsVisible:
    def test_a_section_that_recovers_reports_that_it_retried(
        self, api, analyst_auth, document, stream_session, no_retrieval, monkeypatch
    ):
        """The event the whole feature exists for.

        A section failing validation and coming back on the repair prompt is
        this system demonstrating its own robustness. Surfacing it is the
        point, not an implementation detail leaking out.
        """
        seen = {"attack_types": 0}

        async def flaky(self, prompt):
            if "attack_types" in prompt and not seen["attack_types"]:
                seen["attack_types"] += 1
                return "not json at all", self.usage
            return _valid_for_prompt(prompt), self.usage

        use_provider(monkeypatch, flaky)
        _, frames = generate(api, analyst_auth, document.document_id)

        attack = [p for n, p in frames if n == "section" and p["section"] == "attack_types"]
        assert [p["state"] for p in attack] == ["started", "retrying", "completed"]

        retry = attack[1]
        assert retry["attempt"] == 2
        # The reason carries the stage, so a reader can tell "the model wrote
        # prose" from "the model wrote the wrong fields".
        assert retry["reason"].startswith("parse:")

        # And it really did recover — the retry is not cosmetic.
        assert attack[2]["items"] >= 1
        assert all(p["state"] != "retrying" for n, p in frames
                   if n == "section" and p["section"] != "attack_types")

    def test_no_retry_event_when_nothing_retried(
        self, api, analyst_auth, document, stream_session, no_retrieval, monkeypatch
    ):
        use_provider(monkeypatch, always_valid)
        _, frames = generate(api, analyst_auth, document.document_id)
        assert not [p for n, p in frames if n == "section" and p["state"] == "retrying"]


# --- Failure --------------------------------------------------------------


class TestFailure:
    def test_a_permanently_failing_section_emits_failed_rather_than_hanging(
        self, api, analyst_auth, document, stream_session, no_retrieval, monkeypatch
    ):
        async def broken(self, prompt):
            if "attack_types" in prompt:
                return "garbage", self.usage
            return _valid_for_prompt(prompt), self.usage

        use_provider(monkeypatch, broken)
        _, frames = generate(api, analyst_auth, document.document_id)

        attack = [p for n, p in frames if n == "section" and p["section"] == "attack_types"]
        assert [p["state"] for p in attack] == ["started", "retrying", "failed"]

        # The typed SectionError, not a string: the UI shows the stage and the
        # detail separately, and the stage is what distinguishes a provider
        # outage from a model that will not produce valid JSON.
        error = attack[-1]["error"]
        assert error["section"] == "attack_types"
        assert error["stage"] in {"parse", "validation", "llm"}
        assert error["detail"]

        stored = frames[-1][1]
        assert stored["status"] == "partial"
        assert [e["section"] for e in stored["errors"]] == ["attack_types"]
        # One bad section does not sink the report — Phase 1's rule, still true
        # when the report is streamed.
        report = stream_session.get(models.Report, uuid.UUID(stored["report_id"]))
        assert report.timeline

    def test_a_reserved_report_never_stays_in_generating(
        self, api, analyst_auth, document, stream_session, no_retrieval, monkeypatch
    ):
        async def dead(self, prompt):
            return "garbage", self.usage

        use_provider(monkeypatch, dead)
        _, frames = generate(api, analyst_auth, document.document_id)
        stored = frames[-1][1]

        report = stream_session.get(models.Report, uuid.UUID(stored["report_id"]))
        # "generating" means "still running". A row left in it is a report that
        # is neither running nor finished, which no status endpoint can
        # describe honestly.
        assert report.status == "failed"


# --- Disconnect -----------------------------------------------------------


class TestDisconnect:
    def test_closing_the_stream_halfway_still_stores_the_report(
        self, db, analyst, document, no_retrieval, monkeypatch
    ):
        """The reason generation does not live in the response body.

        Driven directly rather than through the client, because the assertion
        is about what happens *after* the response generator is closed — which
        is precisely what a request/response test cannot observe.
        """
        monkeypatch.setattr(report_stream, "open_session", lambda: _NoCloseSession(db))
        use_provider(monkeypatch, always_valid)

        from app.schemas.report import GenerateReportRequest
        from app.services.report_storage import reserve_report

        payload = GenerateReportRequest(
            document_id=document.document_id,
            report_name="Abandoned",
            classification="Internal",
        )
        report = reserve_report(
            db,
            document_id=document.document_id,
            user_id=analyst.user_id,
            report_name=payload.report_name,
            classification=payload.classification,
        )
        assert report.status == "generating"
        report_id = report.report_id

        async def run():
            frames = report_stream.stream_generation(
                report=report, payload=payload, user_id=analyst.user_id, request=None
            )
            first = await frames.__anext__()
            assert b"event: started" in first
            # The client goes away.
            await frames.aclose()

            # The generation task is not the response body, so it is still
            # running. Wait for it the way the event loop would.
            for _ in range(200):
                if not report_stream._running:
                    break
                await asyncio.sleep(0.01)
            assert not report_stream._running, "generation task did not finish"

        asyncio.run(run())

        db.expire_all()
        stored = db.get(models.Report, report_id)
        assert stored.status == "complete"
        assert stored.attack_types, "the abandoned stream still wrote its sections"


# --- The non-streaming path is untouched ----------------------------------


class TestNonStreamingUnchanged:
    def test_generate_report_still_returns_a_report_detail(
        self, api, analyst_auth, document, no_retrieval, monkeypatch
    ):
        use_provider(monkeypatch, always_valid)
        response = api.post(
            "/generate_report",
            json={
                "document_id": str(document.document_id),
                "report_name": "Classic",
                "classification": "Internal",
            },
            headers=analyst_auth,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "complete"
        assert body["sections"]["attack_types"]
        # Not an SSE body — n8n and every other API client still get JSON.
        assert response.headers["content-type"].startswith("application/json")

    def test_generate_report_works_with_no_progress_hook_at_all(
        self, no_retrieval, monkeypatch
    ):
        # The hook is optional, and the default path must not construct one.
        use_provider(monkeypatch, always_valid)
        result = asyncio.run(generate_report("doc-1", FakeProvider()))
        assert result.errors == []


# --- Authorization and observability --------------------------------------


class TestStreamAuthorization:
    def test_anonymous_callers_are_rejected(self, api, document):
        response = api.post(
            "/generate_report/stream",
            json={
                "document_id": str(document.document_id),
                "report_name": "No",
                "classification": "Internal",
            },
        )
        assert response.status_code == 401

    def test_another_users_document_is_a_404(self, api, other_auth, document):
        response = api.post(
            "/generate_report/stream",
            json={
                "document_id": str(document.document_id),
                "report_name": "No",
                "classification": "Internal",
            },
        )
        assert response.status_code == 401  # unauthenticated first

        response = api.post(
            "/generate_report/stream",
            json={
                "document_id": str(document.document_id),
                "report_name": "No",
                "classification": "Internal",
            },
            headers=other_auth,
        )
        # 404, not 403, and refused before any part of the body is written —
        # a rejection delivered as an SSE frame inside a 200 is a status code
        # that lies.
        assert response.status_code == 404
        assert not response.text.startswith("event:")


class TestStreamObservability:
    def test_the_correlation_id_survives_the_streamed_request(
        self, api, analyst_auth, document, stream_session, no_retrieval, monkeypatch
    ):
        use_provider(monkeypatch, always_valid)
        response, frames = generate(api, analyst_auth, document.document_id)

        correlation = response.headers["x-request-id"]
        assert correlation

        report_id = uuid.UUID(frames[-1][1]["report_id"])
        rows = (
            stream_session.query(models.LlmUsage)
            .filter(models.LlmUsage.report_id == report_id)
            .all()
        )
        assert rows
        # Generation runs in a task created inside the request, so the context
        # var is copied into it. If that ever stopped being true these rows
        # would silently carry null and the whole trail would break.
        assert {row.correlation_id for row in rows} == {correlation}
