"""Phase 5: service-token auth, file integrity, alerts and threat intel.

The tests that matter most here are the negative ones. A service credential
that outlives a session is a standing risk, so what it *cannot* do is as much
a part of the design as what it can; and a file-serving route that takes a
caller-supplied name is the classic path-traversal shape, so the fact that the
name never reaches the filesystem needs to be asserted, not assumed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core import api_key as api_key_utils
from app.core.config import settings
from app.db import models
from app.services.integrity import IntegrityError, hash_file, resolve_upload_path

CONTENT = b"timestamp,src_ip,action\n2026-08-01T00:00:00Z,10.0.0.1,allow\n"


# --- Fixtures --------------------------------------------------------------


@pytest.fixture
def upload_file(tmp_path_factory):
    """Write a file inside the real upload directory and clean it up after.

    It has to be in `settings.upload_dir` rather than a tmp path, because
    "is this inside the upload directory" is exactly what the code under test
    checks.
    """
    written: list[Path] = []

    def _write(content: bytes = CONTENT, name: str | None = None) -> Path:
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        path = settings.upload_dir / (name or f"test_{uuid.uuid4().hex}.csv")
        path.write_bytes(content)
        written.append(path)
        return path

    yield _write

    for path in written:
        path.unlink(missing_ok=True)


def _document(db, owner, path: Path | None = None, name: str = "auth.csv"):
    now = datetime.now(timezone.utc)
    document = models.Document(
        document_name=name,
        document_size=1.0,
        document_extension=".csv",
        document_path=str(path) if path else "/nonexistent/auth.csv",
        created_at=now,
        modified_at=now,
        uploaded_at=now,
        user_id=owner.user_id,
    )
    db.add(document)
    db.flush()
    return document


def _report(db, owner, document=None) -> models.Report:
    report = models.Report(
        report_name="Report",
        document_id=(document or _document(db, owner)).document_id,
        user_id=owner.user_id,
        classification="Internal",
        status="complete",
    )
    db.add(report)
    db.flush()
    return report


def _issue_key(db, user, *, revoked: bool = False, expires_at=None) -> str:
    generated = api_key_utils.generate_key()
    db.add(
        models.ApiKey(
            name="test key",
            prefix=generated.prefix,
            key_hash=generated.key_hash,
            user_id=user.user_id,
            revoked=revoked,
            expires_at=expires_at,
        )
    )
    db.flush()
    return generated.secret


def _bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


# --- API key authentication ------------------------------------------------


def test_a_valid_api_key_authenticates_like_a_session(api, db, analyst):
    secret = _issue_key(db, analyst)
    response = api.get("/auth/me", headers=_bearer(secret))
    assert response.status_code == 200
    assert response.json()["email"] == analyst.email


def test_a_revoked_key_is_rejected(api, db, analyst):
    secret = _issue_key(db, analyst, revoked=True)
    assert api.get("/auth/me", headers=_bearer(secret)).status_code == 401


def test_an_expired_key_is_rejected(api, db, analyst):
    secret = _issue_key(
        db, analyst, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
    )
    assert api.get("/auth/me", headers=_bearer(secret)).status_code == 401


def test_a_key_with_a_future_expiry_still_works(api, db, analyst):
    secret = _issue_key(
        db, analyst, expires_at=datetime.now(timezone.utc) + timedelta(days=30)
    )
    assert api.get("/auth/me", headers=_bearer(secret)).status_code == 200


def test_an_unknown_key_is_rejected(api):
    secret = api_key_utils.generate_key().secret
    assert api.get("/auth/me", headers=_bearer(secret)).status_code == 401


def test_a_real_prefix_with_the_wrong_secret_is_rejected(api, db, analyst):
    """The prefix is the lookup key, not the credential."""
    secret = _issue_key(db, analyst)
    prefix = api_key_utils.extract_prefix(secret)
    forged = f"aipcc_{prefix}_not-the-right-secret"
    assert api.get("/auth/me", headers=_bearer(forged)).status_code == 401


def test_a_malformed_key_is_rejected_without_a_lookup(api):
    assert api.get("/auth/me", headers=_bearer("aipcc_broken")).status_code == 401


def test_a_secret_containing_the_separator_still_resolves():
    """Regression. `token_urlsafe` draws from the base64url alphabet, which
    includes `_`, so most secrets contain one. Splitting on every separator
    made a valid key unparseable and it 401'd roughly two times in three."""
    assert api_key_utils.extract_prefix("aipcc_abc123_secret_with_underscores") == "abc123"


