"""Engine and session factory.

HARD RULE (CLAUDE.md #1): this module must never create or destroy schema, at
import time or anywhere else — see that file for the specific calls banned.
Schema changes go through Alembic only. The prototype wiped its database on
every boot precisely because such a call lived at module scope.

The banned call names are deliberately not written out here, so the acceptance
grep in PORTING.md stays clean. Enforced by
tests/test_foundation.py::TestHardRules.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # survive Postgres restarts without stale-connection errors
    echo=settings.debug,
    # Without this, connecting to a Postgres that isn't up blocks on the OS TCP
    # timeout — the readiness probe hangs instead of reporting unreachable.
    connect_args={"connect_timeout": 5},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
