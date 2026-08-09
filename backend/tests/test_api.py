"""Endpoint tests.

The app's `get_db` is overridden with the rolled-back test session, so these
exercise the real routes against real Postgres without leaving rows behind.
All fixtures live in conftest.py.
"""

from __future__ import annotations

import uuid


class TestHealth:
    """Health is deliberately unauthenticated — probes have no credentials."""

    def test_root(self, api):
        assert api.get("/").json()["status"] == "ok"

    def test_db_readiness(self, api):
        response = api.get("/health/db")
        assert response.status_code == 200
        assert response.json()["database"] == "reachable"


class TestStoreGeneratedReport:
    """The endpoint the n8n orchestrator calls. Previously did not exist."""

    def test_stores_and_reads_back(self, api, analyst_auth, document):
        payload = {
            "document_id": str(document.document_id),
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

        created = api.post("/store_generated_report", headers=analyst_auth, json=payload)
        assert created.status_code == 201, created.text
        body = created.json()
        report_id = body["report_id"]

        assert body["status"] == "complete"
        assert body["sections"]["attack_types"][0]["attack_name"] == "Credential Dumping"
        assert body["sections"]["attack_types"][0]["attack_mitre_technique_id"] == "T1003"

        fetched = api.get(f"/reports/{report_id}", headers=analyst_auth)
        assert fetched.status_code == 200
        assert fetched.json()["sections"]["timeline"][0]["event_name"] == "Initial access"

    def test_report_is_attributed_to_the_caller(self, api, analyst_auth, analyst, document):
        created = api.post(
            "/store_generated_report",
            headers=analyst_auth,
            json={
                "document_id": str(document.document_id),
                "report_name": "Attribution",
                "sections": {},
            },
        )
        assert created.json()["user_id"] == str(analyst.user_id)

    def test_requires_authentication(self, api, document):
        response = api.post(
            "/store_generated_report",
            json={
                "document_id": str(document.document_id),
                "report_name": "X",
                "sections": {},
            },
        )
        assert response.status_code == 401

    def test_cannot_attach_report_to_another_users_document(
        self, api, other_auth, document
    ):
        """`document` belongs to the analyst, not to other_user."""
        response = api.post(
            "/store_generated_report",
            headers=other_auth,
            json={
                "document_id": str(document.document_id),
                "report_name": "Not mine",
                "sections": {},
            },
        )
        assert response.status_code == 404

    def test_rejects_unknown_document(self, api, analyst_auth):
        response = api.post(
            "/store_generated_report",
            headers=analyst_auth,
            json={
                "document_id": str(uuid.uuid4()),
                "report_name": "X",
                "sections": {},
            },
        )
        assert response.status_code == 404

    def test_rejects_malformed_body(self, api, analyst_auth, document):
        response = api.post(
            "/store_generated_report",
            headers=analyst_auth,
            json={
                "document_id": str(document.document_id),
                "report_name": "",  # violates min_length
                "sections": {},
            },
        )
        assert response.status_code == 422


class TestReportStatus:
    def test_status_endpoint(self, api, analyst_auth, document):
        created = api.post(
            "/store_generated_report",
            headers=analyst_auth,
            json={
                "document_id": str(document.document_id),
                "report_name": "Status check",
                "sections": {"timeline": [{"event_name": "e"}]},
            },
        )
        report_id = created.json()["report_id"]

        status = api.get(f"/reports/{report_id}/status", headers=analyst_auth)
        assert status.status_code == 200
        assert status.json()["status"] == "complete"
        assert status.json()["report_id"] == report_id

    def test_unknown_report_is_404(self, api, analyst_auth):
        response = api.get(f"/reports/{uuid.uuid4()}/status", headers=analyst_auth)
        assert response.status_code == 404


class TestDocuments:
    def test_latest_content_404_when_none_uploaded(self, api, analyst_auth):
        response = api.get("/get_latest_document_content", headers=analyst_auth)
        assert response.status_code == 404

    def test_latest_content_410_when_file_missing(self, api, analyst_auth, document):
        """Row exists but the file on disk does not."""
        response = api.get("/get_latest_document_content", headers=analyst_auth)
        assert response.status_code == 410

    def test_upload_rejects_unsupported_type(self, api, analyst_auth):
        response = api.post(
            "/upload_file",
            headers=analyst_auth,
            files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert response.status_code == 400
        assert "unsupported file type" in response.json()["detail"]

    def test_upload_requires_authentication(self, api):
        response = api.post(
            "/upload_file", files={"file": ("a.csv", b"col\n1\n", "text/csv")}
        )
        assert response.status_code == 401

    def test_upload_ingests_and_registers(self, api, analyst_auth, analyst):
        """Full path: multipart upload -> disk -> DB row -> Chroma chunks."""
        csv = b"user_id,event,source_ip\n1,login,10.0.0.1\n2,logout,10.0.0.2\n"
        response = api.post(
            "/upload_file",
            headers=analyst_auth,
            files={"file": ("auth.csv", csv, "text/csv")},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["document_name"] == "auth.csv"
        assert body["chunk_count"] >= 1
        assert body["user_id"] == str(analyst.user_id)

        listed = api.get("/documents", headers=analyst_auth)
        assert any(d["document_id"] == body["document_id"] for d in listed.json())

    def test_analyst_sees_only_own_documents(
        self, api, analyst_auth, document, other_user, db
    ):
        from tests.conftest import _make_document

        theirs = _make_document(db, other_user, "theirs.csv")
        ids = {d["document_id"] for d in api.get("/documents", headers=analyst_auth).json()}
        assert str(document.document_id) in ids
        assert str(theirs.document_id) not in ids


class TestN8nAliases:
    """Paths the FIM workflow polls verbatim."""

    def test_get_all_reports(self, api, analyst_auth):
        assert api.get("/get_all_reports", headers=analyst_auth).status_code == 200

    def test_get_report_by_id(self, api, analyst_auth, document):
        created = api.post(
            "/store_generated_report",
            headers=analyst_auth,
            json={
                "document_id": str(document.document_id),
                "report_name": "Alias",
                "sections": {},
            },
        )
        report_id = created.json()["report_id"]
        assert api.get(f"/get_report_by_id/{report_id}", headers=analyst_auth).status_code == 200