def test_every_generated_key_round_trips():
    for _ in range(200):
        generated = api_key_utils.generate_key()
        assert api_key_utils.extract_prefix(generated.secret) == generated.prefix
        assert api_key_utils.verify_key(generated.secret, generated.key_hash)
        assert not api_key_utils.verify_key(generated.secret + "x", generated.key_hash)


def test_using_a_key_records_when_it_was_last_used(api, db, analyst):
    secret = _issue_key(db, analyst)
    prefix = api_key_utils.extract_prefix(secret)
    api.get("/auth/me", headers=_bearer(secret))

    record = db.query(models.ApiKey).filter_by(prefix=prefix).one()
    assert record.last_used_at is not None


def test_a_key_for_a_deactivated_account_is_refused(api, db, analyst):
    secret = _issue_key(db, analyst)
    analyst.status = "Suspended"
    db.flush()
    assert api.get("/auth/me", headers=_bearer(secret)).status_code == 403


# --- What a key deliberately cannot do -------------------------------------


def test_an_api_key_cannot_manage_users_even_as_an_admin(api, db, admin):
    """The containment that makes a long-lived credential acceptable."""
    secret = _issue_key(db, admin)
    assert api.get("/users", headers=_bearer(secret)).status_code == 403


def test_an_api_key_cannot_mint_another_api_key(api, db, admin):
    secret = _issue_key(db, admin)
    response = api.post("/api-keys", json={"name": "second"}, headers=_bearer(secret))
    assert response.status_code == 403


def test_an_api_key_can_still_do_the_work_it_exists_for(api, db, admin):
    """Containment must not have cost the workflow its actual job."""
    secret = _issue_key(db, admin)
    assert api.get("/get_all_reports", headers=_bearer(secret)).status_code == 200


def test_a_session_token_still_manages_users(api, admin_auth):
    assert api.get("/users", headers=admin_auth).status_code == 200


# --- API key management ----------------------------------------------------


def test_creating_a_key_returns_the_secret_exactly_once(api, admin_auth):
    created = api.post("/api-keys", json={"name": "n8n"}, headers=admin_auth)
    assert created.status_code == 201
    secret = created.json()["secret"]
    assert secret.startswith("aipcc_")

    listed = api.get("/api-keys", headers=admin_auth).json()
    mine = next(k for k in listed if k["key_id"] == created.json()["key_id"])
    assert "secret" not in mine
    assert mine["prefix"] == api_key_utils.extract_prefix(secret)


def test_a_created_key_authenticates(api, admin_auth):
    secret = api.post("/api-keys", json={"name": "n8n"}, headers=admin_auth).json()["secret"]
    assert api.get("/auth/me", headers=_bearer(secret)).status_code == 200


def test_only_an_admin_can_create_a_key(api, analyst_auth):
    assert api.post("/api-keys", json={"name": "x"}, headers=analyst_auth).status_code == 403


def test_creating_a_key_requires_authentication(api):
    assert api.post("/api-keys", json={"name": "x"}).status_code == 401


def test_revoking_a_key_stops_it_working(api, admin_auth):
    created = api.post("/api-keys", json={"name": "n8n"}, headers=admin_auth).json()
    assert api.get("/auth/me", headers=_bearer(created["secret"])).status_code == 200

    assert api.delete(f"/api-keys/{created['key_id']}", headers=admin_auth).status_code == 204
    assert api.get("/auth/me", headers=_bearer(created["secret"])).status_code == 401


def test_a_revoked_key_is_kept_for_the_record(api, admin_auth):
    created = api.post("/api-keys", json={"name": "n8n"}, headers=admin_auth).json()
    api.delete(f"/api-keys/{created['key_id']}", headers=admin_auth)

    listed = api.get("/api-keys", headers=admin_auth).json()
    row = next(k for k in listed if k["key_id"] == created["key_id"])
    assert row["revoked"] is True


# --- Path safety -----------------------------------------------------------


def test_resolve_upload_path_rejects_a_path_that_escapes_the_upload_directory():
    escaped = settings.upload_dir / ".." / ".." / ".env"
    with pytest.raises(IntegrityError):
        resolve_upload_path(escaped)


def test_resolve_upload_path_rejects_a_missing_file():
    with pytest.raises(IntegrityError):
        resolve_upload_path(settings.upload_dir / "definitely-not-here.csv")


