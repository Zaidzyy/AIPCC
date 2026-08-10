"""Report generation.

Five sections, generated concurrently, each validated against the canonical
schema in `app.schemas.report` before it is allowed anywhere near the database.

What changed from the prototype:

- **Concurrent, not serial.** The prototype ran five blocking `chain.invoke()`
  calls back to back. These run under `asyncio.gather`.
- **Validated, not `json.loads` + bare except.** Output is parsed, validated
  against the section's Pydantic model, and on failure retried once with a
  repair instruction that includes the actual error. A section that still
  fails returns a typed `SectionError` instead of a silent `{"status":
  "error"}` dict with no section key.
- **Prompts derive their JSON skeleton from the schema**, so a field rename
  updates the prompt automatically.

The five section prompts themselves are ported from the prototype — PORTING.md
judged them the genuinely good part.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from app.core.correlation import get_correlation_id
from app.core.tracing import get_tracer
from app.schemas.report import (
    AnomalyItem,
    AnomalySection,
    AttackTypeItem,
    AttackTypeSection,
    LlmCallRecord,
    ReportGenerationResult,
    ReportSections,
    RiskAssessmentItem,
    RiskAssessmentSection,
    SectionError,
    TimelineItem,
    TimelineSection,
    VulnerabilityItem,
    VulnerabilitySection,
    field_list,
    json_skeleton,
)
from app.services.grounding import GroundingResult, SourceChunk, render_context, resolve
from app.services.llm import LLMError, LLMProvider, get_llm_provider

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)

RETRIEVAL_K = 5


@dataclass(frozen=True)
class SectionSpec:
    """Everything needed to produce one section of a report."""

    name: str
    envelope: type[BaseModel]
    item_model: type[BaseModel]
    queries: list[str]
    guidance: str
    retrieval_k: int = RETRIEVAL_K


SECTION_SPECS: list[SectionSpec] = [
    SectionSpec(
        name="attack_types",
        envelope=AttackTypeSection,
        item_model=AttackTypeItem,
        queries=[
            "detected attacks",
            "Risk assessment for the detected attacks\nrisk, likelihood, impact, mitigation",
        ],
        guidance=(
            "- Give the 3 main detected attacks.\n"
            "- Do not invent attacks that did not happen.\n"
            "- For each attack also give its risk assessment, as flat fields on the "
            "same object (risk_name, risk_description, risk_level, impact, "
            "likelihood, mitigation). Do not nest them under another key.\n"
            "- risk_level and likelihood should be one of: Low, Medium, High, Critical."
        ),
    ),
    SectionSpec(
        name="general_risk_assessment",
        envelope=RiskAssessmentSection,
        item_model=RiskAssessmentItem,
        queries=[
            "General risk assessment for anything that causes risks\n"
            "risk, likelihood, impact, mitigation"
        ],
        guidance=(
            "- Assess anything in the data that causes risk, not only the attacks.\n"
            "- risk_level and likelihood should be one of: Low, Medium, High, Critical."
        ),
    ),
    SectionSpec(
        name="vulnerabilities",
        envelope=VulnerabilitySection,
        item_model=VulnerabilityItem,
        queries=["main detected vulnerabilities\nweaknesses"],
        guidance=(
            "- List the 3 main detected vulnerabilities.\n"
            "- cve_id must look like CVE-YYYY-NNNN, cwe_id like CWE-NNN.\n"
            "- If you cannot identify a real CVE or CWE, set those fields to null. "
            "Never invent an identifier."
        ),
    ),
    SectionSpec(
        name="anomalies",
        envelope=AnomalySection,
        item_model=AnomalyItem,
        queries=["main detected anomalies\nsuspicious user, abnormal"],
        guidance=(
            "- List the 5 main detected anomalies.\n"
            "- anomaly_name is a short label; use it, not a 'description' key.\n"
            "- counted must be a plain integer or null.\n"
            "- user_id and user_name are the principal named in the log."
        ),
    ),
    SectionSpec(
        name="timeline",
        envelope=TimelineSection,
        item_model=TimelineItem,
        queries=["important events"],
        guidance=(
            "- List the 5 main events that happened.\n"
            "- entity is whoever or whatever performed the action.\n"
            "- time_stamp is when it happened; duration is the estimated period."
        ),
    ),
]

SECTION_SPECS_BY_NAME = {spec.name: spec for spec in SECTION_SPECS}


# --- Prompting ------------------------------------------------------------


def build_prompt(spec: SectionSpec, context: str) -> str:
    return f"""You are a security analyst. Analyse the log data below and return your findings.

