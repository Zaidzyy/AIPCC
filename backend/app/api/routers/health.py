"""Health / liveness endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/")
def health() -> dict:
    """Liveness probe. Does not touch the database."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
    }


@router.get("/health/db")
def health_db(db: Session = Depends(get_db)) -> dict:
    """Readiness probe. Confirms the app can reach Postgres."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
