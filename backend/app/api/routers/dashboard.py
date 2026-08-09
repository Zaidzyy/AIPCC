"""Dashboard aggregates.

Thin by design: each route resolves the caller, validates its window, and hands
off to `services.analytics`, which does the aggregation in SQL. Scoping is the
same rule the rest of the API uses — an analyst sees their own reports, an
admin sees every report.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import models
from app.db.session import get_db
from app.schemas.dashboard import (
    AnomalyBucket,
    AttackTypeCount,
    KpiSummary,
    ReportBucket,
    SeveritySlice,
)
from app.services import analytics

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# A year of daily buckets is the widest chart worth drawing, and the ceiling
# keeps a caller from asking for a series with a million points in it.
Days = Query(default=30, ge=1, le=365, description="Size of the daily window.")


@router.get("/summary", response_model=KpiSummary)
def summary(
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KpiSummary:
    """Totals for the KPI row."""
    return analytics.kpi_summary(db, user)


@router.get("/reports-over-time", response_model=list[ReportBucket])
def reports_over_time(
    days: int = Days,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReportBucket]:
    """Reports per day. Days with no reports come back as zeros, not gaps."""
    return analytics.reports_over_time(db, user, days)


@router.get("/severity", response_model=list[SeveritySlice])
def severity(
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SeveritySlice]:
    """Findings by severity, low → critical, every bucket always present."""
    return analytics.severity_breakdown(db, user)


@router.get("/top-attack-types", response_model=list[AttackTypeCount])
def top_attack_types(
    limit: int = Query(default=8, ge=1, le=50),
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AttackTypeCount]:
    """Most frequently observed attack techniques, with their MITRE mapping."""
    return analytics.top_attack_types(db, user, limit)


@router.get("/anomalies-over-time", response_model=list[AnomalyBucket])
def anomalies_over_time(
    days: int = Days,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AnomalyBucket]:
    """Anomaly volume per day, bucketed by the report that recorded them."""
    return analytics.anomalies_over_time(db, user, days)
