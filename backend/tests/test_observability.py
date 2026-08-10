"""Phase 9: correlation, structured logging, tracing, and cost accounting.

The load-bearing test in this file is `TestTracing::test_five_sections_overlap`.
This project has claimed concurrent section generation since Phase 1, and the
existing proof is a wall-clock assertion — real, but indirect. Here the span
tree is inspected: five `llm.complete` spans under one `report.generate`
parent, with intervals that genuinely overlap. That is the same picture a
Jaeger UI would draw, asserted on every run instead of eyeballed once.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

import pytest
from sqlalchemy import select

from app.core import correlation
from app.core.config import ModelPrice, settings
from app.core.logging import ConsoleFormatter, CorrelationFilter, JsonFormatter
from app.db import models
from app.schemas.report import LlmCallRecord, ReportSections
from app.services import analytics
from app.services.llm import cost_of, price_for
from app.services.llm.base import Usage
from app.services.report import (
    SECTION_SPECS_BY_NAME,
    generate_report,
    generate_section,
)
from app.services.report_storage import store_report
from tests.test_report import VALID_ATTACK_JSON, FakeProvider, _valid_for_prompt


@pytest.fixture
def attack_spec():
    return SECTION_SPECS_BY_NAME["attack_types"]


@pytest.fixture
def no_retrieval(monkeypatch):
    """Bypass Chroma; these tests are about measurement, not retrieval."""
    monkeypatch.setattr(
        "app.services.report.retrieve_context",
        lambda spec, document_id: "some log context",
    )


def _access_lines(caplog):
    """Every access record, in order.

    Callers take the *last* one. A test that authenticates by first calling
    another endpoint would otherwise assert against the setup request rather
    than the one it cares about — which is how this file's own API-key test
    first passed against the wrong line.
    """
    return [r for r in caplog.records if r.name == "aipcc.access"]


# --- Correlation ----------------------------------------------------------


class TestCorrelationId:
    def test_it_is_generated_and_returned(self, api):
        response = api.get("/health")
        assert response.headers["x-request-id"]
        assert len(response.headers["x-request-id"]) == 32

    def test_an_inbound_id_is_honoured(self, api):
        response = api.get("/health", headers={"X-Request-ID": "trace-abc-123"})
        assert response.headers["x-request-id"] == "trace-abc-123"

    def test_each_request_gets_its_own(self, api):
        first = api.get("/health").headers["x-request-id"]
        second = api.get("/health").headers["x-request-id"]
        assert first != second

    @pytest.mark.parametrize(
        "hostile, expected",
        [
            # A newline forges a second log line; a CR forges a second HTTP
            # header. Both are stripped rather than rejected, so a proxy that
            # appends whitespace still gets its id honoured.
            ("abc\r\nX-Evil: yes", "abcX-Evilyes"),
            ("id\nlevel=CRITICAL", "idlevelCRITICAL"),
            ("../../etc/passwd", "etcpasswd"),
            ("a" * 500, "a" * correlation.MAX_LENGTH),
        ],
    )
    def test_a_hostile_inbound_id_is_filtered(self, hostile, expected):
        assert correlation.sanitize(hostile) == expected

    def test_an_id_with_nothing_usable_is_replaced(self, api):
        """An empty result must mint a fresh id, not propagate an empty string."""
        assert correlation.sanitize("!!!@@@###") is None
        response = api.get("/health", headers={"X-Request-ID": "!!!@@@###"})
        assert response.headers["x-request-id"]
        assert response.headers["x-request-id"] != "!!!@@@###"

    def test_it_reaches_the_audit_log(self, api, db, analyst):
        """The whole point: an audit row is answerable against the request log."""
        from app.services import audit

        api.post(
            "/auth/login",
            data={"username": analyst.email, "password": "test-password-123"},
            headers={"X-Request-ID": "corr-login-test"},
        )
        entry = db.scalars(
            select(models.AuditLog)
            .where(models.AuditLog.action == audit.LOGIN_SUCCESS)
            .order_by(models.AuditLog.at.desc())
        ).first()
        assert entry.correlation_id == "corr-login-test"

    def test_it_is_cleared_between_requests(self, api):
        """A leaked ContextVar would tag a later request with an earlier id."""
        api.get("/health", headers={"X-Request-ID": "sticky"})
        assert correlation.get_correlation_id() is None


# --- Structured logging ---------------------------------------------------


def _record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello", args=(), exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestJsonLogging:
    def test_a_line_is_one_json_object(self):
        payload = json.loads(JsonFormatter().format(_record(correlation_id="abc", route="/x")))
        assert payload["message"] == "hello"
        assert payload["level"] == "INFO"
        assert payload["correlation_id"] == "abc"
        assert payload["route"] == "/x"

    def test_extras_survive_but_internals_do_not(self):
        payload = json.loads(JsonFormatter().format(_record(correlation_id=None, status=200)))
        assert payload["status"] == 200
        # LogRecord internals would drown the useful fields.
        for noise in ("msg", "args", "pathname", "levelno"):
            assert noise not in payload

    def test_an_unserialisable_extra_does_not_raise(self):
        """A log line is not the place to raise."""
        payload = json.loads(
            JsonFormatter().format(_record(correlation_id=None, report_id=uuid.uuid4()))
        )
        assert isinstance(payload["report_id"], str)

    def test_the_filter_attaches_the_current_id(self):
        correlation.set_correlation_id("from-context")
        try:
            record = _record()
            CorrelationFilter().filter(record)
            assert record.correlation_id == "from-context"
        finally:
            correlation.set_correlation_id(None)

    def test_console_format_is_readable(self):
        line = ConsoleFormatter().format(_record(correlation_id="abcdef1234567890", route="/x"))
        assert "hello" in line
        # Shortened, because a 32-character hex id in every line makes a
        # terminal unreadable and the first 8 are enough to correlate by eye.
        assert "[abcdef12]" in line
        assert "route=/x" in line

    def test_the_access_line_carries_route_actor_and_correlation(self, api, analyst_auth, caplog):
        with caplog.at_level(logging.INFO, logger="aipcc.access"):
            api.get("/auth/me", headers=analyst_auth)

        line = _access_lines(caplog)[-1]
        assert line.route == "/auth/me"
        assert line.status == 200
        assert line.method == "GET"
        assert line.duration_ms >= 0
        assert line.actor_id, "the access log must know who called"
        assert line.actor_type == "jwt"

    def test_the_access_line_uses_the_route_template_not_the_path(
        self, api, analyst_auth, analyst_report, caplog
    ):
        """`/reports/{report_id}` is one log key; the resolved path is thousands."""
        with caplog.at_level(logging.INFO, logger="aipcc.access"):
            api.get(f"/reports/{analyst_report}", headers=analyst_auth)

        line = _access_lines(caplog)[-1]
        assert line.route == "/reports/{report_id}"
        assert str(analyst_report) not in line.route

    def test_an_api_key_caller_is_distinguishable(self, api, admin_auth, caplog):
        created = api.post("/api-keys", json={"name": "n8n"}, headers=admin_auth)
        machine = {"Authorization": f"Bearer {created.json()['secret']}"}

        with caplog.at_level(logging.INFO, logger="aipcc.access"):
            api.get("/auth/me", headers=machine)

        # The *last* line: the POST that minted the key was itself a JWT call.
        line = _access_lines(caplog)[-1]
        assert line.actor_type == "api_key"


# --- Pricing --------------------------------------------------------------


class TestPricing:
    def test_the_maths_is_exact(self, monkeypatch):
        monkeypatch.setitem(
            settings.llm_prices,
            "test-model",
            ModelPrice(input_usd_per_1m=3.0, output_usd_per_1m=15.0),
        )
        # 1000 * 3/1e6 = 0.003; 500 * 15/1e6 = 0.0075; total 0.0105
        cost = cost_of("test-model", Usage(prompt_tokens=1000, completion_tokens=500))
        assert cost == pytest.approx(0.0105, abs=1e-12)

    def test_an_unknown_model_costs_none_not_zero(self):
        """The pair of states that must never look alike.

        Zero would quietly drag a dashboard total down and the figure would
        still look plausible — the worst kind of wrong number.
        """
        assert price_for("some-model-nobody-configured-xyz") is None
        assert cost_of(
            "some-model-nobody-configured-xyz", Usage(prompt_tokens=100, completion_tokens=100)
        ) is None

    def test_unreported_tokens_cost_none(self):
        assert cost_of("gemini-2.5-flash", Usage()) is None

    def test_a_local_model_is_genuinely_free_and_still_counts_tokens(self):
        usage = Usage(prompt_tokens=1000, completion_tokens=1000)
        assert cost_of("llama3.1", usage) == 0.0
        assert usage.total_tokens == 2000

    def test_a_prefixed_model_name_still_resolves(self):
        """Providers decorate model names; an undecorated price must still apply."""
        assert price_for("models/gemini-2.5-flash") is not None
        assert price_for("gemini-2.5-flash-preview-09-2025") is not None

    def test_the_longest_matching_price_wins(self, monkeypatch):
        """Otherwise a cheap variant is billed at its expensive parent's rate."""
        monkeypatch.setitem(
            settings.llm_prices, "aa-model", ModelPrice(input_usd_per_1m=10.0, output_usd_per_1m=10.0)
        )
        monkeypatch.setitem(
            settings.llm_prices, "aa-model-lite", ModelPrice(input_usd_per_1m=1.0, output_usd_per_1m=1.0)
        )
        assert price_for("aa-model-lite").input_usd_per_1m == 1.0

    def test_total_tokens_is_none_only_when_nothing_was_reported(self):
        assert Usage().total_tokens is None
        assert Usage(prompt_tokens=5).total_tokens == 5