Each block of log data is preceded by a marker of the form [chunk N].

LOG DATA
--------
{context}

REQUIREMENTS
------------
{spec.guidance}
- Include only these fields: {field_list(spec.item_model)}
- Keep every key. If a value is unknown or not present in the data, set it to null.
- Base every finding on the log data above. Do not speculate.
- "evidence" must list the numbers of the [chunk N] blocks this finding came
  from — at least one. Cite only numbers that appear above; do not guess a
  number and do not cite a chunk you did not use. A finding you cannot point
  at a chunk for is a finding you should not report.

OUTPUT
------
Return a single JSON object with exactly this shape:
{json_skeleton(spec.envelope)}

The nulls above show the field names only — they are NOT the answer. Replace
them with values read from the log data. Use null only for a field the data
genuinely does not contain, and never return an object whose fields are all
null. If the data supports no findings at all, return an empty list rather than
one empty object.

Return raw JSON only. No markdown, no backticks, no commentary.
"""


def build_repair_prompt(spec: SectionSpec, bad_output: str, error: str) -> str:
    return f"""Your previous response could not be used.

ERROR
-----
{error}

YOUR PREVIOUS RESPONSE
----------------------
{bad_output[:4000]}

Rewrite it as a single valid JSON object exactly matching this structure:
{json_skeleton(spec.envelope)}

