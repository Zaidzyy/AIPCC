"""Phase 2 tests: login, token handling, role enforcement, ownership scoping."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.core.security import (
    MAX_PASSWORD_BYTES,
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_is_bcrypt_and_not_the_password(self):
        digest = hash_password("correct horse battery staple")
        assert digest.startswith("$2b$")
        assert "correct horse" not in digest

    def test_verify_round_trip(self):
        digest = hash_password("s3cret-password")
        assert verify_password("s3cret-password", digest)
        assert not verify_password("wrong-password", digest)

    def test_salted_hashes_differ(self):
        assert hash_password("same") != hash_password("same")

    def test_overlong_password_rejected(self):
        with pytest.raises(ValueError, match="at most"):
            hash_password("x" * (MAX_PASSWORD_BYTES + 1))

    def test_corrupt_stored_hash_is_false_not_an_exception(self):
        """A bad row must not turn the login route into a 500."""
        assert verify_password("anything", "not-a-bcrypt-hash") is False


class TestTokens:
    def test_round_trip(self):
        user_id = uuid.uuid4()
        payload = decode_access_token(create_access_token(user_id, "admin"))
        assert payload["sub"] == str(user_id)
        assert payload["role"] == "admin"
        assert payload["type"] == "access"

    def test_expired_token_rejected(self):
        token = create_access_token(
            uuid.uuid4(), "analyst", expires_delta=timedelta(seconds=-1)
        )
        with pytest.raises(TokenError, match="expired"):
            decode_access_token(token)

    def test_tampered_token_rejected(self):
        token = create_access_token(uuid.uuid4(), "analyst")
        head, payload, signature = token.split(".")
        with pytest.raises(TokenError, match="invalid"):
            decode_access_token(f"{head}.{payload}.{signature[:-4]}AAAA")

    def test_garbage_rejected(self):
        with pytest.raises(TokenError):
            decode_access_token("not-a-token")

    def test_token_signed_with_another_key_rejected(self):
        import jwt as pyjwt

        forged = pyjwt.encode(
            {"sub": str(uuid.uuid4()), "role": "admin", "type": "access"},
            "an-attacker-chosen-key-that-is-long-enough-to-sign",
            algorithm="HS256",
        )
        with pytest.raises(TokenError):
            decode_access_token(forged)


class TestLogin:
    def test_login_returns_token(self, api, analyst_credentials):
        email, password = analyst_credentials
        response = api.post(
            "/auth/login", data={"username": email, "password": password}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert decode_access_token(body["access_token"])["sub"]

    def test_login_is_case_insensitive_on_email(self, api, analyst_credentials):
        email, password = analyst_credentials
        response = api.post(
            "/auth/login", data={"username": email.upper(), "password": password}
        )
        assert response.status_code == 200

    def test_wrong_password_rejected(self, api, analyst_credentials):
        email, _ = analyst_credentials
        response = api.post(
            "/auth/login", data={"username": email, "password": "wrong"}
        )
        assert response.status_code == 401

    def test_unknown_email_gives_identical_error(self, api, analyst_credentials):
        """Must not reveal whether an address is registered."""
        email, _ = analyst_credentials
        unknown = api.post(
            "/auth/login", data={"username": "nobody@aipcc.io", "password": "wrong"}
        )
        wrong_password = api.post(
            "/auth/login", data={"username": email, "password": "wrong"}
        )
        assert unknown.status_code == wrong_password.status_code == 401
        assert unknown.json()["detail"] == wrong_password.json()["detail"]

    def test_suspended_account_cannot_log_in(self, api, db, analyst, analyst_credentials):
        analyst.status = "Suspended"
        db.flush()
        email, password = analyst_credentials
        response = api.post(
            "/auth/login", data={"username": email, "password": password}
        )
        assert response.status_code == 403


class TestRegistration:
    def test_register_creates_analyst(self, api):
        response = api.post(
            "/auth/register",
            json={
                "first_name": "New",
                "last_name": "Person",
                "email": f"new-{uuid.uuid4().hex[:8]}@aipcc.io",
                "password": "a-good-password",
            },
        )
        assert response.status_code == 201
        assert response.json()["role"] == "analyst"
        assert "password" not in response.json()
        assert "password_hash" not in response.json()

    def test_cannot_self_assign_admin(self, api):
        """A role in the body must be ignored, not honoured."""
        response = api.post(
            "/auth/register",
            json={
                "first_name": "Sneaky",
                "last_name": "User",
                "email": f"sneaky-{uuid.uuid4().hex[:8]}@aipcc.io",
                "password": "a-good-password",
                "role": "admin",
            },
        )
        assert response.status_code == 201
        assert response.json()["role"] == "analyst"

    def test_duplicate_email_conflicts(self, api, analyst_credentials):
        email, _ = analyst_credentials
        response = api.post(
            "/auth/register",
            json={
                "first_name": "Dup",
                "last_name": "User",
                "email": email,
                "password": "a-good-password",
            },
        )
        assert response.status_code == 409

    def test_short_password_rejected(self, api):
        response = api.post(
            "/auth/register",
            json={
                "first_name": "A",
                "last_name": "B",
                "email": f"short-{uuid.uuid4().hex[:8]}@aipcc.io",
                "password": "tiny",
            },
        )
        assert response.status_code == 422

    def test_stored_password_is_hashed(self, api, db):
        from sqlalchemy import select

        from app.db import models

        email = f"hashcheck-{uuid.uuid4().hex[:8]}@aipcc.io"
        api.post(
            "/auth/register",
            json={
                "first_name": "Hash",
                "last_name": "Check",
                "email": email,
                "password": "plaintext-would-be-bad",
            },
        )
        user = db.scalar(select(models.Users).where(models.Users.email == email))
        assert user.password_hash != "plaintext-would-be-bad"
        assert user.password_hash.startswith("$2b$")


class TestProtectedRoutes:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/auth/me"),
            ("get", "/reports"),
            ("get", "/documents"),
            ("get", "/users"),
            ("get", "/get_all_reports"),
            ("get", "/get_latest_document_content"),
        ],
    )
    def test_without_token_is_401(self, api, method, path):
        assert getattr(api, method)(path).status_code == 401

    def test_with_invalid_token_is_401(self, api):
        response = api.get("/auth/me", headers={"Authorization": "Bearer nonsense"})
        assert response.status_code == 401

    def test_token_for_deleted_user_is_401(self, api):
        token = create_access_token(uuid.uuid4(), "analyst")
        response = api.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert "no longer exists" in response.json()["detail"]

    def test_me_returns_the_caller(self, api, analyst_auth, analyst):
        response = api.get("/auth/me", headers=analyst_auth)
        assert response.status_code == 200
        assert response.json()["user_id"] == str(analyst.user_id)


class TestRoleEnforcement:
    def test_analyst_cannot_list_users(self, api, analyst_auth):
        assert api.get("/users", headers=analyst_auth).status_code == 403

    def test_admin_can_list_users(self, api, admin_auth):
        assert api.get("/users", headers=admin_auth).status_code == 200

    def test_analyst_cannot_create_users(self, api, analyst_auth):
        response = api.post(
            "/users",
            headers=analyst_auth,
            json={
                "first_name": "X",
                "last_name": "Y",
                "email": f"x-{uuid.uuid4().hex[:8]}@aipcc.io",
                "password": "a-good-password",
                "role": "admin",
            },
        )
        assert response.status_code == 403

    def test_admin_can_create_user_with_role(self, api, admin_auth):
        response = api.post(
            "/users",
            headers=admin_auth,
            json={
                "first_name": "Made",
                "last_name": "ByAdmin",
                "email": f"made-{uuid.uuid4().hex[:8]}@aipcc.io",
                "password": "a-good-password",
                "role": "admin",
            },
        )
        assert response.status_code == 201
        assert response.json()["role"] == "admin"

    def test_admin_cannot_demote_self(self, api, admin_auth, admin):
        response = api.patch(
            f"/users/{admin.user_id}/role", headers=admin_auth, json={"role": "analyst"}
        )
        assert response.status_code == 400

    def test_admin_cannot_delete_self(self, api, admin_auth, admin):
        assert api.delete(f"/users/{admin.user_id}", headers=admin_auth).status_code == 400


class TestOwnershipScoping:
    def test_analyst_sees_only_own_reports(
        self, api, analyst_auth, analyst_report, other_report
    ):
        ids = {r["report_id"] for r in api.get("/reports", headers=analyst_auth).json()}
        assert str(analyst_report) in ids
        assert str(other_report) not in ids

    def test_admin_sees_all_reports(
        self, api, admin_auth, analyst_report, other_report
    ):
        ids = {r["report_id"] for r in api.get("/reports", headers=admin_auth).json()}
        assert {str(analyst_report), str(other_report)} <= ids

    def test_analyst_cannot_read_another_users_report(
        self, api, analyst_auth, other_report
    ):
        """404, not 403 — a 403 would confirm the id is real."""
        response = api.get(f"/reports/{other_report}", headers=analyst_auth)
        assert response.status_code == 404

    def test_analyst_cannot_delete_another_users_report(
        self, api, analyst_auth, other_report
    ):
        assert api.delete(f"/reports/{other_report}", headers=analyst_auth).status_code == 404

    def test_admin_can_read_any_report(self, api, admin_auth, other_report):
        assert api.get(f"/reports/{other_report}", headers=admin_auth).status_code == 200


class TestPasswordChange:
    def test_change_password_then_log_in_with_it(self, api, analyst_auth, analyst_credentials):
        email, password = analyst_credentials
        changed = api.post(
            "/auth/change-password",
            headers=analyst_auth,
            json={"current_password": password, "new_password": "brand-new-password"},
        )
        assert changed.status_code == 204

        assert (
            api.post("/auth/login", data={"username": email, "password": password}).status_code
            == 401
        )
        assert (
            api.post(
                "/auth/login",
                data={"username": email, "password": "brand-new-password"},
            ).status_code
            == 200
        )

    def test_wrong_current_password_rejected(self, api, analyst_auth):
        response = api.post(
            "/auth/change-password",
            headers=analyst_auth,
            json={"current_password": "not-it", "new_password": "brand-new-password"},
        )
        assert response.status_code == 400
