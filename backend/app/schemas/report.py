"""Canonical report schema.

This module is the single source of truth for report field names. The LLM
prompt skeletons, the validation of the model's output, and the DB write all
derive from these classes — a field name is never written as a string literal
in two places.

That is the fix for the prototype's #1 bug: `report.py` emitted `name`,
`mitre_attack_technique_id` and a *nested* `risk_assessment` object, while
`store_report_data()` read `attack_name`, `attack_mitre_technique_id` and
*flat* `risk_name`. Nothing reconciled them, so rows saved mostly-null.

Field names here match `app.db.models` column names exactly, so storage is a
straight `Model(**item.model_dump())`.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _blank_to_none(value: object) -> object:
    """LLMs emit "", "null", "N/A" and "unknown" where they mean null."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "" or stripped.lower() in {"null", "none", "n/a", "na", "unknown"}:
            return None
    return value


def _to_int(value: object) -> object:
    """Coerce "42" / 42.0 to 42; anything else non-numeric becomes None."""
    value = _blank_to_none(value)
    if value is None or isinstance(value, int):
        return value
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


Text = Annotated[str | None, BeforeValidator(_blank_to_none)]
Count = Annotated[int | None, BeforeValidator(_to_int)]


class SectionItem(BaseModel):
    """Base for report row types. Unknown keys from the LLM are dropped."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    def is_empty(self) -> bool:
        """True when no field carries a value.

        Every field is optional, so the all-null JSON skeleton the prompt shows
        the model validates perfectly. Smaller models echo that skeleton back
        verbatim instead of extracting anything, which would otherwise store a
        row of nulls and report the section as a success — the exact
        looks-fine-but-empty failure this rebuild exists to remove.
        """
        return all(value is None for value in self.model_dump().values())


# --- Row types (field names == DB column names) ---------------------------


class AttackTypeItem(SectionItem):
    attack_name: Text = None
    attack_mitre_technique_id: Text = None
    attack_mitre_technique_name: Text = None
    attack_description: Text = None
    # The prototype's prompt nested these under "risk_assessment" while the
    # table stores them flat. Flat wins: it matches the column layout, so no
    # translation step exists to drift.
    risk_name: Text = None
    risk_description: Text = None
    risk_level: Text = None
    impact: Text = None
    likelihood: Text = None
    mitigation: Text = None


class RiskAssessmentItem(SectionItem):
    risk_name: Text = None
    risk_description: Text = None
    risk_level: Text = None
    impact: Text = None
    likelihood: Text = None
    mitigation: Text = None


class VulnerabilityItem(SectionItem):
    vulnerability_name: Text = None
    vulnerability_description: Text = None
    cve_id: Text = None
    cve_description: Text = None
    cwe_id: Text = None
    cwe_description: Text = None


class AnomalyItem(SectionItem):
    anomaly_id: Text = None
    anomaly_name: Text = None
    user_id: Text = None
    user_name: Text = None
    source_ip: Text = None
    destination_ip: Text = None
    protocol: Text = None
    counted: Count = None
    first_occurrence: Text = None
    last_occurrence: Text = None


class TimelineItem(SectionItem):
    event_name: Text = None
    entity: Text = None
    time_stamp: Text = None
    duration: Text = None


# --- Section envelopes ----------------------------------------------------
# Each is what the LLM must return for one section: a single object with one
# key holding a list. The key is also the section name used everywhere else.


class AttackTypeSection(BaseModel):
    attack_types: list[AttackTypeItem] = Field(default_factory=list)


class RiskAssessmentSection(BaseModel):
    general_risk_assessment: list[RiskAssessmentItem] = Field(default_factory=list)


class VulnerabilitySection(BaseModel):
    vulnerabilities: list[VulnerabilityItem] = Field(default_factory=list)


class AnomalySection(BaseModel):
    anomalies: list[AnomalyItem] = Field(default_factory=list)


class TimelineSection(BaseModel):
    timeline: list[TimelineItem] = Field(default_factory=list)


# --- Whole report ---------------------------------------------------------


class ReportSections(BaseModel):
    """Every section of a generated report."""

    attack_types: list[AttackTypeItem] = Field(default_factory=list)
    general_risk_assessment: list[RiskAssessmentItem] = Field(default_factory=list)
    vulnerabilities: list[VulnerabilityItem] = Field(default_factory=list)
    anomalies: list[AnomalyItem] = Field(default_factory=list)
    timeline: list[TimelineItem] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            (
                self.attack_types,
                self.general_risk_assessment,
                self.vulnerabilities,
                self.anomalies,
                self.timeline,
            )
        )


class SectionError(BaseModel):
    """A section that could not be produced.

    Returned instead of the prototype's silent `{"status": "error"}`, which had
    no section key at all — so `report.update()` merged it, the section key
    vanished, and a failed section became indistinguishable from an empty one.
    """

    section: str
    stage: Literal["llm", "parse", "validation"]
    detail: str
    raw_output: str | None = None


class LlmCallRecord(BaseModel):
    """What one LLM call cost, on its way to `llm_usage`.

    A schema rather than an ORM object so `generate_report` stays free of the
    database — the generator has never taken a `Session` and does not start
    now. `store_report` turns these into rows.

    Every token and cost field is optional because "the provider did not
    report" is a real state, and it is not zero.
    """

    section: str
    provider: str
    model: str
    attempt: int = 1
    succeeded: bool = True
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: float
    cost_usd: float | None = None
    correlation_id: str | None = None


class ReportGenerationResult(BaseModel):
    """Outcome of generating every section."""

    sections: ReportSections
    errors: list[SectionError] = Field(default_factory=list)
    # Every LLM call the generation made, including the repair retries and the
    # calls belonging to sections that ultimately failed. A failed section is
    # not a free section — leaving its usage out would make the cost figure
    # understate exactly the reports that cost the most to produce.
    usage: list[LlmCallRecord] = Field(default_factory=list)
    # Wall-clock for the whole concurrent fan-out. Deliberately not the sum of
    # the section latencies: they run at the same time, so summing them would
    # report roughly five times the elapsed time.
    generation_ms: float | None = None

    @property
    def partial(self) -> bool:
        return bool(self.errors)


# --- Threat intelligence --------------------------------------------------

# Same three states the FIM workflow works in. UNKNOWN is the honest default:
# a report nobody has checked is not "fine", it is unchecked.
IntegrityState = Literal["UNKNOWN", "SEALED", "TAMPERED"]


class ThreatIntelCreate(BaseModel):
    """One enriched indicator, as the n8n orchestrator produces it.

    Field names match `models.ThreatIntel` columns exactly, so storage is
    `ThreatIntel(**item.model_dump())` — the same no-mapping rule the report
    sections follow.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    indicator: str = Field(min_length=1, max_length=500)
    indicator_type: str = Field(max_length=50)
    category: str | None = Field(default=None, max_length=120)
    source: str = Field(default="n8n", max_length=50)
    reputation_score: Count = None
    risk_level: Text = None
    country: str | None = Field(default=None, max_length=10)
    usage_type: str | None = Field(default=None, max_length=120)
    raw: dict | None = None