# --- Usage capture --------------------------------------------------------


class TestUsageCapture:
    def test_a_fake_provider_with_known_counts_is_recorded_exactly(
        self, no_retrieval, monkeypatch
    ):
        async def invoke(self, prompt):
            return _valid_for_prompt(prompt), self.usage

        monkeypatch.setattr(FakeProvider, "_invoke", invoke)
        provider = FakeProvider(usage=Usage(prompt_tokens=111, completion_tokens=22))
        result = asyncio.run(generate_report("doc-1", provider))

        assert len(result.usage) == 5, "one record per section"
        assert {r.prompt_tokens for r in result.usage} == {111}
        assert {r.completion_tokens for r in result.usage} == {22}
        assert {r.total_tokens for r in result.usage} == {133}
        assert {r.section for r in result.usage} == {
            "attack_types", "general_risk_assessment", "vulnerabilities", "anomalies", "timeline"
        }

    def test_a_retried_section_records_both_calls(self, attack_spec, no_retrieval):
        """The retry rate is only measurable if the failed call left a row."""
        provider = FakeProvider("not json at all", VALID_ATTACK_JSON)
        outcome = asyncio.run(generate_section(attack_spec, "doc-1", provider))

        assert outcome.error is None
        assert [r.attempt for r in outcome.usage] == [1, 2]
        # The first call spent its tokens even though its output was unusable.
        assert all(r.total_tokens == 120 for r in outcome.usage)

    def test_a_failed_section_still_records_its_usage(self, attack_spec, no_retrieval):
        """Otherwise the cost figure understates exactly the worst reports."""
        provider = FakeProvider("garbage", "still garbage")
        outcome = asyncio.run(generate_section(attack_spec, "doc-1", provider))

        assert outcome.error is not None
        assert len(outcome.usage) == 2, "both doomed calls spent tokens"

    def test_a_provider_outage_records_nothing(self, attack_spec, no_retrieval):
        """A call that never reached the model has no tokens to record.

        Writing a zero-token row would drag every average down with calls that
        never happened.
        """
        from app.services.llm import LLMError

        provider = FakeProvider(LLMError("api key rejected"))
        outcome = asyncio.run(generate_section(attack_spec, "doc-1", provider))

        assert outcome.error is not None
        assert outcome.usage == []

    def test_generation_ms_is_wall_clock_not_the_sum(self, no_retrieval, monkeypatch):
        """Summing five concurrent sections would report ~5x the truth."""

        async def slow(self, prompt):
            await asyncio.sleep(0.05)
            return _valid_for_prompt(prompt), self.usage

        monkeypatch.setattr(FakeProvider, "_invoke", slow)
        result = asyncio.run(generate_report("doc-1", FakeProvider()))

        summed = sum(r.latency_ms for r in result.usage)
        assert result.generation_ms < summed, "wall clock must be under the sum"
        assert result.generation_ms >= 50


