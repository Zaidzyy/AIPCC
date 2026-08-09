from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import hash_password
from app.db import models
from app.db.session import engine, get_db
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "test-password-123"


@pytest.fixture
def sample_csv() -> Path:
    path = FIXTURES / "synthetic_pegasus_dataset.csv"
    if not path.exists():
        pytest.skip(f"sample dataset missing at {path}")
    return path


@pytest.fixture
def db() -> Generator[Session, None, None]:
    """A session wrapped in a transaction that is always rolled back.

    Tests and the routes they call can commit freely; the outer transaction is
    discarded, so the database is left exactly as it was found.
    """
    try:
        connection = engine.connect()
    except Exception as exc:  # pragma: no cover - depends on local infra
        pytest.skip(
            f"Postgres not reachable ({exc}). Start it: docker compose up -d postgres"
        )

    transaction = connection.begin()
    session = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client() -> TestClient:
    """Unauthenticated client with the real database dependency."""
    return TestClient(app)


@pytest.fixture
def api(db) -> Generator[TestClient, None, None]:
    """Client bound to the rolled-back test session."""
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


# --- Users ---------------------------------------------------------------


def _make_user(db: Session, role: str, prefix: str) -> models.Users:
    user = models.Users(
        first_name=prefix.title(),
        last_name="Tester",
        email=f"{prefix}-{uuid.uuid4().hex[:8]}@aipcc.io",
        role=role,
        status="Active",
        password_hash=hash_password(PASSWORD),
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def analyst(db) -> models.Users:
    return _make_user(db, "analyst", "analyst")


@pytest.fixture
def admin(db) -> models.Users:
    return _make_user(db, "admin", "admin")


@pytest.fixture
def other_user(db) -> models.Users:
    return _make_user(db, "analyst", "other")


@pytest.fixture
def analyst_credentials(analyst) -> tuple[str, str]:
    return analyst.email, PASSWORD


def _auth_header(api: TestClient, email: str) -> dict[str, str]:
    response = api.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def analyst_auth(api, analyst) -> dict[str, str]:
    return _auth_header(api, analyst.email)


@pytest.fixture
def admin_auth(api, admin) -> dict[str, str]:
    return _auth_header(api, admin.email)


@pytest.fixture
def other_auth(api, other_user) -> dict[str, str]:
    return _auth_header(api, other_user.email)


# --- Documents and reports ----------------------------------------------


def _make_document(db: Session, owner: models.Users, name: str = "sample.csv"):
    now = datetime.now(timezone.utc)
    document = models.Document(
        document_name=name,
        document_size=1.0,
        document_extension=Path(name).suffix,
        document_path=f"/tmp/{name}",
        created_at=now,
        modified_at=now,
        uploaded_at=now,
        user_id=owner.user_id,
    )
    db.add(document)
    db.flush()
    return document


def _make_report(db: Session, owner: models.Users) -> uuid.UUID:
    document = _make_document(db, owner)
    report = models.Report(
        report_name="Report",
        document_id=document.document_id,
        user_id=owner.user_id,
        classification="Internal",
        status="complete",
    )
    db.add(report)
    db.flush()
    return report.report_id


@pytest.fixture
def document(db, analyst) -> models.Document:
    return _make_document(db, analyst)


@pytest.fixture
def analyst_report(db, analyst) -> uuid.UUID:
    return _make_report(db, analyst)


@pytest.fixture
def other_report(db, other_user) -> uuid.UUID:
    return _make_report(db, other_user)