class ThreatIntelItem(ThreatIntelCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime | None = None


class IntegrityUpdate(BaseModel):
    """Body of PATCH /api/report/integrity/{report_id}, sent by the FIM engine."""

    integrity_state: IntegrityState
    # The hash the engine actually computed. Optional, but when it is supplied
    # a TAMPERED verdict carries the evidence for itself instead of asking an
    # analyst to take the workflow's word for it.
    observed_hash: str | None = Field(default=None, max_length=64)


# --- Classification -------------------------------------------------------

# The handling caveat a report carries: who this may be shown to. It is printed
# on every page of an export and it is what the share layer consults before it
# will hand a report to an unauthenticated reader.
#
# Three levels, deliberately — a ladder an analyst can hold in their head beats
# a taxonomy nobody applies consistently. The prototype's fourth level,
# "Restricted", sat between Confidential and nothing: it had no rule attached to
# it, so it meant whatever the reader assumed. A level with no consequence is
# decoration.
Classification = Literal["Public", "Internal", "Confidential"]
CLASSIFICATIONS: tuple[str, ...] = get_args(Classification)
DEFAULT_CLASSIFICATION = "Internal"

# Which levels a share link may expose without an explicit override. See
# `app.services.share` — this is the vocabulary, that module is the rule.
FREELY_SHAREABLE: frozenset[str] = frozenset({"Public", "Internal"})


class ClassificationUpdate(BaseModel):
    """Body of PATCH /reports/{report_id}/classification."""

    classification: Classification


# --- API request / response ----------------------------------------------


class GenerateReportRequest(BaseModel):
    document_id: uuid.UUID
    report_name: str = Field(min_length=1, max_length=255)
    classification: Classification = DEFAULT_CLASSIFICATION


class ReportStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_id: uuid.UUID
    status: str
    error_detail: str | None = None
    generated_at: datetime | None = None
    integrity_state: IntegrityState = "UNKNOWN"
    integrity_checked_at: datetime | None = None


class ReportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_id: uuid.UUID
    report_name: str
    document_id: uuid.UUID
    user_id: uuid.UUID
    # `str` on the way out, `Classification` on the way in — the same asymmetry
    # `UserPublic.email` uses, for the same reason. Rows written before this
    # vocabulary was closed carry values outside it; re-validating on output
    # would make one such row raise inside `GET /reports` and take the listing
    # down for every report the caller owns.
    classification: str
    status: str
    generated_at: datetime | None = None
    integrity_state: IntegrityState = "UNKNOWN"
    integrity_checked_at: datetime | None = None


class ReportDetail(ReportSummary):
    sections: ReportSections
    errors: list[SectionError] = Field(default_factory=list)
    # The source document's SHA-256 as it was when this report was generated.
    file_hash: str | None = None
    threat_intel: list[ThreatIntelItem] = Field(default_factory=list)


class StoreGeneratedReportRequest(BaseModel):
    """Body accepted by POST /store_generated_report (called by n8n).

    The n8n orchestrator produces the same sections the Python generator does,
    so both land in the same tables through the same schema.

    The report is attributed to the authenticated caller, so n8n must present a
    token like any other client — see n8n/IMPORT.md.
    """

    document_id: uuid.UUID
    report_name: str = Field(min_length=1, max_length=255)
    classification: Classification = DEFAULT_CLASSIFICATION
    sections: ReportSections
    # The orchestrator's AbuseIPDB reputation and IOC classification pass.
    # Optional: a report generated without enrichment is still a valid report.
    threat_intel: list[ThreatIntelCreate] = Field(default_factory=list)


# --- Prompt helpers -------------------------------------------------------


def json_skeleton(model: type[BaseModel]) -> str:
    """Render a model as the all-null JSON example shown to the LLM.

    Deriving the skeleton from the model is what keeps the prompt honest: add
    or rename a field and the prompt changes with it. The prototype hand-wrote
    these skeletons, which is how they drifted from the storage layer.
    """
    return json.dumps(_skeleton_value(model), indent=2)


def _skeleton_value(model: type[BaseModel]) -> dict:
    skeleton: dict = {}
    for name, field in model.model_fields.items():
        annotation = field.annotation
        origin_args = getattr(annotation, "__args__", ())
        item_model = next(
            (
                arg
                for arg in origin_args
                if isinstance(arg, type) and issubclass(arg, BaseModel)
            ),
            None,
        )
        skeleton[name] = [_skeleton_value(item_model)] if item_model else None
    return skeleton


def field_list(model: type[BaseModel]) -> str:
    """Comma-separated field names, for the "Include only:" prompt line."""
    return ", ".join(model.model_fields)