class TestUsagePersistence:
    def test_usage_rows_and_report_totals_round_trip(self, db, analyst, document):
        usage = [
            LlmCallRecord(
                section="attack_types", provider="fake", model="fake-model",
                prompt_tokens=100, completion_tokens=20, total_tokens=120,
                latency_ms=12.5, cost_usd=0.001,
            ),
            LlmCallRecord(
                section="timeline", provider="fake", model="fake-model",
                prompt_tokens=200, completion_tokens=30, total_tokens=230,
                latency_ms=9.0, cost_usd=0.002,
            ),
        ]
        report = store_report(
            db,
            document_id=document.document_id,
            user_id=analyst.user_id,
            report_name="Costed",
            classification="Internal",
            sections=ReportSections(),
            usage=usage,
            generation_ms=340.0,
        )

        assert report.total_tokens == 350
        assert report.total_cost_usd == pytest.approx(0.003)
        assert report.generation_ms == 340.0

        rows = db.scalars(
            select(models.LlmUsage).where(models.LlmUsage.report_id == report.report_id)
        ).all()
        assert len(rows) == 2
        # Attributed to the document's owner, like the report itself — so an
        # n8n-generated report's spend lands on the analyst's dashboard.
        assert {r.user_id for r in rows} == {analyst.user_id}

    def test_a_report_with_no_usage_has_null_totals_not_zero(self, db, analyst, document):
        report = store_report(
            db,
            document_id=document.document_id,
            user_id=analyst.user_id,
            report_name="From n8n",
            classification="Internal",
            sections=ReportSections(),
        )
        # A report stored by n8n was not measured by this process. Zero would
        # be a claim that it was free.
        assert report.total_tokens is None
        assert report.total_cost_usd is None