def test_resolve_upload_path_accepts_a_real_upload(upload_file):
    path = upload_file()
    assert resolve_upload_path(path) == path.resolve()


def test_a_traversal_style_name_is_a_lookup_miss_not_a_file_read(api, analyst_auth):
    """The name is a database key. It is never joined onto a directory."""
    response = api.get("/uploads/..%2F..%2F.env", headers=analyst_auth)
    assert response.status_code == 404


# --- Downloads -------------------------------------------------------------


def test_downloading_a_document_returns_its_bytes(api, db, analyst, analyst_auth, upload_file):
    document = _document(db, analyst, upload_file())
    response = api.get(f"/documents/{document.document_id}/download", headers=analyst_auth)
    assert response.status_code == 200
    assert response.content == CONTENT


def test_downloading_someone_elses_document_is_a_404(
    api, db, other_user, analyst_auth, upload_file
):
    document = _document(db, other_user, upload_file())
    response = api.get(f"/documents/{document.document_id}/download", headers=analyst_auth)
    assert response.status_code == 404


def test_downloading_a_document_whose_file_is_gone_is_410_not_404(
    api, db, analyst, analyst_auth
):
    """The record exists; the bytes do not. The FIM engine handles those differently."""
    document = _document(db, analyst)
    response = api.get(f"/documents/{document.document_id}/download", headers=analyst_auth)
    assert response.status_code == 410


def test_downloading_by_name_returns_the_callers_own_document(
    api, db, analyst, analyst_auth, upload_file
):
    _document(db, analyst, upload_file(), name="shared-name.csv")
    response = api.get("/uploads/shared-name.csv", headers=analyst_auth)
    assert response.status_code == 200
    assert response.content == CONTENT


def test_downloading_by_name_does_not_reach_another_users_file(
    api, db, other_user, analyst_auth, upload_file
):
    _document(db, other_user, upload_file(b"secret"), name="theirs.csv")
    assert api.get("/uploads/theirs.csv", headers=analyst_auth).status_code == 404


def test_downloads_require_authentication(api, db, analyst, upload_file):
    document = _document(db, analyst, upload_file())
    assert api.get(f"/documents/{document.document_id}/download").status_code == 401
    assert api.get("/uploads/auth.csv").status_code == 401


# --- Integrity -------------------------------------------------------------


def test_a_report_seals_the_hash_of_its_source_document(
    api, db, analyst, analyst_auth, upload_file
):
    path = upload_file()
    document = _document(db, analyst, path)

    response = api.post(
        "/store_generated_report",
        json={
            "document_id": str(document.document_id),
            "report_name": "Sealed",
            "sections": {"attack_types": [{"attack_name": "Phishing"}]},
        },
        headers=analyst_auth,
    )
    assert response.status_code == 201
    assert response.json()["file_hash"] == hash_file(path)
    assert response.json()["integrity_state"] == "UNKNOWN"


def test_a_report_whose_source_file_is_missing_is_stored_unsealed(
    api, db, analyst, analyst_auth
):
    document = _document(db, analyst)
    response = api.post(
        "/store_generated_report",
        json={
            "document_id": str(document.document_id),
            "report_name": "Unsealed",
            "sections": {"attack_types": [{"attack_name": "Phishing"}]},
        },
        headers=analyst_auth,
    )
    assert response.status_code == 201
    assert response.json()["file_hash"] is None
    assert response.json()["integrity_state"] == "UNKNOWN"


@pytest.mark.parametrize("state", ["SEALED", "TAMPERED"])
def test_the_fim_engine_can_record_its_verdict(api, db, analyst, analyst_auth, state):
    report = _report(db, analyst)
    response = api.patch(
        f"/api/report/integrity/{report.report_id}",
        json={"integrity_state": state},
        headers=analyst_auth,
    )
    assert response.status_code == 200
    assert response.json()["integrity_state"] == state
    assert response.json()["integrity_checked_at"] is not None


def test_a_tamper_verdict_keeps_the_hash_it_observed(api, db, analyst, analyst_auth):
    report = _report(db, analyst)
    api.patch(
        f"/api/report/integrity/{report.report_id}",
        json={"integrity_state": "TAMPERED", "observed_hash": "a" * 64},
        headers=analyst_auth,
    )
    detail = api.get(f"/reports/{report.report_id}/status", headers=analyst_auth).json()
    assert "a" * 64 in detail["error_detail"]


