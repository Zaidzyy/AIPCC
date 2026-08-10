"""Report persistence.

Every row is written as `Model(report_id=..., **item.model_dump())`. Because
the Pydantic field names in `app.schemas.report` are identical to the ORM
column names, there is no mapping step here — which is the point. The
prototype's `store_report_data()` restated every field name as a string
literal (`attack.get("attack_name")`), and those literals disagreed with what
the generator emitted, so rows saved mostly-null.

Also fixed here: the prototype generated a `report_id` and used it as the
foreign key for every child row, but never passed it into the `Report(...)`
insert. `report_id` is a NOT NULL primary key, so the commit raised, the bare
`except` swallowed it, and the endpoint reported "Failed to store report data"
every single time. Report storage never worked. Here the parent is flushed
first so its generated id is available to the children.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.schemas.report import (
    AnomalyItem,
    AttackTypeItem,
    LlmCallRecord,
    ReportDetail,
    ReportSections,
    RiskAssessmentItem,
    SectionError,
    ThreatIntelCreate,
    ThreatIntelItem,
    TimelineItem,
    VulnerabilityItem,
)
from app.services.integrity import hash_document

# section name -> (ORM model, relationship attribute on Report, schema item)
SECTION_TABLES: dict[str, tuple[type, str, type]] = {
    "attack_types": (models.AttackType, "attack_types", AttackTypeItem),
    "general_risk_assessment": (
        models.RiskAssessment,
        "risk_assessments",
        RiskAssessmentItem,
    ),
    "vulnerabilities": (models.Vulnerability, "vulnerabilities", VulnerabilityItem),
    "anomalies": (models.Anomaly, "anomalies", AnomalyItem),
    "timeline": (models.Timeline, "timeline", TimelineItem),
}


def resolve_status(sections: ReportSections, errors: list[SectionError]) -> str:
    if errors and sections.is_empty():
        return "failed"
    if errors:
        return "partial"
    return "complete"


def store_report(
    db: Session,
    *,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    report_name: str,
    classification: str,
    sections: ReportSections,
    errors: list[SectionError] | None = None,
    threat_intel: list[ThreatIntelCreate] | None = None,
    usage: list[LlmCallRecord] | None = None,
    generation_ms: float | None = None,
) -> models.Report:
    """Persist a generated report and all its sections. Commits.

    `user_id` is the caller — who asked for this report. The report is
    attributed to the **document's owner**, which is usually the same person
    and deliberately is not always. The n8n orchestrator runs on a service
    account: attributing to the caller would file every workflow-generated
    report under `n8n@aipcc.io`, where the analyst whose log it describes could
    never see it. Since `/reports` is scoped by `user_id`, that is the
    difference between a feature and a black hole.

    This is not a hardcoded user (hard rule #2). The caller is still resolved
    from their token and still authorized against the document before reaching
    here; ownership of the *output* simply follows ownership of the *input*.
    """
    errors = errors or []
    usage = usage or []

    document = db.get(models.Document, document_id)
    owner_id = document.user_id if document else user_id

    # Summed from the per-call rows, and **left null when nothing reported**
    # rather than defaulting to zero. A report stored by n8n has no Python
    # usage rows at all, and a provider that reports no tokens leaves nothing
    # to add up; in both cases "not measured" is the truth and `0` would be a
    # claim. Same rule as the dashboard's `—` and UNKNOWN integrity.
    token_values = [r.total_tokens for r in usage if r.total_tokens is not None]
    cost_values = [r.cost_usd for r in usage if r.cost_usd is not None]

    report = models.Report(
        report_name=report_name,
        document_id=document_id,
        user_id=owner_id,
        classification=classification,
        status=resolve_status(sections, errors),
        error_detail=_format_errors(errors),
        total_tokens=sum(token_values) if token_values else None,
        total_cost_usd=sum(cost_values) if cost_values else None,
        generation_ms=generation_ms,
        # Seal the source document as it is right now. A missing or unreadable
        # file leaves this null and the report UNKNOWN rather than failing the
        # write — an unsealable report is still a report.
        file_hash=hash_document(document.document_path) if document else None,
    )
    db.add(report)
    # Flush so the primary key exists before children reference it. This is the
    # step the prototype was missing.
    db.flush()

    for section_name, (model_cls, _, _) in SECTION_TABLES.items():
        for item in getattr(sections, section_name):
            db.add(model_cls(report_id=report.report_id, **item.model_dump()))

    for indicator in threat_intel or []:
        db.add(models.ThreatIntel(report_id=report.report_id, **indicator.model_dump()))

    for record in usage:
        # Attributed to the report's owner, not the caller — the same rule the
        # report itself follows, so an n8n-generated report's spend appears on
        # the analyst's dashboard rather than on the service account's.
        db.add(
            models.LlmUsage(
                report_id=report.report_id,
                user_id=owner_id,
                **record.model_dump(),
            )
        )

    db.commit()
    db.refresh(report)
    return report


def _format_errors(errors: list[SectionError]) -> str | None:
    if not errors:
        return None
    return "; ".join(f"{e.section} ({e.stage}): {e.detail}" for e in errors)


def load_report_sections(db: Session, report_id: uuid.UUID) -> ReportSections:
    """Read every section back out, keyed the same way it went in."""
    sections = ReportSections()
    for section_name, (model_cls, _, item_model) in SECTION_TABLES.items():
        rows = db.scalars(
            select(model_cls).where(model_cls.report_id == report_id)
        ).all()
        setattr(
            sections,
            section_name,
            [item_model.model_validate(row, from_attributes=True) for row in rows],
        )
    return sections


def load_report_detail(db: Session, report: models.Report) -> ReportDetail:
    indicators = db.scalars(
        select(models.ThreatIntel)
        .where(models.ThreatIntel.report_id == report.report_id)
        .order_by(models.ThreatIntel.created_at)
    ).all()

    return ReportDetail(
        report_id=report.report_id,
        report_name=report.report_name,
        document_id=report.document_id,
        user_id=report.user_id,
        classification=report.classification,
        status=report.status,
        generated_at=report.generated_at,
        integrity_state=report.integrity_state,
        integrity_checked_at=report.integrity_checked_at,
        file_hash=report.file_hash,
        sections=load_report_sections(db, report.report_id),
        threat_intel=[
            ThreatIntelItem.model_validate(row, from_attributes=True) for row in indicators
        ],
        errors=[],
    )
