"""Share links and classification enforcement.

The point of these tests is that the rules hold *at the API*, not in the UI.
Every refusal below is reachable with curl and a token, which is exactly how a
share link is used — the recipient never loads the app that would hide a button.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core import share_token
from app.db import models

PDF_MAGIC = b"%PDF-"

JUSTIFICATION = "Requested by the incident commander for the 09:00 bridge."


@pytest.fixture
def report(db, analyst_report) -> models.Report:
    return db.get(models.Report, analyst_report)


def _create(api, auth, report_id, **body):
    return api.post(f"/reports/{report_id}/shares", json=body, headers=auth)


def _token_of(api, auth, report_id, **body) -> str:
    response = _create(api, auth, report_id, **body)
    assert response.status_code == 201, response.text
    return response.json()["token"]


def _record(db, token: str) -> models.ReportShare:
    return db.scalar(
        select(models.ReportShare).where(
            models.ReportShare.prefix == share_token.extract_prefix(token)
        )
    )


class TestTokenFormat:
    def test_a_token_is_not_a_jwt(self):
        token = share_token.generate_token().token
        assert token.startswith("shr_")
        # Three dot-separated segments is what a JWT looks like; nothing here
        # should be mistakable for one.
        assert token.count(".") == 0

    def test_a_token_cannot_be_confused_with_an_api_key(self):
        from app.core import api_key

        assert not api_key.looks_like_api_key(share_token.generate_token().token)

    def test_underscores_in_the_secret_survive_parsing(self):
        """The Phase 5 `token_urlsafe` bug, guarded on this token type too."""
        for _ in range(200):
            generated = share_token.generate_token()
            assert share_token.extract_prefix(generated.token) == generated.prefix
            assert share_token.verify_token(generated.token, generated.token_hash)

    @pytest.mark.parametrize("malformed", ["", "shr_", "shr_abc", "abc_def_ghi", "nonsense"])
    def test_malformed_tokens_have_no_prefix(self, malformed):
        assert share_token.extract_prefix(malformed) is None

    def test_only_the_hash_is_stored(self, api, analyst_auth, analyst_report, db):
        token = _token_of(api, analyst_auth, analyst_report)
        record = _record(db, token)
        assert record.token_hash == share_token.hash_token(token)
        assert token not in {value for value in vars(record).values() if isinstance(value, str)}


class TestCreate:
    def test_returns_the_token_once(self, api, analyst_auth, analyst_report):
        response = _create(api, analyst_auth, analyst_report, expires_in_hours=24)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["token"].startswith("shr_")
        assert body["token"] in body["url"]
        assert body["active"] is True
        assert body["view_count"] == 0

        # And never again: the list endpoint has no token field at all.
        listed = api.get(f"/reports/{analyst_report}/shares", headers=analyst_auth).json()
        assert len(listed) == 1
        assert "token" not in listed[0]

    def test_defaults_to_a_bounded_window(self, api, analyst_auth, analyst_report):
        """Sending no expiry gets a week, not forever."""
        body = _create(api, analyst_auth, analyst_report).json()
        assert body["expires_at"] is not None

    def test_never_expiring_is_possible_but_explicit(self, api, analyst_auth, analyst_report):
        body = _create(api, analyst_auth, analyst_report, expires_in_hours=None).json()
        assert body["expires_at"] is None

    def test_requires_authentication(self, api, analyst_report):
        assert api.post(f"/reports/{analyst_report}/shares", json={}).status_code == 401

    def test_cannot_share_another_users_report(self, api, analyst_auth, other_report):
        assert _create(api, analyst_auth, other_report).status_code == 404

    def test_an_api_key_cannot_mint_a_share(self, api, db, analyst, analyst_auth, analyst_report):
        """A leaked machine key must not be able to walk a report out of the system."""
        from app.core import api_key

        generated = api_key.generate_key()
        db.add(
            models.ApiKey(
                name="n8n",
                prefix=generated.prefix,
                key_hash=generated.key_hash,
                user_id=analyst.user_id,
            )
        )
        db.flush()

        machine = {"Authorization": f"Bearer {generated.secret}"}
        # The key works elsewhere...
        assert api.get("/reports", headers=machine).status_code == 200
        # ...and is refused here.
        assert _create(api, machine, analyst_report).status_code == 403


class TestRead:
    def test_grants_read_of_exactly_one_report(self, api, analyst_auth, analyst_report, db):
        second = models.Report(
            report_name="Unrelated",
            document_id=db.get(models.Report, analyst_report).document_id,
            user_id=db.get(models.Report, analyst_report).user_id,
            classification="Internal",
            status="complete",
        )
        db.add(second)
        db.flush()

        token = _token_of(api, analyst_auth, analyst_report)
        body = api.get(f"/share/{token}").json()
        assert body["report_name"] == "Report"
        # There is no parameter, path or field on the public view that reaches
        # a second report.
        assert "report_id" not in body
        assert str(second.report_id) not in api.get(f"/share/{token}").text

    def test_leaks_no_identity(self, api, analyst_auth, analyst_report, analyst):
        token = _token_of(api, analyst_auth, analyst_report)
        response = api.get(f"/share/{token}")
        assert response.status_code == 200
        body = response.json()
        for leaked in ("user_id", "report_id", "document_id", "file_hash", "created_by"):
            assert leaked not in body
        assert analyst.email not in response.text
        assert str(analyst.user_id) not in response.text

    def test_carries_the_report_itself(self, api, analyst_auth, analyst_report):
        token = _token_of(api, analyst_auth, analyst_report)
        body = api.get(f"/share/{token}").json()
        assert body["classification"] == "Internal"
        assert body["status"] == "complete"
        assert set(body["sections"]) == {
            "attack_types",
            "general_risk_assessment",
            "vulnerabilities",
            "anomalies",
            "timeline",
        }

    def test_needs_no_credentials(self, api, analyst_auth, analyst_report):
        token = _token_of(api, analyst_auth, analyst_report)
        assert api.get(f"/share/{token}", headers={}).status_code == 200

    def test_a_share_token_is_not_a_credential(self, api, analyst_auth, analyst_report):
        """Presented as a bearer token it authenticates nobody."""
        token = _token_of(api, analyst_auth, analyst_report)
        header = {"Authorization": f"Bearer {token}"}
        assert api.get("/reports", headers=header).status_code == 401
        assert api.get("/dashboard/summary", headers=header).status_code == 401

    def test_unknown_token(self, api):
        assert api.get(f"/share/{share_token.generate_token().token}").status_code == 404

    def test_counts_views(self, api, analyst_auth, analyst_report):
        token = _token_of(api, analyst_auth, analyst_report)
        api.get(f"/share/{token}")
        listed = api.get(f"/reports/{analyst_report}/shares", headers=analyst_auth).json()
        assert listed[0]["view_count"] == 1
        assert listed[0]["last_viewed_at"] is not None


class TestRevocation:
    def test_a_revoked_link_stops_working(self, api, analyst_auth, analyst_report, db):
        token = _token_of(api, analyst_auth, analyst_report)
        share_id = api.get(f"/reports/{analyst_report}/shares", headers=analyst_auth).json()[0][
            "share_id"
        ]

        assert api.get(f"/share/{token}").status_code == 200
        revoked = api.delete(f"/shares/{share_id}", headers=analyst_auth)
        assert revoked.status_code == 200
        assert revoked.json()["revoked"] is True
        assert revoked.json()["active"] is False
        assert api.get(f"/share/{token}").status_code == 404

    def test_revoked_is_indistinguishable_from_never_existed(
        self, api, analyst_auth, analyst_report
    ):
        """Revocation usually answers a leak. It must not confirm the leak was real."""
        token = _token_of(api, analyst_auth, analyst_report)
        share_id = api.get(f"/reports/{analyst_report}/shares", headers=analyst_auth).json()[0][
            "share_id"
        ]
        api.delete(f"/shares/{share_id}", headers=analyst_auth)

        revoked = api.get(f"/share/{token}")
        unknown = api.get(f"/share/{share_token.generate_token().token}")
        assert revoked.status_code == unknown.status_code == 404
        assert revoked.json() == unknown.json()

    def test_revoking_twice_is_not_an_error(self, api, analyst_auth, analyst_report):
        _token_of(api, analyst_auth, analyst_report)
        share_id = api.get(f"/reports/{analyst_report}/shares", headers=analyst_auth).json()[0][
            "share_id"
        ]
        assert api.delete(f"/shares/{share_id}", headers=analyst_auth).status_code == 200
        assert api.delete(f"/shares/{share_id}", headers=analyst_auth).status_code == 200

    def test_another_user_cannot_revoke(self, api, analyst_auth, other_auth, analyst_report):
        _token_of(api, analyst_auth, analyst_report)
        share_id = api.get(f"/reports/{analyst_report}/shares", headers=analyst_auth).json()[0][
            "share_id"
        ]
        assert api.delete(f"/shares/{share_id}", headers=other_auth).status_code == 404

    def test_an_admin_can_revoke_anyones_link(self, api, analyst_auth, admin_auth, analyst_report):
        _token_of(api, analyst_auth, analyst_report)
        share_id = api.get(f"/reports/{analyst_report}/shares", headers=analyst_auth).json()[0][
            "share_id"
        ]
        assert api.delete(f"/shares/{share_id}", headers=admin_auth).status_code == 200


class TestExpiry:
    def _expire(self, db, token: str) -> None:
        """Age a link out, rather than waiting an hour for it to happen."""
        record = _record(db, token)
        record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    def test_an_expired_link_is_refused(self, api, analyst_auth, analyst_report, db):
        token = _token_of(api, analyst_auth, analyst_report, expires_in_hours=1)
        assert api.get(f"/share/{token}").status_code == 200
        self._expire(db, token)
        response = api.get(f"/share/{token}")
        # 410, not 404: the holder was given this link legitimately and needs to
        # know it aged out rather than that the app is broken.
        assert response.status_code == 410
        assert "expired" in response.json()["detail"]

    def test_expiry_is_enforced_on_the_export_too(self, api, analyst_auth, analyst_report, db):
        token = _token_of(api, analyst_auth, analyst_report, expires_in_hours=1)
        self._expire(db, token)
        assert api.get(f"/share/{token}/export").status_code == 410

    def test_an_expired_link_reads_as_inactive_to_its_owner(
        self, api, analyst_auth, analyst_report, db
    ):
        token = _token_of(api, analyst_auth, analyst_report, expires_in_hours=1)
        self._expire(db, token)
        listed = api.get(f"/reports/{analyst_report}/shares", headers=analyst_auth).json()
        assert listed[0]["active"] is False
        assert listed[0]["revoked"] is False

    @pytest.mark.parametrize("hours", [0, -1, 400 * 24])
    def test_absurd_windows_are_rejected(self, api, analyst_auth, analyst_report, hours):
        assert _create(api, analyst_auth, analyst_report, expires_in_hours=hours).status_code == 422


class TestClassification:
    def test_the_vocabulary_is_closed(self, api, analyst_auth, analyst_report):
        response = api.patch(
            f"/reports/{analyst_report}/classification",
            json={"classification": "Restricted"},
            headers=analyst_auth,
        )
        assert response.status_code == 422

    def test_an_owner_can_reclassify(self, api, analyst_auth, analyst_report):
        response = api.patch(
            f"/reports/{analyst_report}/classification",
            json={"classification": "Public"},
            headers=analyst_auth,
        )
        assert response.status_code == 200
        assert response.json()["classification"] == "Public"

    def test_another_user_cannot_reclassify(self, api, analyst_auth, other_report):
        response = api.patch(
            f"/reports/{other_report}/classification",
            json={"classification": "Public"},
            headers=analyst_auth,
        )
        assert response.status_code == 404

    def test_generation_rejects_an_unknown_level(self, api, analyst_auth, document):
        response = api.post(
            "/generate_report",
            json={
                "document_id": str(document.document_id),
                "report_name": "R",
                "classification": "Top Secret",
            },
            headers=analyst_auth,
        )
        assert response.status_code == 422

    def test_confidential_needs_a_written_justification(
        self, api, analyst_auth, analyst_report, report, db
    ):
        report.classification = "Confidential"
        db.commit()

        refused = _create(api, analyst_auth, analyst_report)
        assert refused.status_code == 403
        assert "justification" in refused.json()["detail"]

    def test_the_override_is_recorded(self, api, analyst_auth, analyst_report, report, db):
        report.classification = "Confidential"
        db.commit()

        created = _create(api, analyst_auth, analyst_report, justification=JUSTIFICATION)
        assert created.status_code == 201
        assert created.json()["override_justification"] == JUSTIFICATION
        assert created.json()["classification_at_share"] == "Confidential"
        assert api.get(f"/share/{created.json()['token']}").status_code == 200

    def test_the_override_raises_an_alert(self, api, analyst_auth, analyst_report, report, db):
        """An override that lives only in a column nobody queries is not oversight."""
        report.classification = "Confidential"
        db.commit()
        _create(api, analyst_auth, analyst_report, justification=JUSTIFICATION)

        alerts = api.get("/alerts", headers=analyst_auth).json()
        override = [a for a in alerts if a["source"] == "share-link"]
        assert len(override) == 1
        assert JUSTIFICATION in override[0]["message"]
        assert override[0]["report_id"] == str(analyst_report)

    def test_no_override_is_recorded_for_an_ordinary_share(
        self, api, analyst_auth, analyst_report
    ):
        """A justification on an Internal link would read as an override that never happened."""
        created = _create(api, analyst_auth, analyst_report, justification=JUSTIFICATION)
        assert created.json()["override_justification"] is None
        assert not [
            a
            for a in api.get("/alerts", headers=analyst_auth).json()
            if a["source"] == "share-link"
        ]

    def test_raising_the_classification_kills_existing_links(
        self, api, analyst_auth, analyst_report, report, db
    ):
        """The enforcement that matters: the link holder never sees the UI."""
        token = _token_of(api, analyst_auth, analyst_report)
        assert api.get(f"/share/{token}").status_code == 200

        api.patch(
            f"/reports/{analyst_report}/classification",
            json={"classification": "Confidential"},
            headers=analyst_auth,
        )

        response = api.get(f"/share/{token}")
        assert response.status_code == 403
        assert "Confidential" in response.json()["detail"]
        assert api.get(f"/share/{token}/export").status_code == 403

    def test_lowering_it_again_restores_the_link(
        self, api, analyst_auth, analyst_report
    ):
        """Reclassification does not destroy links, so a mistake is reversible."""
        token = _token_of(api, analyst_auth, analyst_report)
        for level, expected in (("Confidential", 403), ("Internal", 200)):
            api.patch(
                f"/reports/{analyst_report}/classification",
                json={"classification": level},
                headers=analyst_auth,
            )
            assert api.get(f"/share/{token}").status_code == expected


class TestSharedExport:
    def test_a_link_holder_can_download_the_report(self, api, analyst_auth, analyst_report):
        token = _token_of(api, analyst_auth, analyst_report)
        response = api.get(f"/share/{token}/export")
        assert response.status_code == 200
        assert response.content.startswith(PDF_MAGIC)
        assert "attachment; filename=" in response.headers["content-disposition"]

    def test_the_shared_copy_carries_no_seal_and_no_reference(self):
        from app.schemas.report import ReportSections
        from app.schemas.share import SharedReport
        from app.services.export import source_from_shared

        source = source_from_shared(
            SharedReport(
                report_name="R",
                classification="Internal",
                status="complete",
                sections=ReportSections(),
            )
        )
        assert source.file_hash is None
        assert source.reference is None
        assert source.provenance == "Read-only copy, shared by link"

    def test_a_revoked_link_cannot_download(self, api, analyst_auth, analyst_report):
        token = _token_of(api, analyst_auth, analyst_report)
        share_id = api.get(f"/reports/{analyst_report}/shares", headers=analyst_auth).json()[0][
            "share_id"
        ]
        api.delete(f"/shares/{share_id}", headers=analyst_auth)
        assert api.get(f"/share/{token}/export").status_code == 404

    def test_unknown_share_id_revocation(self, api, analyst_auth):
        assert api.delete(f"/shares/{uuid.uuid4()}", headers=analyst_auth).status_code == 404
