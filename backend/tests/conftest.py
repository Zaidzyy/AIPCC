from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import engine
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def sample_csv() -> Path:
    path = FIXTURES / "synthetic_pegasus_dataset.csv"
    if not path.exists():
        pytest.skip(f"sample dataset missing at {path}")
    return path


@pytest.fixture
def db() -> Generator[Session, None, None]:
    """A session wrapped in a transaction that is always rolled back.

    Tests can commit freely; the outer transaction is discarded, so the
    database is left exactly as it was found.
    """
    try:
        connection = engine.connect()
    except Exception as exc:  # pragma: no cover - depends on local infra
        pytest.skip(f"Postgres not reachable ({exc}). Start it: docker compose up -d postgres")

    transaction = connection.begin()
    session = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
