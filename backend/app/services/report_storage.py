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
    ReportDetail,
    ReportSections,
    RiskAssessmentItem,
    SectionError,
    TimelineItem,
    VulnerabilityItem,
)

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
) -> models.Report:
    """Persist a generated report and all its sections. Commits."""
    errors = errors or []

    report = models.Report(
        report_name=report_name,
        document_id=document_id,
        user_id=user_id,
        classification=classification,
        status=resolve_status(sections, errors),
        error_detail=_format_errors(errors),
    )
    db.add(report)
    # Flush so the primary key exists before children reference it. This is the
    # step the prototype was missing.
    db.flush()

    for section_name, (model_cls, _, _) in SECTION_TABLES.items():
        for item in getattr(sections, section_name):
            db.add(model_cls(report_id=report.report_id, **item.model_dump()))

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
    return ReportDetail(
        report_id=report.report_id,
        report_name=report.report_name,
        document_id=report.document_id,
        user_id=report.user_id,
        classification=report.classification,
        status=report.status,
        generated_at=report.generated_at,
        sections=load_report_sections(db, report.report_id),
        errors=[],
    )
