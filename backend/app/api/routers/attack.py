"""The ATT&CK matrix: the grid, what was detected on it, and the export.

Thin, like every other router here. The grid comes from the vendored
catalogue and needs neither the caller nor the database; the detections come
from `services/attack_matrix.py` and are scoped exactly as `/reports` is.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import authorize_owner, get_current_user
from app.db import models
from app.db.session import get_db
from app.schemas.attack import DetectionSet, MatrixGrid
from app.services import attack_matrix, audit
from app.services.export.layout import filename_stem

router = APIRouter(prefix="/attack", tags=["attack"])


@router.get("/matrix", response_model=MatrixGrid)
def matrix() -> MatrixGrid:
    """The published enterprise matrix.

    Deliberately not scoped and deliberately not authenticated-by-owner: this
    is MITRE's data, identical for every caller, and the frontend caches it for
    the session rather than re-fetching a 200 KB grid per navigation.
    """
    return attack_matrix.matrix_grid()


@router.get("/detections", response_model=DetectionSet)
def all_detections(
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DetectionSet:
    """Techniques across every report the caller can see."""
    return attack_matrix.detections(db, user)


@router.get("/detections/{report_id}", response_model=DetectionSet)
def report_detections(
    report_id: uuid.UUID,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DetectionSet:
    """Techniques for one report."""
    _assert_visible(db, user, report_id)
    return attack_matrix.detections(db, user, report_id=report_id)


@router.get("/navigator-layer", response_class=Response)
def navigator_layer(
    request: Request,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Every visible detection as a layer file for MITRE's own Navigator."""
    found = attack_matrix.detections(db, user)
    layer = attack_matrix.navigator_layer(found, name="AIPCC — all reports")
    _record_export(db, request, user, target_id=None, found=found)
    return _as_layer_download(layer, "aipcc-attack-layer")


@router.get("/navigator-layer/{report_id}", response_class=Response)
def report_navigator_layer(
    report_id: uuid.UUID,
    request: Request,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """One report's detections as a Navigator layer file."""
    report = _assert_visible(db, user, report_id)
    found = attack_matrix.detections(db, user, report_id=report_id)
    layer = attack_matrix.navigator_layer(found, name=f"AIPCC — {report.report_name}")
    _record_export(db, request, user, target_id=report_id, found=found)
    return _as_layer_download(layer, filename_stem(report.report_name, report.generated_at))


# --- Internals ------------------------------------------------------------


def _assert_visible(db: Session, user: models.Users, report_id: uuid.UUID) -> models.Report:
    """404 on a report the caller does not own — never 403.

    Same rule as `/reports/{id}`: a 403 confirms the id is real to somebody who
    should not know that.
    """
    report = db.get(models.Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    authorize_owner(user, report.user_id)
    return report


def _record_export(
    db: Session,
    request: Request,
    user: models.Users,
    *,
    target_id: uuid.UUID | None,
    found: DetectionSet,
) -> None:
    """A layer file is a report leaving the system, so it is audited as one.

    Reusing `report.export` rather than minting a new action keeps the question
    "what left, and when" answerable with one query instead of two.
    """
    audit.record(
        db,
        action=audit.REPORT_EXPORT,
        request=request,
        actor=user,
        target_type="report",
        target_id=target_id,
        detail={
            "format": "navigator-layer",
            "scope": found.scope,
            "reports": found.reports_considered,
            "techniques": len(found.detections),
        },
    )


def _as_layer_download(layer: dict, stem: str) -> Response:
    # `.json` rather than a custom extension: Navigator's file picker takes a
    # .json, and a browser that opens it inline still shows something readable.
    body = json.dumps(layer, indent=2).encode("utf-8")
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{stem}-navigator.json"',
            "Content-Length": str(len(body)),
        },
    )
