from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
