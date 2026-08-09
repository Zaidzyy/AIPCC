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