def test_an_unknown_integrity_state_is_refused(api, db, analyst, analyst_auth):
    report = _report(db, analyst)
    response = api.patch(
        f"/api/report/integrity/{report.report_id}",
        json={"integrity_state": "PROBABLY_FINE"},
        headers=analyst_auth,
    )
    assert response.status_code == 422


def test_integrity_cannot_be_set_on_someone_elses_report(api, db, other_user, analyst_auth):
    report = _report(db, other_user)
    response = api.patch(
        f"/api/report/integrity/{report.report_id}",
        json={"integrity_state": "TAMPERED"},
        headers=analyst_auth,
    )
    assert response.status_code == 404


def test_integrity_updates_require_authentication(api, db, analyst):
    report = _report(db, analyst)
    response = api.patch(
        f"/api/report/integrity/{report.report_id}", json={"integrity_state": "SEALED"}
    )
    assert response.status_code == 401


def test_a_service_key_can_run_the_whole_fim_loop(api, db, admin, analyst, upload_file):
    """End to end on the credential the workflow actually uses."""
    secret = _issue_key(db, admin)
    headers = _bearer(secret)

    document = _document(db, analyst, upload_file())
    report = _report(db, analyst, document)

    assert api.get("/get_all_reports", headers=headers).status_code == 200
    assert api.get(f"/get_report_by_id/{report.report_id}", headers=headers).status_code == 200
    assert (
        api.get(f"/documents/{document.document_id}/download", headers=headers).status_code
        == 200
    )
    assert (
        api.patch(
            f"/api/report/integrity/{report.report_id}",
            json={"integrity_state": "SEALED"},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        api.post(
            "/api/security/alert",
            json={"message": "integrity verified", "report_id": str(report.report_id)},
            headers=headers,
        ).status_code
        == 201
    )


# --- Alerts ----------------------------------------------------------------


def test_creating_an_alert_stores_it_open(api, db, analyst, analyst_auth):
    report = _report(db, analyst)
    response = api.post(
        "/api/security/alert",
        json={
            "message": "File integrity mismatch",
            "severity": "CRITICAL",
            "source": "FIM & Audit Engine",
            "report_id": str(report.report_id),
        },
        headers=analyst_auth,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "open"
    assert body["severity"] == "critical"  # normalised on the way in
    assert body["source"] == "FIM & Audit Engine"


def test_an_alert_belongs_to_the_owner_of_its_report_not_the_poster(
    api, db, admin, analyst, admin_auth
):
    """The FIM engine posts on a service account; the analyst must still see it."""
    report = _report(db, analyst)
    body = api.post(
        "/api/security/alert",
        json={"message": "tampered", "report_id": str(report.report_id)},
        headers=admin_auth,
    ).json()
    assert body["user_id"] == str(analyst.user_id)


def test_an_alert_for_an_unknown_report_is_refused(api, analyst_auth):
    response = api.post(
        "/api/security/alert",
        json={"message": "x", "report_id": str(uuid.uuid4())},
        headers=analyst_auth,
    )
    assert response.status_code == 404


def test_an_alert_cannot_be_attached_to_someone_elses_report(
    api, db, other_user, analyst_auth
):
    report = _report(db, other_user)
    response = api.post(
        "/api/security/alert",
        json={"message": "x", "report_id": str(report.report_id)},
        headers=analyst_auth,
    )
    assert response.status_code == 404


def test_alerts_are_scoped_to_the_caller(api, db, analyst, other_user, analyst_auth, other_auth):
    api.post("/api/security/alert", json={"message": "mine"}, headers=analyst_auth)
    api.post("/api/security/alert", json={"message": "theirs"}, headers=other_auth)

    messages = [a["message"] for a in api.get("/alerts", headers=analyst_auth).json()]
    assert messages == ["mine"]


def test_alerts_can_be_filtered_by_status(api, analyst_auth):
    open_alert = api.post(
        "/api/security/alert", json={"message": "still open"}, headers=analyst_auth
    ).json()
    closed = api.post(
        "/api/security/alert", json={"message": "handled"}, headers=analyst_auth
    ).json()
    api.patch(f"/alerts/{closed['alert_id']}", json={"status": "resolved"}, headers=analyst_auth)

    ids = [a["alert_id"] for a in api.get("/alerts?status=open", headers=analyst_auth).json()]
    assert ids == [open_alert["alert_id"]]


def test_resolving_an_alert_stamps_when(api, analyst_auth):
    alert = api.post(
        "/api/security/alert", json={"message": "x"}, headers=analyst_auth
    ).json()
    resolved = api.patch(
        f"/alerts/{alert['alert_id']}", json={"status": "resolved"}, headers=analyst_auth
    ).json()
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"] is not None


def test_reopening_an_alert_clears_its_resolution_time(api, analyst_auth):
    """`resolved_at` must never describe an open alert."""
    alert = api.post(
        "/api/security/alert", json={"message": "x"}, headers=analyst_auth
    ).json()
    api.patch(f"/alerts/{alert['alert_id']}", json={"status": "resolved"}, headers=analyst_auth)
    reopened = api.patch(
        f"/alerts/{alert['alert_id']}", json={"status": "open"}, headers=analyst_auth
    ).json()
    assert reopened["resolved_at"] is None


def test_an_alert_cannot_be_resolved_by_a_stranger(api, db, other_user, analyst_auth):
    report = _report(db, other_user)
    alert = models.SecurityAlert(
        severity="high", source="test", message="x",
        report_id=report.report_id, user_id=other_user.user_id,
    )
    db.add(alert)
    db.flush()
    response = api.patch(
        f"/alerts/{alert.alert_id}", json={"status": "resolved"}, headers=analyst_auth
    )
    assert response.status_code == 404


def test_alerts_require_authentication(api):
    assert api.get("/alerts").status_code == 401
    assert api.post("/api/security/alert", json={"message": "x"}).status_code == 401


def test_open_alerts_reaches_the_dashboard_kpi(api, analyst_auth):
    assert api.get("/dashboard/summary", headers=analyst_auth).json()["open_alerts"] == 0

    alert = api.post(
        "/api/security/alert", json={"message": "x"}, headers=analyst_auth
    ).json()
    assert api.get("/dashboard/summary", headers=analyst_auth).json()["open_alerts"] == 1

    api.patch(f"/alerts/{alert['alert_id']}", json={"status": "resolved"}, headers=analyst_auth)
    assert api.get("/dashboard/summary", headers=analyst_auth).json()["open_alerts"] == 0


# --- Threat intelligence ---------------------------------------------------


def test_threat_intel_from_the_orchestrator_is_persisted_with_the_report(
    api, db, analyst, analyst_auth
):
    document = _document(db, analyst)
    created = api.post(
        "/store_generated_report",
        json={
            "document_id": str(document.document_id),
            "report_name": "Enriched",
            "sections": {"attack_types": [{"attack_name": "Phishing"}]},
            "threat_intel": [
                {
                    "indicator": "203.0.113.44",
                    "indicator_type": "ip",
                    "category": "External Infrastructure",
                    "source": "abuseipdb",
                    "reputation_score": 91,
                    "risk_level": "CRITICAL",
                    "country": "RU",
                    "usage_type": "Data Center/Web Hosting",
                    "raw": {"abuseConfidenceScore": 91},
                }
            ],
        },
        headers=analyst_auth,
    )
    assert created.status_code == 201

    detail = api.get(f"/reports/{created.json()['report_id']}", headers=analyst_auth).json()
    assert len(detail["threat_intel"]) == 1
    indicator = detail["threat_intel"][0]
    assert indicator["indicator"] == "203.0.113.44"
    assert indicator["reputation_score"] == 91
    assert indicator["raw"] == {"abuseConfidenceScore": 91}


def test_a_workflow_generated_report_belongs_to_the_analyst_not_the_service_account(
    api, db, admin, analyst, admin_auth
):
    """`/reports` is scoped by owner. If the orchestrator's reports were filed
    under the service account, the analyst whose log they describe could never
    see them — the difference between a feature and a black hole."""
    document = _document(db, analyst)
    created = api.post(
        "/store_generated_report",
        json={
            "document_id": str(document.document_id),
            "report_name": "From n8n",
            "sections": {"attack_types": [{"attack_name": "Phishing"}]},
        },
        headers=admin_auth,
    ).json()
    assert created["user_id"] == str(analyst.user_id)


def test_a_report_without_enrichment_still_stores(api, db, analyst, analyst_auth):
    document = _document(db, analyst)
    response = api.post(
        "/store_generated_report",
        json={
            "document_id": str(document.document_id),
            "report_name": "Plain",
            "sections": {"attack_types": [{"attack_name": "Phishing"}]},
        },
        headers=analyst_auth,
    )
    assert response.status_code == 201
    assert response.json()["threat_intel"] == []
