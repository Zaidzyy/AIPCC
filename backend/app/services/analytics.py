"""Dashboard aggregation.

Every function here answers with a `GROUP BY` executed in Postgres. Nothing
loads ORM objects and counts them in Python: the dashboard is the one screen
that reads across *all* of a user's reports, so the per-row cost is the whole
cost. The only Python-side loop in this module walks the aggregated rows —
one per day or one per severity — never one per finding.

Two things are normalised here rather than at the edges:

1. **Severity is free text.** The prompts ask for Low/Medium/High/Critical and
   the field is nullable, so a model will still answer "Severe", "Med" or
   nothing at all. `severity_bucket` folds those into the canonical ladder
   inside SQL, so the chart never gets a slice called "Med." that is really the
   same thing as "Medium". The ladder itself lives in `services/severity.py`
   and the `CASE` below is generated from it, so the dashboard and the exporter
   cannot drift apart about what "Sev 1" means. `severityToken` in
   `frontend/src/lib/format.js` is the third runtime and stays a hand copy — a
   browser cannot import Python.
2. **Empty days.** A day with no reports must come back as a zero, not be
   absent. A line chart that silently closes the gap between two distant dates
   draws a trend that did not happen.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Select, case, func, select, union_all
from sqlalchemy.orm import Session

from app.api.deps import is_admin
from app.db import models
from app.schemas.dashboard import (
    AnomalyBucket,
    AttackTypeCount,
    KpiSummary,
    ReportBucket,
    SeveritySlice,
)
from app.services.severity import SEVERITY_ORDER, SEVERITY_PREFIXES, UNKNOWN

# Report states that mean "an analyst still has to look at this".
ATTENTION_STATES = ("failed", "partial")

__all__ = ["SEVERITY_ORDER", "ATTENTION_STATES", "severity_bucket"]


def severity_bucket(column):
    """Fold a free-text severity into the canonical ladder, inside SQL.

    The `WHEN` arms are generated from `services.severity.SEVERITY_PREFIXES`
    rather than restated here, so adding a spelling the models produce updates
    the dashboard and the exported document in one edit.
    """
    normalized = func.lower(func.trim(func.coalesce(column, "")))
    return case(
        *((normalized.like(f"{prefix}%"), name) for prefix, name in SEVERITY_PREFIXES),
        else_=UNKNOWN,
    )


def _scope(statement: Select, user: models.Users, column) -> Select:
    """Restrict a statement to the caller unless they are an admin.

    Same rule as `reports.py`: an analyst sees their own rows, an admin sees
    everything. The dashboard must not be the one place that leaks totals
    across tenants.
    """
    if is_admin(user):
        return statement
    return statement.where(column == user.user_id)


def _window_start(days: int) -> datetime:
    """Midnight UTC, `days` buckets ago — inclusive of today."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=days - 1)


def _day_index(start: datetime, days: int) -> list[date]:
    return [(start + timedelta(days=offset)).date() for offset in range(days)]


def _as_date(value: datetime | date) -> date:
    return value.date() if isinstance(value, datetime) else value


# --- KPI row --------------------------------------------------------------


def kpi_summary(db: Session, user: models.Users) -> KpiSummary:
    """The five headline numbers."""
    reports = _scope(
        select(func.count(models.Report.report_id)), user, models.Report.user_id
    )
    documents = _scope(
        select(func.count(models.Document.document_id)), user, models.Document.user_id
    )
    attention = _scope(
        select(func.count(models.Report.report_id)).where(
            func.lower(models.Report.status).in_(ATTENTION_STATES)
        ),
        user,
        models.Report.user_id,
    )
    open_alerts = _scope(
        select(func.count(models.SecurityAlert.alert_id)).where(
            models.SecurityAlert.status == "open"
        ),
        user,
        models.SecurityAlert.user_id,
    )

    return KpiSummary(
        total_reports=db.scalar(reports) or 0,
        documents_ingested=db.scalar(documents) or 0,
        attention_required=db.scalar(attention) or 0,
        open_alerts=db.scalar(open_alerts) or 0,
        critical_findings=_critical_findings(db, user),
    )


def _critical_findings(db: Session, user: models.Users) -> int:
    findings = _findings_subquery()
    statement = (
        select(func.count())
        .select_from(findings)
        .join(models.Report, models.Report.report_id == findings.c.report_id)
        .where(severity_bucket(findings.c.risk_level) == "critical")
    )
    return db.scalar(_scope(statement, user, models.Report.user_id)) or 0


# --- Series ---------------------------------------------------------------