# --- Aggregates -----------------------------------------------------------


class TestCostAggregates:
    def _usage(self, db, user, *, section="attack_types", cost=0.001, tokens=100,
               attempt=1, report_id=None):
        row = models.LlmUsage(
            report_id=report_id, user_id=user.user_id, section=section,
            provider="fake", model="fake-model", attempt=attempt, succeeded=True,
            prompt_tokens=tokens, completion_tokens=0, total_tokens=tokens,
            latency_ms=10.0, cost_usd=cost,
        )
        db.add(row)
        db.flush()
        return row

    def test_summary_counts_retries_and_unpriced_calls(self, db, analyst):
        self._usage(db, analyst)
        self._usage(db, analyst, attempt=2)
        self._usage(db, analyst, cost=None)

        summary = analytics.usage_summary(db, analyst)
        assert summary.calls == 3
        assert summary.retries == 1
        assert summary.retry_rate == pytest.approx(1 / 3, abs=1e-4)
        # Surfaced rather than hidden: without it, a total that excludes these
        # calls reads as complete when it is not.
        assert summary.unpriced_calls == 1
        assert summary.total_cost_usd == pytest.approx(0.002)

    def test_tokens_by_section_is_ordered_most_expensive_first(self, db, analyst):
        self._usage(db, analyst, section="anomalies", tokens=10)
        self._usage(db, analyst, section="attack_types", tokens=900)
        self._usage(db, analyst, section="chat", tokens=50)

        rows = analytics.tokens_by_section(db, analyst)
        by_section = {r.section: r for r in rows}
        assert by_section["attack_types"].total_tokens == 900
        # Chat is in the accounting at all — omitting it would make the cost
        # figure quietly exclude a whole feature.
        assert "chat" in by_section
        ordered = [r.section for r in rows if r.section in {"attack_types", "anomalies", "chat"}]
        assert ordered.index("attack_types") < ordered.index("chat") < ordered.index("anomalies")

    def test_cost_over_time_emits_a_bucket_per_day(self, db, analyst):
        self._usage(db, analyst)
        buckets = analytics.cost_over_time(db, analyst, days=7)
        assert len(buckets) == 7
        # A day with no calls really did cost nothing — that is a zero, not an
        # unmeasured amount, and the chart must not break the line.
        assert all(b.cost_usd is not None for b in buckets)
        assert buckets[-1].calls >= 1

    def test_latency_percentiles_ignore_unmeasured_reports(self, db, analyst, document):
        for ms in (100.0, 200.0, 5000.0):
            store_report(
                db, document_id=document.document_id, user_id=analyst.user_id,
                report_name="R", classification="Internal",
                sections=ReportSections(), generation_ms=ms,
            )
        # No timing at all — must not be counted as a fast report.
        store_report(
            db, document_id=document.document_id, user_id=analyst.user_id,
            report_name="Untimed", classification="Internal", sections=ReportSections(),
        )

        today = analytics.generation_latency(db, analyst, days=1)[-1]
        assert today.reports == 3
        # p95 sits near the slow tail, which is the number that matters to
        # somebody waiting; a mean would have hidden it.
        assert today.p95_ms > today.p50_ms
        assert today.p95_ms > 1000

    def test_aggregates_are_owner_scoped(self, db, analyst, other_user):
        self._usage(db, analyst, cost=0.5)
        before = analytics.usage_summary(db, other_user)
        self._usage(db, analyst, cost=0.5)
        after = analytics.usage_summary(db, other_user)
        # Deltas, not absolutes: an admin's query sees pre-existing rows on a
        # developer's machine (Phase 4 decision).
        assert after.calls == before.calls