Every key must be present; unknown values are null. Field names must match
exactly. The structure above is a template showing the shape — do not return it
unchanged. Fill it in with what the log data actually shows. Return raw JSON
only — no markdown, no backticks, no commentary.
"""


# --- Parsing --------------------------------------------------------------

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def extract_json(raw: str) -> dict:
    """Pull a JSON object out of a model response.

    Models wrap output in markdown fences and add prose regardless of
    instructions, so strip fences first, then fall back to the outermost
    brace-delimited span.
    """
    if not raw or not raw.strip():
        raise ValueError("model returned an empty response")

    candidate = _FENCE.sub("", raw.strip())
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("no JSON object found in model response") from None
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed


# --- Retrieval ------------------------------------------------------------


def retrieve_context(spec: SectionSpec, document_id: str) -> list[SourceChunk]:
    """Fetch the chunks relevant to this section, scoped to one document.

    Returns the chunks themselves rather than one joined string. Phase 10 needs
    their ids to number the prompt and their row spans to show an analyst which
    log lines a finding came from; a concatenated blob has thrown both away by
    the time anyone wants them.

    De-duplicated by `chunk_id`, not by content. Two different chunks of a log
    file can be byte-identical, and collapsing them — which is what the
    previous content-based `seen` set did — silently removed a citable source
    and would have made a perfectly good citation unresolvable.
    """
    from app.services.rag.vectorstore import get_vectorstore

    with tracer.start_as_current_span("rag.retrieve") as span:
        span.set_attribute("rag.section", spec.name)
        span.set_attribute("rag.k", spec.retrieval_k)
        span.set_attribute("rag.queries", len(spec.queries))

        store = get_vectorstore()
        chunks: dict[int, SourceChunk] = {}
        for query in spec.queries:
            for doc in store.similarity_search(
                query, k=spec.retrieval_k, filter={"document_id": str(document_id)}
            ):
                chunk = SourceChunk.from_document(doc)
                if chunk.chunk_id >= 0:
                    chunks.setdefault(chunk.chunk_id, chunk)

        # The count and the size, never the content — a span goes to a
        # collector, and log data does not leave this system that way.
        span.set_attribute("rag.chunks", len(chunks))
        return [chunks[key] for key in sorted(chunks)]


# --- Section generation ---------------------------------------------------


@dataclass
class SectionOutcome:
    name: str
    items: list = field(default_factory=list)
    error: SectionError | None = None
    # Every call this section made, including the repair retry. Carried out of
    # here rather than written here: the generator has never touched the
    # database and does not start now.
    usage: list[LlmCallRecord] = field(default_factory=list)
    # Resolved citations and the counts of the ones that were fabricated.
    grounding: GroundingResult = field(default_factory=GroundingResult)


# What retrieval looks like from the generator's point of view: a section spec
# and a document id in, chunks out. Injectable so the evaluation harness can
# feed a deterministic set from a committed log file — no Chroma, no embedding
# model, no network — which is what makes the CI quality gate hermetic.
Retriever = Callable[[SectionSpec, str], list[SourceChunk]]


async def generate_section(
    spec: SectionSpec,
    document_id: str,
    provider: LLMProvider,
    retriever: Retriever | None = None,
) -> SectionOutcome:
    """Generate one section: retrieve, prompt, parse, validate, retry once."""
    usage: list[LlmCallRecord] = []
    retriever = retriever or retrieve_context

    with tracer.start_as_current_span("report.section") as span:
        span.set_attribute("section.name", spec.name)

        try:
            chunks = await asyncio.to_thread(retriever, spec, document_id)
        except Exception as exc:
            logger.exception("retrieval failed for section %s", spec.name)
            return SectionOutcome(
                spec.name,
                error=SectionError(
                    section=spec.name, stage="llm", detail=f"retrieval failed: {exc}"
                ),
            )

        if not chunks:
            return SectionOutcome(
                spec.name,
                error=SectionError(
                    section=spec.name,
                    stage="llm",
                    detail=(
                        f"no indexed content for document {document_id}. "
                        "Has it been ingested?"
                    ),
                ),
            )

        outcome = await _attempt_section(
            spec, provider, render_context(chunks), usage, span
        )

        # Citations are resolved after the section validates, against the
        # chunks this section was actually shown. A finding that cites nothing
        # valid stays in the report and is simply absent from the evidence
        # table — flagged, not dropped. See `services/grounding.py`.
        if outcome.items:
            outcome.grounding = resolve(spec.name, outcome.items, chunks)
            span.set_attribute("section.ungrounded", outcome.grounding.ungrounded_items)
            span.set_attribute(
                "section.invalid_citations", outcome.grounding.invalid_citations
            )
        return outcome


def _record(
    usage: list[LlmCallRecord], spec: SectionSpec, result, attempt: int, succeeded: bool
) -> None:
    usage.append(
        LlmCallRecord(
            section=spec.name,
            provider=result.provider,
            model=result.model,
            attempt=attempt,
            succeeded=succeeded,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
            latency_ms=result.latency_ms,
            cost_usd=result.cost_usd,
            correlation_id=get_correlation_id(),
        )
    )


async def _attempt_section(
    spec: SectionSpec,
    provider: LLMProvider,
    context: str,
    usage: list[LlmCallRecord],
    span,
) -> SectionOutcome:
    prompt = build_prompt(spec, context)
    raw = ""
    last_error = ""
    last_stage: str = "llm"

    for attempt in (1, 2):
        try:
            result = await provider.generate(prompt)
        except LLMError as exc:
            # A provider failure is not repairable by re-prompting. No usage
            # row either: the call never reached the model, so it has no
            # tokens, and inventing zeros would drag every average down with
            # calls that never happened.
            span.set_attribute("section.failed", True)
            return SectionOutcome(
                spec.name,
                error=SectionError(section=spec.name, stage="llm", detail=str(exc)),
                usage=usage,
            )

        raw = result.text
        # Recorded before the response is judged. A call that produced
        # unusable JSON still spent its tokens, and a cost figure that counted
        # only the calls that worked would understate exactly the reports that
        # went wrong most expensively.
        _record(usage, spec, result, attempt, succeeded=True)

        try:
            payload = extract_json(raw)
        except ValueError as exc:
            last_error, last_stage = str(exc), "parse"
        else:
            try:
                validated = spec.envelope.model_validate(payload)
            except ValidationError as exc:
                last_error, last_stage = _summarize(exc), "validation"
            else:
                raw_items = list(getattr(validated, spec.name))
                items = [item for item in raw_items if not item.is_empty()]
                if raw_items and not items:
                    # The model echoed the all-null skeleton instead of
                    # extracting anything. Valid JSON, valid schema, zero
                    # content — worth another attempt.
                    last_error, last_stage = (
                        "every item was empty; the all-null template was returned "
                        "instead of findings from the log data",
                        "validation",
                    )
                else:
                    span.set_attribute("section.items", len(items))
                    span.set_attribute("section.attempts", attempt)
                    return SectionOutcome(spec.name, items=items, usage=usage)

        if attempt == 1:
            logger.warning(
                "section failed, retrying with repair prompt",
                extra={"section": spec.name, "stage": last_stage, "reason": last_error},
            )
            span.set_attribute("section.retried", True)
            prompt = build_repair_prompt(spec, raw, last_error)

    span.set_attribute("section.failed", True)
    return SectionOutcome(
        spec.name,
        error=SectionError(
            section=spec.name,
            stage=last_stage,  # type: ignore[arg-type]
            detail=f"failed after retry: {last_error}",
            raw_output=raw[:2000] if raw else None,
        ),
        usage=usage,
    )


def _summarize(exc: ValidationError, limit: int = 5) -> str:
    parts = [
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
        for err in exc.errors()[:limit]
    ]
    remaining = len(exc.errors()) - len(parts)
    if remaining > 0:
        parts.append(f"(+{remaining} more)")
    return "; ".join(parts)


# --- Whole report ---------------------------------------------------------


async def generate_report(
    document_id: str,
    provider: LLMProvider | None = None,
    retriever: Retriever | None = None,
) -> ReportGenerationResult:
    """Generate every section concurrently.

    The span opened here is the parent of five `report.section` spans, each
    with its own `llm.complete` child. Those five overlap in wall-clock time,
    and that overlap is the visual proof that the concurrency this project has
    claimed since Phase 1 is real — asserted in
    `tests/test_observability.py::TestTracing`, so it is checked rather than
    admired.
    """
    provider = provider or get_llm_provider()

    with tracer.start_as_current_span("report.generate") as span:
        span.set_attribute("report.document_id", str(document_id))
        span.set_attribute("report.sections", len(SECTION_SPECS))
        started = time.perf_counter()

        outcomes = await asyncio.gather(
            *(
                generate_section(spec, document_id, provider, retriever)
                for spec in SECTION_SPECS
            ),
            return_exceptions=True,
        )

        sections = ReportSections()
        errors: list[SectionError] = []
        usage: list[LlmCallRecord] = []
        grounding = GroundingResult()

        for spec, outcome in zip(SECTION_SPECS, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                logger.exception("section raised", extra={"section": spec.name}, exc_info=outcome)
                errors.append(
                    SectionError(
                        section=spec.name,
                        stage="llm",
                        detail=f"unexpected error: {outcome}",
                    )
                )
                continue
            usage.extend(outcome.usage)
            grounding.merge(outcome.grounding)
            if outcome.error:
                errors.append(outcome.error)
            else:
                setattr(sections, spec.name, outcome.items)

        # Wall-clock, not the sum of the section latencies. They ran at the
        # same time; summing them would report about five times the truth.
        generation_ms = round((time.perf_counter() - started) * 1000, 2)

        costs = [record.cost_usd for record in usage if record.cost_usd is not None]
        span.set_attribute("report.generation_ms", generation_ms)
        span.set_attribute("report.llm_calls", len(usage))
        span.set_attribute("report.failed_sections", len(errors))
        if costs:
            span.set_attribute("report.cost_usd", sum(costs))

        span.set_attribute("report.evidence", len(grounding.records))
        span.set_attribute("report.invalid_citations", grounding.invalid_citations)

        logger.info(
            "report generated",
            extra={
                "document_id": str(document_id),
                "sections_ok": len(SECTION_SPECS) - len(errors),
                "sections_failed": len(errors),
                "llm_calls": len(usage),
                "generation_ms": generation_ms,
                "cost_usd": sum(costs) if costs else None,
                "evidence": len(grounding.records),
                "ungrounded_findings": grounding.ungrounded_items,
                "invalid_citations": grounding.invalid_citations,
            },
        )

        return ReportGenerationResult(
            sections=sections,
            errors=errors,
            usage=usage,
            generation_ms=generation_ms,
            evidence=grounding.records,
            ungrounded_findings=grounding.ungrounded_items,
            invalid_citations=grounding.invalid_citations,
        )
