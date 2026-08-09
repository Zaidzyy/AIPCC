"""Report generation, storage and retrieval."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.report import (
    GenerateReportRequest,
    ReportDetail,
    ReportStatusResponse,
    ReportSummary,
    StoreGeneratedReportRequest,
)
from app.services.report import generate_report
from app.services.report_storage import load_report_detail, store_report

router = APIRouter(tags=["reports"])


@router.post("/generate_report", response_model=ReportDetail, status_code=201)
async def generate_report_endpoint(
    request: GenerateReportRequest,
    db: Session = Depends(get_db),
) -> ReportDetail:
    """Generate all five sections concurrently and persist them."""
    document = db.get(models.Document, request.document_id)
    if document is None:
        raise HTTPException(404, f"document {request.document_id} not found")
    if db.get(models.Users, request.user_id) is None:
        raise HTTPException(404, f"user {request.user_id} not found")

    result = await generate_report(str(request.document_id))

    if result.sections.is_empty():
        # Nothing usable came back. Persist the attempt so the failure is
        # visible and debuggable rather than vanishing.
        report = store_report(
            db,
            document_id=request.document_id,
            user_id=request.user_id,
            report_name=request.report_name,
            classification=request.classification,
            sections=result.sections,
            errors=result.errors,
        )
        detail = load_report_detail(db, report)
        detail.errors = result.errors
        raise HTTPException(
            status_code=502,
            detail={
                "message": "report generation produced no usable sections",
                "report_id": str(report.report_id),
                "errors": [e.model_dump() for e in result.errors],
            },
        )

    report = store_report(
        db,
        document_id=request.document_id,
        user_id=request.user_id,
        report_name=request.report_name,
        classification=request.classification,
        sections=result.sections,
        errors=result.errors,
    )

    detail = load_report_detail(db, report)
    detail.errors = result.errors
    return detail


@router.post("/store_generated_report", response_model=ReportDetail, status_code=201)
def store_generated_report(
    request: StoreGeneratedReportRequest,
    db: Session = Depends(get_db),
) -> ReportDetail:
    """Persist a report generated elsewhere — used by the n8n orchestrator.

    Deliberately shares `store_report` with the Python path, so a report from
    n8n and one from the app land in the same tables in the same shape.
    """
    if db.get(models.Document, request.document_id) is None:
        raise HTTPException(404, f"document {request.document_id} not found")
    if db.get(models.Users, request.user_id) is None:
        raise HTTPException(404, f"user {request.user_id} not found")

    report = store_report(
        db,
        document_id=request.document_id,
        user_id=request.user_id,
        report_name=request.report_name,
        classification=request.classification,
        sections=request.sections,
    )
    return load_report_detail(db, report)


@router.get("/reports", response_model=list[ReportSummary])
def list_reports(
    user_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> list[ReportSummary]:
    statement = select(models.Report).order_by(models.Report.generated_at.desc())
    if user_id:
        statement = statement.where(models.Report.user_id == user_id)
    return [ReportSummary.model_validate(r) for r in db.scalars(statement).all()]


@router.get("/get_all_reports", response_model=list[ReportSummary])
def get_all_reports(db: Session = Depends(get_db)) -> list[ReportSummary]:
    """Alias consumed by the n8n FIM workflow, which polls this path."""
    return list_reports(db=db)


@router.get("/reports/{report_id}/status", response_model=ReportStatusResponse)
def get_report_status(
    report_id: uuid.UUID, db: Session = Depends(get_db)
) -> ReportStatusResponse:
    report = db.get(models.Report, report_id)
    if report is None:
        raise HTTPException(404, f"report {report_id} not found")
    return ReportStatusResponse.model_validate(report)


@router.get("/reports/{report_id}", response_model=ReportDetail)
def get_report(report_id: uuid.UUID, db: Session = Depends(get_db)) -> ReportDetail:
    report = db.get(models.Report, report_id)
    if report is None:
        raise HTTPException(404, f"report {report_id} not found")
    return load_report_detail(db, report)


@router.get("/get_report_by_id/{report_id}", response_model=ReportDetail)
def get_report_by_id(
    report_id: uuid.UUID, db: Session = Depends(get_db)
) -> ReportDetail:
    """Alias consumed by the n8n FIM workflow."""
    return get_report(report_id, db)