class TestCostEndpoints:
    @pytest.mark.parametrize(
        "path",
        ["/dashboard/usage-summary", "/dashboard/cost-over-time",
         "/dashboard/tokens-by-section", "/dashboard/generation-latency"],
    )
    def test_requires_authentication(self, api, path):
        assert api.get(path).status_code == 401

    @pytest.mark.parametrize(
        "path",
        ["/dashboard/usage-summary", "/dashboard/cost-over-time",
         "/dashboard/tokens-by-section", "/dashboard/generation-latency"],
    )
    def test_happy_path(self, api, analyst_auth, path):
        assert api.get(path, headers=analyst_auth).status_code == 200


# --- Tracing --------------------------------------------------------------


# The `spans` fixture lives in conftest.py. It has to be installed once for
# the whole session rather than per test — see the note there on how
# OpenTelemetry's proxy tracer caches its provider.


class TestTracing:
    def test_five_sections_overlap_under_one_parent(self, spans, no_retrieval, monkeypatch):
        """The picture this phase exists to produce.

        One `report.generate` span, five `llm.complete` descendants, and their
        intervals genuinely overlap. The wall-clock test in `test_report.py`
        shows the *effect* of concurrency; this shows its *shape* — the same
        thing a Jaeger screenshot would, checked automatically.
        """

        async def slow(self, prompt):
            await asyncio.sleep(0.05)
            return _valid_for_prompt(prompt), self.usage

        monkeypatch.setattr(FakeProvider, "_invoke", slow)
        result = asyncio.run(generate_report("doc-1", FakeProvider()))
        assert result.errors == []

        captured = spans.get_finished_spans()
        parents = [s for s in captured if s.name == "report.generate"]
        llm = [s for s in captured if s.name == "llm.complete"]
        sections = [s for s in captured if s.name == "report.section"]

        assert len(parents) == 1, "one trace per generation"
        assert len(llm) == 5
        assert len(sections) == 5

        # All five hang off the single report span's trace.
        assert {s.context.trace_id for s in llm} == {parents[0].context.trace_id}

        # Overlap: the last span to start did so before the first one ended.
        # Serial execution would make these disjoint.
        latest_start = max(s.start_time for s in llm)
        earliest_end = min(s.end_time for s in llm)
        assert latest_start < earliest_end, "LLM spans are serial, not concurrent"

    def test_llm_spans_carry_tokens_and_cost_but_never_content(self, spans, no_retrieval):
        provider = FakeProvider(
            '{"timeline": [{"event_name": "x"}]}',
            usage=Usage(prompt_tokens=77, completion_tokens=9),
        )
        asyncio.run(
            generate_section(SECTION_SPECS_BY_NAME["timeline"], "doc-1", provider)
        )

        span = next(s for s in spans.get_finished_spans() if s.name == "llm.complete")
        assert span.attributes["llm.prompt_tokens"] == 77
        assert span.attributes["llm.completion_tokens"] == 9
        assert span.attributes["llm.model"] == "fake-model"
        assert span.attributes["llm.latency_ms"] >= 0

        # A trace ships to a collector. Log data does not leave this system
        # that way, so no prompt and no completion may appear on a span.
        blob = json.dumps({k: str(v) for k, v in span.attributes.items()})
        assert "LOG DATA" not in blob
        assert "timeline" not in blob.lower() or "llm." in blob

    def test_a_retry_is_visible_on_the_section_span(self, spans, attack_spec, no_retrieval):
        provider = FakeProvider("not json", VALID_ATTACK_JSON)
        asyncio.run(generate_section(attack_spec, "doc-1", provider))

        section = next(s for s in spans.get_finished_spans() if s.name == "report.section")
        assert section.attributes["section.retried"] is True
        assert section.attributes["section.attempts"] == 2
