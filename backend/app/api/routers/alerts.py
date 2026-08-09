"""Security alerts.

Raised by the n8n FIM engine when a report's source document stops matching the
hash it was sealed with, and readable by an analyst in the app. Scoped like
everything else: an analyst sees alerts about their own work, an admin sees all
of them.

An alert is attributed to **the owner of the report it concerns**, not to the
caller that posted it. The FIM engine runs on a service account; if alerts
belonged to the poster, every alert in the system would belong to n8n and no
analyst would ever see one on their own dashboard.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import authorize_owner, get_current_user, is_admin
from app.db import models
from app.db.session import get_db
from app.schemas.alert import Alert, AlertCreate, AlertUpdate

router = APIRouter(tags=["alerts"])


@router.post("/api/security/alert", response_model=Alert, status_code=201)
def create_alert(
    request: AlertCreate,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Alert:
    """Record an alert. The path is the one the FIM workflow already calls."""
    owner_id = user.user_id
    report: models.Report | None = None

    if request.report_id is not None:
        report = db.get(models.Report, request.report_id)
        if report is None:
            raise HTTPException(404, f"report {request.report_id} not found")
        # The poster must be allowed to see the report it is alerting about,
        # or anyone with a login could probe for real report ids.
        authorize_owner(user, report.user_id)
        owner_id = report.user_id

    document_id = request.document_id
    if document_id is not None:
        document = db.get(models.Document, document_id)
        if document is None:
            raise HTTPException(404, f"document {document_id} not found")
        authorize_owner(user, document.user_id)
        if report is None:
            owner_id = document.user_id

    alert = models.SecurityAlert(
        severity=request.severity,
        source=request.source,
        message=request.message,
        report_id=request.report_id,
        document_id=document_id,
        user_id=owner_id,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return Alert.model_validate(alert)


@router.get("/alerts", response_model=list[Alert])
def list_alerts(
    status_filter: str | None = Query(default=None, alias="status", pattern="^(open|resolved)$"),
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Alert]:
    statement = select(models.SecurityAlert).order_by(
        models.SecurityAlert.created_at.desc()
    )
    if not is_admin(user):
        statement = statement.where(models.SecurityAlert.user_id == user.user_id)
    if status_filter:
        statement = statement.where(models.SecurityAlert.status == status_filter)
    return [Alert.model_validate(a) for a in db.scalars(statement).all()]


@router.patch("/alerts/{alert_id}", response_model=Alert)
def update_alert(
    alert_id: uuid.UUID,
    request: AlertUpdate,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Alert:
    """Resolve an alert, or reopen one."""
    alert = _get_authorized_alert(db, user, alert_id)
    alert.status = request.status
    # Cleared on reopen, so "resolved_at" can never describe an open alert.
    alert.resolved_at = datetime.now(timezone.utc) if request.status == "resolved" else None
    db.commit()
    db.refresh(alert)
    return Alert.model_validate(alert)


@router.delete("/alerts/{alert_id}", status_code=204)
def delete_alert(
    alert_id: uuid.UUID,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    db.delete(_get_authorized_alert(db, user, alert_id))
    db.commit()


def _get_authorized_alert(
    db: Session, user: models.Users, alert_id: uuid.UUID
) -> models.SecurityAlert:
    alert = db.get(models.SecurityAlert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"alert {alert_id} not found")
    authorize_owner(user, alert.user_id)
    return alert
