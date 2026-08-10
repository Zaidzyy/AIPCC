"""Dashboard aggregate response schemas.

These are read-only projections — no ORM model maps to them. Each one is the
shape a single chart consumes, so a chart component never has to reshape a
response before rendering it.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class KpiSummary(BaseModel):
    """The headline row.

    `open_alerts` became a real number in Phase 5, when the table behind it
    arrived. It counts unresolved `security_alerts` rows — including the ones
    the FIM engine raises when a report's source document stops matching the
    hash it was sealed with.
    """

    total_reports: int
    critical_findings: int
    documents_ingested: int
    attention_required: int
    open_alerts: int


class ReportBucket(BaseModel):
    """One day of report volume."""

    day: date
    total: int
    attention: int = Field(description="Of `total`, how many were partial or failed.")


class SeveritySlice(BaseModel):
    """Findings at one severity, across attack risks and general risks."""

    severity: str
    count: int


class AttackTypeCount(BaseModel):
    """One observed attack technique and how often it was seen."""

    attack_name: str
    attack_mitre_technique_id: str | None = None
    attack_mitre_technique_name: str | None = None
    count: int


class AnomalyBucket(BaseModel):
    """One day of anomaly volume."""

    day: date
    findings: int = Field(description="Distinct anomalies recorded that day.")
    events: int = Field(description="Sum of each anomaly's occurrence count.")


# --- Cost and latency (Phase 9) -------------------------------------------
#
# Every money and token field below is optional, and `None` means "not
# measured" — a provider that reported no usage, or a model with no configured
# price. It never means zero. The UI renders it as `—`, the same way a failed
# aggregate does, because on this dashboard "I could not measure this" and
# "this was free" must not look alike.


class CostBucket(BaseModel):
    """One day of LLM spend."""

    day: date
    cost_usd: float | None = None
    total_tokens: int | None = None
    calls: int


class SectionTokens(BaseModel):
    """Token spend for one report section, or for chat."""

    section: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    calls: int


class LatencyBucket(BaseModel):
    """Per-day generation latency.

    p95 as well as the median, because a mean hides the tail and the tail is
    what an analyst waiting on a report actually experiences.
    """

    day: date
    p50_ms: float | None = None
    p95_ms: float | None = None
    reports: int


class UsageSummary(BaseModel):
    """Headline numbers for the cost panel.

    `unpriced_calls` is deliberately surfaced rather than hidden: it is how
    many calls could not be costed at all, and without it a total that excludes
    them reads as complete when it is not.
    """

    total_cost_usd: float | None = None
    total_tokens: int | None = None
    calls: int
    retries: int
    retry_rate: float
    unpriced_calls: int
    cost_per_report_usd: float | None = None