def reports_over_time(db: Session, user: models.Users, days: int) -> list[ReportBucket]:
    """Report volume per day, split by outcome."""
    start = _window_start(days)
    bucket = func.date_trunc("day", models.Report.generated_at)

    statement = (
        select(
            bucket.label("day"),
            func.count(models.Report.report_id).label("total"),
            func.count(models.Report.report_id)
            .filter(func.lower(models.Report.status).in_(ATTENTION_STATES))
            .label("attention"),
        )
        .where(models.Report.generated_at >= start)
        .group_by(bucket)
        .order_by(bucket)
    )

    rows = db.execute(_scope(statement, user, models.Report.user_id)).all()
    counts = {_as_date(row.day): (row.total, row.attention) for row in rows}

    return [
        ReportBucket(
            day=day,
            total=counts.get(day, (0, 0))[0],
            attention=counts.get(day, (0, 0))[1],
        )
        for day in _day_index(start, days)
    ]


def severity_breakdown(db: Session, user: models.Users) -> list[SeveritySlice]:
    """Findings by severity, across attack risks *and* general risks.

    Both tables carry the same `risk_level` column and both describe findings
    an analyst has to triage, so counting only one of them would report roughly
    half the exposure.
    """
    findings = _findings_subquery()
    bucket = severity_bucket(findings.c.risk_level)

    statement = (
        select(bucket.label("severity"), func.count().label("count"))
        .select_from(findings)
        .join(models.Report, models.Report.report_id == findings.c.report_id)
        .group_by(bucket)
    )

    counts = {
        row.severity: row.count
        for row in db.execute(_scope(statement, user, models.Report.user_id))
    }
    # Every bucket is emitted even at zero: a legend that appears and vanishes
    # between refreshes is harder to read than a zero.
    return [
        SeveritySlice(severity=severity, count=counts.get(severity, 0))
        for severity in SEVERITY_ORDER
    ]


def top_attack_types(db: Session, user: models.Users, limit: int) -> list[AttackTypeCount]:
    """The most frequently observed attacks, with their MITRE mapping.

    Grouped on the case-folded name: two runs of the same model will write
    "SQL Injection" and "SQL injection", and splitting those into two bars
    halves a technique's apparent frequency.
    """
    name = func.lower(func.trim(models.AttackType.attack_name))

    statement = (
        select(
            func.max(models.AttackType.attack_name).label("attack_name"),
            func.max(models.AttackType.attack_mitre_technique_id).label("mitre_id"),
            func.max(models.AttackType.attack_mitre_technique_name).label("mitre_name"),
            func.count().label("count"),
        )
        .select_from(models.AttackType)
        .join(models.Report, models.Report.report_id == models.AttackType.report_id)
        .where(models.AttackType.attack_name.is_not(None))
        .where(name != "")
        .group_by(name)
        .order_by(func.count().desc(), name)
        .limit(limit)
    )

    return [
        AttackTypeCount(
            attack_name=row.attack_name,
            attack_mitre_technique_id=row.mitre_id,
            attack_mitre_technique_name=row.mitre_name,
            count=row.count,
        )
        for row in db.execute(_scope(statement, user, models.Report.user_id))
    ]


def anomalies_over_time(db: Session, user: models.Users, days: int) -> list[AnomalyBucket]:
    """Anomaly volume per day, bucketed by the report that found them.

    `findings` is how many distinct anomalies were recorded; `events` sums the
    occurrence count the model attached to each. One noisy anomaly seen 4 000
    times and 4 000 separate anomalies are very different days, and a chart
    that shows only one of those numbers cannot tell them apart.
    """
    start = _window_start(days)
    bucket = func.date_trunc("day", models.Report.generated_at)

    statement = (
        select(
            bucket.label("day"),
            func.count(models.Anomaly.id).label("findings"),
            func.coalesce(func.sum(models.Anomaly.counted), 0).label("events"),
        )
        .select_from(models.Anomaly)
        .join(models.Report, models.Report.report_id == models.Anomaly.report_id)
        .where(models.Report.generated_at >= start)
        .group_by(bucket)
        .order_by(bucket)
    )

    rows = db.execute(_scope(statement, user, models.Report.user_id)).all()
    counts = {_as_date(row.day): (row.findings, int(row.events)) for row in rows}

    return [
        AnomalyBucket(
            day=day,
            findings=counts.get(day, (0, 0))[0],
            events=counts.get(day, (0, 0))[1],
        )
        for day in _day_index(start, days)
    ]


# --- Shared ---------------------------------------------------------------


def _findings_subquery():
    """`attack_types` and `risk_assessments` as one severity-bearing relation.

    A `UNION ALL` rather than two queries summed in Python: the grouping and
    the counting both stay in the database.
    """
    attack_risks = select(
        models.AttackType.report_id.label("report_id"),
        models.AttackType.risk_level.label("risk_level"),
    )
    general_risks = select(
        models.RiskAssessment.report_id.label("report_id"),
        models.RiskAssessment.risk_level.label("risk_level"),
    )
    return union_all(attack_risks, general_risks).subquery("findings")


__all__ = [
    "SEVERITY_ORDER",
    "anomalies_over_time",
    "kpi_summary",
    "reports_over_time",
    "severity_breakdown",
    "severity_bucket",
    "top_attack_types",
]
