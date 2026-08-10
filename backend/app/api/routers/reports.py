"""Report generation, storage and retrieval.

Every route resolves its caller through `get_current_user`. A non-admin sees
only their own reports; an admin sees everything.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import authorize_owner, get_current_user, is_admin
from app.api.responses import as_download
from app.db import models
from app.db.session import get_db
from app.schemas.report import (
    ClassificationUpdate,
    GenerateReportRequest,
    IntegrityUpdate,
    ReportDetail,
    ReportStatusResponse,
    ReportSummary,
    StoreGeneratedReportRequest,
)
from app.services import audit, export
from app.services.report import generate_report
from app.services.report_storage import load_report_detail, store_report

router = APIRouter(tags=["reports"])


@router.post("/generate_report", response_model=ReportDetail, status_code=201)
async def generate_report_endpoint(
    payload: GenerateReportRequest,
    request: Request,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportDetail:
    """Generate all five sections concurrently and persist them."""
    document = db.get(models.Document, payload.document_id)
    if document is None:
        raise HTTPException(404, f"document {payload.document_id} not found")
    authorize_owner(user, document.user_id)

    result = await generate_report(str(payload.document_id))

    report = store_report(
        db,
        document_id=payload.document_id,
        user_id=user.user_id,
        report_name=payload.report_name,
        classification=payload.classification,
        sections=result.sections,
        errors=result.errors,
        usage=result.usage,
        generation_ms=result.generation_ms,
        evidence=result.evidence,
        ungrounded_findings=result.ungrounded_findings,
        invalid_citations=result.invalid_citations,
    )

    # Recorded before the 502 below, so a generation that produced nothing is
    # still in the log. "Reports that were attempted and failed" is a question
    # about the system's health that a success-only log cannot answer.
    audit.record(
        db,
        action=audit.REPORT_CREATE,
        outcome=audit.SUCCESS if not result.sections.is_empty() else audit.FAILURE,
        request=request,
        actor=user,
        target_type="report",
        target_id=report.report_id,
        detail={
            "report_name": report.report_name,
            "document_id": str(payload.document_id),
            "classification": report.classification,
            "status": report.status,
            "origin": "app",
            "section_errors": len(result.errors),
            "cost_usd": report.total_cost_usd,
            "total_tokens": report.total_tokens,
            "ungrounded_findings": report.ungrounded_findings,
            # A non-zero count here means the model cited log content that was
            # never given to it. Worth an audit row of its own, because it is a
            # property of the *model*, not of the request.
            "invalid_citations": report.invalid_citations,
        },
    )

    if result.sections.is_empty():
        # Nothing usable came back. The attempt is persisted with status
        # "failed" so it is visible and debuggable rather than vanishing.
        raise HTTPException(
            status_code=502,
            detail={
                "message": "report generation produced no usable sections",
                "report_id": str(report.report_id),
                "errors": [e.model_dump() for e in result.errors],
            },
        )

    detail = load_report_detail(db, report)
    detail.errors = result.errors
    return detail


@router.post("/store_generated_report", response_model=ReportDetail, status_code=201)
def store_generated_report(
    payload: StoreGeneratedReportRequest,
    request: Request,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportDetail:
    """Persist a report generated elsewhere — used by the n8n orchestrator.

    Shares `store_report` with the Python path, so a report from n8n and one
    from the app land in the same tables in the same shape.
    """
    document = db.get(models.Document, payload.document_id)
    if document is None:
        raise HTTPException(404, f"document {payload.document_id} not found")
    authorize_owner(user, document.user_id)

    report = store_report(
        db,
        document_id=payload.document_id,
        user_id=user.user_id,
        report_name=payload.report_name,
        classification=payload.classification,
        sections=payload.sections,
        threat_intel=payload.threat_intel,
    )

    # `origin` distinguishes this from the app path. The two write identical
    # rows by design, so without it the log cannot answer "did a workflow do
    # this, or did a person?" — and `actor_type` alone will not, since a human
    # admin can call this endpoint too.
    audit.record(
        db,
        action=audit.REPORT_CREATE,
        request=request,
        actor=user,
        target_type="report",
        target_id=report.report_id,
        detail={
            "report_name": report.report_name,
            "document_id": str(payload.document_id),
            "classification": report.classification,
            "status": report.status,
            "origin": "n8n",
        },
    )
    return load_report_detail(db, report)


@router.patch("/api/report/integrity/{report_id}", response_model=ReportStatusResponse)
def update_report_integrity(
    report_id: uuid.UUID,
    payload: IntegrityUpdate,
    request: Request,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportStatusResponse:
    """Record the FIM engine's verdict on a report's source document.

    The path is the one the exported workflow already calls. `integrity_state`
    is a closed enum, so a workflow that sends a typo gets a 422 rather than
    writing a state the UI has no rendering for.

    `integrity_checked_at` is stamped here rather than taken from the request:
    "when was this last verified" is a claim about this system, and letting a
    caller set it would let a stale check present itself as a fresh one.
    """
    report = _get_authorized_report(db, user, report_id)
    previous = report.integrity_state
    report.integrity_state = payload.integrity_state
    report.integrity_checked_at = datetime.now(timezone.utc)
    if payload.observed_hash and payload.integrity_state == "TAMPERED":
        # Keep the evidence with the verdict. The sealed hash stays in
        # `file_hash`; this is what the file hashes to now.
        report.error_detail = (
            f"integrity mismatch: sealed {report.file_hash or 'unknown'}, "
            f"observed {payload.observed_hash}"
        )
    db.commit()
    db.refresh(report)

    # Only a *change* is recorded, which is what the phase brief asks for and
    # also the only thing that is readable. The FIM engine re-checks on a
    # schedule, so logging every verdict would bury nineteen real events under
    # a thousand rows a day saying the file is still fine.
    if previous != report.integrity_state:
        audit.record(
            db,
            action=audit.INTEGRITY_CHANGE,
            outcome=(
                audit.FAILURE if report.integrity_state == "TAMPERED" else audit.SUCCESS
            ),
            request=request,
            actor=user,
            target_type="report",
            target_id=report.report_id,
            detail={"from": previous, "to": report.integrity_state},
        )
    return ReportStatusResponse.model_validate(report)


@router.get("/reports", response_model=list[ReportSummary])
def list_reports(
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReportSummary]:
    statement = select(models.Report).order_by(models.Report.generated_at.desc())
    if not is_admin(user):
        statement = statement.where(models.Report.user_id == user.user_id)
    return [ReportSummary.model_validate(r) for r in db.scalars(statement).all()]


@router.get("/get_all_reports", response_model=list[ReportSummary])
def get_all_reports(
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReportSummary]:
    """Alias consumed by the n8n FIM workflow, which polls this path."""
    return list_reports(user=user, db=db)


@router.get("/reports/{report_id}/status", response_model=ReportStatusResponse)
def get_report_status(
    report_id: uuid.UUID,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportStatusResponse:
    report = _get_authorized_report(db, user, report_id)
    return ReportStatusResponse.model_validate(report)


@router.get(
    "/reports/{report_id}/export",
    response_class=Response,
    responses={200: {"content": {media: {} for media in export.MEDIA_TYPES.values()}}},
)
def export_report(
    report_id: uuid.UUID,
    request: Request,
    format: export.ExportFormat = "pdf",
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Render this report as a document an analyst can hand to someone.

    Ownership is the same rule every other report route uses. Classification is
    not a restriction here — the owner is allowed their own report in any
    format — but it is stamped on every page of what comes back, because that
    caveat has to travel with the file once it leaves this system.
    """
    report = _get_authorized_report(db, user, report_id)
    detail = load_report_detail(db, report)
    source = export.source_from_detail(
        detail, document_name=report.document.document_name if report.document else None
    )

    # An export is the moment a report leaves this system, so its
    # classification is recorded alongside it: "who took a Confidential report
    # out, and when" is the question this row exists to answer.
    audit.record(
        db,
        action=audit.REPORT_EXPORT,
        request=request,
        actor=user,
        target_type="report",
        target_id=report.report_id,
        detail={"format": format, "classification": report.classification},
    )
    return as_download(export.render(source, format))


