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
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from app.schemas.report import (
    AnomalyItem,
    AnomalySection,
    AttackTypeItem,
    AttackTypeSection,
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
from app.services.llm import LLMError, LLMProvider, get_llm_provider

logger = logging.getLogger(__name__)

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

LOG DATA
--------
{context}

REQUIREMENTS
------------
{spec.guidance}
- Include only these fields: {field_list(spec.item_model)}
- Keep every key. If a value is unknown or not present in the data, set it to null.
- Base every finding on the log data above. Do not speculate.

OUTPUT
------
Return a single JSON object exactly matching this structure:
{json_skeleton(spec.envelope)}

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
exactly. Return raw JSON only — no markdown, no backticks, no commentary.
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


def retrieve_context(spec: SectionSpec, document_id: str) -> str:
    """Fetch the chunks relevant to this section, scoped to one document."""
    from app.services.rag.vectorstore import get_vectorstore

    store = get_vectorstore()
    chunks: list[str] = []
    seen: set[str] = set()
    for query in spec.queries:
        for doc in store.similarity_search(
            query, k=spec.retrieval_k, filter={"document_id": str(document_id)}
        ):
            if doc.page_content not in seen:
                seen.add(doc.page_content)
                chunks.append(doc.page_content)
    return "\n--\n".join(chunks)


# --- Section generation ---------------------------------------------------


@dataclass
class SectionOutcome:
    name: str
    items: list = field(default_factory=list)
    error: SectionError | None = None


async def generate_section(
    spec: SectionSpec,
    document_id: str,
    provider: LLMProvider,
) -> SectionOutcome:
    """Generate one section: retrieve, prompt, parse, validate, retry once."""
    try:
        context = await asyncio.to_thread(retrieve_context, spec, document_id)
    except Exception as exc:
        logger.exception("retrieval failed for section %s", spec.name)
        return SectionOutcome(
            spec.name,
            error=SectionError(
                section=spec.name, stage="llm", detail=f"retrieval failed: {exc}"
            ),
        )

    if not context.strip():
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

    prompt = build_prompt(spec, context)
    raw = ""
    last_error = ""
    last_stage: str = "llm"

    for attempt in (1, 2):
        try:
            raw = await provider.complete(prompt)
        except LLMError as exc:
            # A provider failure is not repairable by re-prompting.
            return SectionOutcome(
                spec.name,
                error=SectionError(section=spec.name, stage="llm", detail=str(exc)),
            )

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
                items = getattr(validated, spec.name)
                return SectionOutcome(spec.name, items=list(items))

        if attempt == 1:
            logger.warning(
                "section %s failed (%s), retrying with repair prompt: %s",
                spec.name,
                last_stage,
                last_error,
            )
            prompt = build_repair_prompt(spec, raw, last_error)

    return SectionOutcome(
        spec.name,
        error=SectionError(
            section=spec.name,
            stage=last_stage,  # type: ignore[arg-type]
            detail=f"failed after retry: {last_error}",
            raw_output=raw[:2000] if raw else None,
        ),
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
) -> ReportGenerationResult:
    """Generate every section concurrently."""
    provider = provider or get_llm_provider()

    outcomes = await asyncio.gather(
        *(generate_section(spec, document_id, provider) for spec in SECTION_SPECS),
        return_exceptions=True,
    )

    sections = ReportSections()
    errors: list[SectionError] = []

    for spec, outcome in zip(SECTION_SPECS, outcomes, strict=True):
        if isinstance(outcome, BaseException):
            logger.exception("section %s raised", spec.name, exc_info=outcome)
            errors.append(
                SectionError(
                    section=spec.name,
                    stage="llm",
                    detail=f"unexpected error: {outcome}",
                )
            )
            continue
        if outcome.error:
            errors.append(outcome.error)
        else:
            setattr(sections, spec.name, outcome.items)

    return ReportGenerationResult(sections=sections, errors=errors)
