"""Share links: three owner routes and two public ones.

The public routes are the only endpoints in this application with no
`get_current_user` dependency, so the split is drawn hard. They take a token
from the path, hand it to `services.share.resolve_share`, and read exactly one
report — they never see a `Users`, never receive an `Authorization` header, and
answer with `SharedReport`, which is built by listing what may be exposed
rather than by stripping what may not. See `schemas/share.py`.

`require_human` is applied to the owner routes for the same reason it guards
`/api-keys`: a share link is a credential-shaped thing, and a leaked machine
key must not be able to mint one and walk a report out of the system.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import authorize_owner, require_human
from app.api.responses import as_download
from app.db import models
from app.db.session import get_db
from app.schemas.report import ThreatIntelItem
from app.schemas.share import ShareCreate, ShareCreated, SharedReport, ShareLink
from app.services import export, share
from app.services.report_storage import load_report_sections

router = APIRouter(tags=["shares"])


# --- Owner routes ---------------------------------------------------------


@router.post("/reports/{report_id}/shares", response_model=ShareCreated, status_code=201)
def create_share(
    report_id: uuid.UUID,
    request: ShareCreate,
    user: models.Users = Depends(require_human),
    db: Session = Depends(get_db),
) -> ShareCreated:
    """Mint a read-only link. The token is returned once and never again."""
    report = _get_authorized_report(db, user, report_id)
    try:
        record, token = share.create_share(db, report=report, creator=user, request=request)
    except share.ShareForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc

    return ShareCreated(
        **_link(record).model_dump(),
        token=token,
        url=share.share_url(token),
    )


@router.get("/reports/{report_id}/shares", response_model=list[ShareLink])
def list_shares(
    report_id: uuid.UUID,
    user: models.Users = Depends(require_human),
    db: Session = Depends(get_db),
) -> list[ShareLink]:
    report = _get_authorized_report(db, user, report_id)
    return [_link(record) for record in share.list_shares(db, report.report_id)]


@router.delete("/shares/{share_id}", response_model=ShareLink)
def revoke_share(
    share_id: uuid.UUID,
    user: models.Users = Depends(require_human),
    db: Session = Depends(get_db),
) -> ShareLink:
    """Retire a link.

    Answers with the updated row rather than 204: revocation is the action an
    owner takes when something has gone wrong, and they should see the state
    they just produced, not an empty body they have to refetch to trust.
    """
    record = db.get(models.ReportShare, share_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"share {share_id} not found")
    # Scoped through the report, not through `created_by`: an admin revoking a
    # link on somebody's report is exactly the case this needs to allow.
    authorize_owner(user, record.report.user_id)
    return _link(share.revoke_share(db, record))


# --- Public routes --------------------------------------------------------


@router.get("/share/{token}", response_model=SharedReport, tags=["public"])
def read_shared_report(token: str, db: Session = Depends(get_db)) -> SharedReport:
    """Read one report by link. No authentication, and no way to reach a second."""
    return _shared_report(db, _resolve(db, token))


@router.get("/share/{token}/export", response_class=Response, tags=["public"])
def export_shared_report(
    token: str,
    format: export.ExportFormat = "pdf",
    db: Session = Depends(get_db),
) -> Response:
    """The same report as a file.

    It goes through `source_from_shared`, so the exported copy carries exactly
    what the page carries — no sealed hash, no internal identifier — and says
    on its face that it is a shared copy.
    """
    shared = _shared_report(db, _resolve(db, token))
    return as_download(export.render(export.source_from_shared(shared), format))


# --- Internals ------------------------------------------------------------


def _resolve(db: Session, token: str) -> models.ReportShare:
    """Map the three share failures onto the three status codes.

    Kept in one place so the page and the export cannot answer differently for
    the same link. Why each code was chosen is argued in `services/share.py`.
    """
    try:
        return share.resolve_share(db, token)
    except share.ShareExpired as exc:
        raise HTTPException(status.HTTP_410_GONE, str(exc)) from exc
    except share.ShareForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except share.ShareNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


def _shared_report(db: Session, record: models.ReportShare) -> SharedReport:
    report = record.report
    return SharedReport(
        report_name=report.report_name,
        classification=report.classification,
        status=report.status,
        generated_at=report.generated_at,
        document_name=report.document.document_name if report.document else None,
        integrity_state=report.integrity_state,
        integrity_checked_at=report.integrity_checked_at,
        sections=load_report_sections(db, report.report_id),
        threat_intel=[
            ThreatIntelItem.model_validate(row, from_attributes=True)
            for row in sorted(report.threat_intel, key=lambda row: row.created_at)
        ],
        expires_at=record.expires_at,
    )


def _link(record: models.ReportShare) -> ShareLink:
    return ShareLink(
        **{
            key: getattr(record, key)
            for key in (
                "share_id",
                "report_id",
                "label",
                "created_at",
                "expires_at",
                "revoked",
                "revoked_at",
                "last_viewed_at",
                "view_count",
                "classification_at_share",
                "override_justification",
            )
        },
        active=share.is_active(record),
    )


def _get_authorized_report(
    db: Session, user: models.Users, report_id: uuid.UUID
) -> models.Report:
    report = db.get(models.Report, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"report {report_id} not found")
    authorize_owner(user, report.user_id)
    return report