@router.patch("/reports/{report_id}/classification", response_model=ReportSummary)
def set_classification(
    report_id: uuid.UUID,
    payload: ClassificationUpdate,
    request: Request,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportSummary:
    """Reclassify a report.

    Existing share links are deliberately *not* revoked here. `resolve_share`
    re-reads the classification on every open, so raising a report to
    Confidential stops its links working immediately and lowering it again
    restores them — which is the behaviour somebody who reclassified by mistake
    expects. Revoking on write would silently destroy links instead.
    """
    report = _get_authorized_report(db, user, report_id)
    previous = report.classification
    report.classification = payload.classification
    db.commit()
    db.refresh(report)

    audit.record(
        db,
        action=audit.REPORT_CLASSIFY,
        request=request,
        actor=user,
        target_type="report",
        target_id=report.report_id,
        detail={"from": previous, "to": report.classification},
    )
    return ReportSummary.model_validate(report)


@router.get("/reports/{report_id}", response_model=ReportDetail)
def get_report(
    report_id: uuid.UUID,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportDetail:
    report = _get_authorized_report(db, user, report_id)
    return load_report_detail(db, report)


@router.get("/get_report_by_id/{report_id}", response_model=ReportDetail)
def get_report_by_id(
    report_id: uuid.UUID,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportDetail:
    """Alias consumed by the n8n FIM workflow."""
    return get_report(report_id, user, db)


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(
    report_id: uuid.UUID,
    request: Request,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    report = _get_authorized_report(db, user, report_id)
    # Captured before the delete cascades it away.
    deleted = {
        "report_name": report.report_name,
        "classification": report.classification,
        "owner_id": str(report.user_id),
    }
    db.delete(report)
    db.commit()

    audit.record(
        db,
        action=audit.REPORT_DELETE,
        request=request,
        actor=user,
        target_type="report",
        target_id=report_id,
        detail=deleted,
    )


def _get_authorized_report(
    db: Session, user: models.Users, report_id: uuid.UUID
) -> models.Report:
    report = db.get(models.Report, report_id)
    if report is None:
        raise HTTPException(404, f"report {report_id} not found")
    authorize_owner(user, report.user_id)
    return report
