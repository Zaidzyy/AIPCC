"""Endpoint tests.

The app's `get_db` is overridden with the rolled-back test session, so these
exercise the real routes against real Postgres without leaving rows behind.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.db import models
from app.db.session import get_db
from app.main import app


@pytest.fixture
def api(db) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def user(db) -> models.Users:
    record = models.Users(
        first_name="API",
        last_name="Tester",
        email=f"api-{uuid.uuid4().hex[:8]}@aipcc.local",
        role="analyst",
        status="Active",
        password_hash=hash_password("x"),
    )
    db.add(record)
    db.flush()
    return record


@pytest.fixture
def document(db, user) -> models.Document:
    now = datetime.now(timezone.utc)
    record = models.Document(
        document_name="sample.csv",
        document_size=1.0,
        document_extension=".csv",
        document_path="/tmp/sample.csv",
        created_at=now,
        modified_at=now,
        uploaded_at=now,
        user_id=user.user_id,
    )
    db.add(record)
    db.flush()
    return record


class TestHealth:
    def test_root(self, api):
        assert api.get("/").json()["status"] == "ok"

    def test_db_readiness(self, api):
        response = api.get("/health/db")
        assert response.status_code == 200
        assert response.json()["database"] == "reachable"


class TestStoreGeneratedReport:
    """The endpoint the n8n orchestrator calls. Previously did not exist."""

    def test_stores_and_reads_back(self, api, user, document):
        payload = {
            "document_id": str(document.document_id),
            "user_id": str(user.user_id),
            "report_name": "From n8n",
            "classification": "Internal",
            "sections": {
                "attack_types": [
                    {
                        "attack_name": "Credential Dumping",
                        "attack_mitre_technique_id": "T1003",
                        "risk_level": "High",
                        "mitigation": "Rotate credentials.",
                    }
                ],
                "timeline": [{"event_name": "Initial access", "entity": "attacker"}],
            },
        }

        created = api.post("/store_generated_report", json=payload)
        assert created.status_code == 201, created.text
        body = created.json()
        report_id = body["report_id"]

        assert body["status"] == "complete"
        assert body["sections"]["attack_types"][0]["attack_name"] == "Credential Dumping"
        assert body["sections"]["attack_types"][0]["attack_mitre_technique_id"] == "T1003"

        fetched = api.get(f"/reports/{report_id}")
        assert fetched.status_code == 200
        assert fetched.json()["sections"]["timeline"][0]["event_name"] == "Initial access"

    def test_rejects_unknown_document(self, api, user):
        response = api.post(
            "/store_generated_report",
            json={
                "document_id": str(uuid.uuid4()),
                "user_id": str(user.user_id),
                "report_name": "X",
                "sections": {},
            },
        )
        assert response.status_code == 404

    def test_rejects_malformed_body(self, api, user, document):
        response = api.post(
            "/store_generated_report",
            json={
                "document_id": str(document.document_id),
                "user_id": str(user.user_id),
                "report_name": "",  # violates min_length
                "sections": {},
            },
        )
        assert response.status_code == 422


class TestReportStatus:
    def test_status_endpoint(self, api, user, document):
        created = api.post(
            "/store_generated_report",
            json={
                "document_id": str(document.document_id),
                "user_id": str(user.user_id),
                "report_name": "Status check",
                "sections": {"timeline": [{"event_name": "e"}]},
            },
        )
        report_id = created.json()["report_id"]

        status = api.get(f"/reports/{report_id}/status")
        assert status.status_code == 200
        assert status.json()["status"] == "complete"
        assert status.json()["report_id"] == report_id

    def test_unknown_report_is_404(self, api):
        assert api.get(f"/reports/{uuid.uuid4()}/status").status_code == 404


class TestDocuments:
    def test_latest_content_404_when_empty(self, api):
        response = api.get(
            "/get_latest_document_content", params={"user_id": str(uuid.uuid4())}
        )
        assert response.status_code == 404

    def test_latest_content_410_when_file_missing(self, api, user, document):
        """Row exists but the file on disk does not."""
        response = api.get(
            "/get_latest_document_content", params={"user_id": str(user.user_id)}
        )
        assert response.status_code == 410

    def test_upload_rejects_unsupported_type(self, api, user):
        response = api.post(
            "/upload_file",
            files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")},
            data={"user_id": str(user.user_id)},
        )
        assert response.status_code == 400
        assert "unsupported file type" in response.json()["detail"]

    def test_upload_rejects_empty_file(self, api, user):
        response = api.post(
            "/upload_file",
            files={"file": ("empty.csv", b"", "text/csv")},
            data={"file": "", "user_id": str(user.user_id)},
        )
        assert response.status_code in (400, 422)

    def test_upload_rejects_unknown_user(self, api):
        response = api.post(
            "/upload_file",
            files={"file": ("a.csv", b"col\n1\n", "text/csv")},
            data={"user_id": str(uuid.uuid4())},
        )
        assert response.status_code == 404

    def test_upload_ingests_and_registers(self, api, user, tmp_path):
        """Full path: multipart upload -> disk -> DB row -> Chroma chunks."""
        csv = b"user_id,event,source_ip\n1,login,10.0.0.1\n2,logout,10.0.0.2\n"
        response = api.post(
            "/upload_file",
            files={"file": ("auth.csv", csv, "text/csv")},
            data={"user_id": str(user.user_id)},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["document_name"] == "auth.csv"
        assert body["chunk_count"] >= 1
        assert body["user_id"] == str(user.user_id)

        listed = api.get("/documents", params={"user_id": str(user.user_id)})
        assert any(d["document_id"] == body["document_id"] for d in listed.json())


class TestN8nAliases:
    """Paths the FIM workflow polls verbatim."""

    def test_get_all_reports(self, api):
        assert api.get("/get_all_reports").status_code == 200

    def test_get_report_by_id(self, api, user, document):
        created = api.post(
            "/store_generated_report",
            json={
                "document_id": str(document.document_id),
                "user_id": str(user.user_id),
                "report_name": "Alias",
                "sections": {},
            },
        )
        report_id = created.json()["report_id"]
        assert api.get(f"/get_report_by_id/{report_id}").status_code == 200
