"""The audit log, read-only.

There is no POST, no PATCH and no DELETE in this module, and that is the point:
the table is append-only and the API must not be the thing that says otherwise.
Rows are written by `services/audit.py` from the routes that perform the
actions, never by a client. A Postgres trigger backs the same guarantee at the
storage layer — see the `d4b7f2a19c30` migration and
`tests/test_audit.py::TestAppendOnly`.

`require_human_admin` rather than `require_admin`, matching `/users` and
`/api-keys`: this endpoint returns every actor, every address and every action
in the system, which is the most useful single read in the application for
somebody who should not have it. A machine key belongs in a credential store
and can be copied out of one; it does not get to enumerate the audit trail.

Reads are deliberately *not* themselves audited. Every open of the admin page
would append a row, the page would then show its own visit as the newest entry,
and a scheduled dashboard would fill the log with the fact that it looked at
the log. What is worth recording is what changed something.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_human_admin
from app.db import models
from app.db.session import get_db
from app.schemas.audit import AuditActor, AuditEntry, AuditFilters, AuditPage
from app.services import audit

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditPage)
def list_audit(
    action: str | None = Query(None, description="Exact action, e.g. auth.login.failure"),
    actor: str | None = Query(None, description="Actor uuid, or a substring of their label"),
    outcome: str | None = Query(None, description="success | failure | blocked"),
    since: datetime | None = Query(None, description="Only entries at or after this time"),
    until: datetime | None = Query(None, description="Only entries at or before this time"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: models.Users = Depends(require_human_admin),
    db: Session = Depends(get_db),
) -> AuditPage:
    """Newest first, filtered by actor and action."""
    conditions = []
    if action:
        conditions.append(models.AuditLog.action == action)
    if outcome:
        conditions.append(models.AuditLog.outcome == outcome)
    if since:
        conditions.append(models.AuditLog.at >= since)
    if until:
        conditions.append(models.AuditLog.at <= until)
    if actor:
        # An admin pasting a uuid means that principal exactly; an admin typing
        # "smith" means "whoever that is". Matching both against one parameter
        # is what makes the filter usable from the row you are already looking
        # at, where the id is the thing on screen.
        parsed = audit.actor_uuid(actor)
        if parsed is not None:
            conditions.append(models.AuditLog.actor_id == parsed)
        else:
            conditions.append(
                or_(
                    models.AuditLog.actor_label.ilike(f"%{actor}%"),
                    models.AuditLog.source_ip.ilike(f"%{actor}%"),
                )
            )

    total = db.scalar(
        select(func.count()).select_from(models.AuditLog).where(*conditions)
    ) or 0

    rows = db.scalars(
        select(models.AuditLog)
        .where(*conditions)
        # `audit_id` breaks ties. Two rows written in the same transaction can
        # share a timestamp, and an unstable sort would shuffle them between
        # pages — an entry could be shown twice or skipped entirely.
        .order_by(models.AuditLog.at.desc(), models.AuditLog.audit_id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return AuditPage(
        items=[AuditEntry.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/filters", response_model=AuditFilters)
def audit_filters(
    _: models.Users = Depends(require_human_admin),
    db: Session = Depends(get_db),
) -> AuditFilters:
    """The values worth filtering on.

    `actions` is the closed vocabulary the code can emit rather than the
    distinct values present, so a filter for something that has not happened
    yet returns an honest empty result instead of being missing from the menu.
    """
    actors = db.execute(
        select(models.AuditLog.actor_id, models.AuditLog.actor_label)
        .where(models.AuditLog.actor_label.is_not(None))
        .distinct()
        .order_by(models.AuditLog.actor_label)
        .limit(200)
    ).all()

    return AuditFilters(
        actions=list(audit.ACTIONS),
        actors=[AuditActor(actor_id=row[0], actor_label=row[1]) for row in actors],
        outcomes=[audit.SUCCESS, audit.FAILURE, audit.BLOCKED],
    )
