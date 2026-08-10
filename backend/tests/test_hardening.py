"""Phase 8: brute-force protection, security headers, and the audit trail.

The tests that matter most here are the ones about *absence*: that a failed
login is still recorded after the request raises, that no endpoint can mutate
an audit row, and that a locked-out address has not also locked out the person
whose account was being sprayed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DatabaseError

from app.core import middleware
from app.core.config import settings
from app.db import models
from app.main import app
from app.services import audit, ratelimit
from tests.conftest import PASSWORD

# --- Helpers --------------------------------------------------------------


@pytest.fixture
def instant(monkeypatch) -> list[float]:
    """Record the progressive delay instead of serving it.

    Six real failures would sleep 2 + 4 + 8 + 8 seconds. The delay is asserted
    on directly — here through the recorded calls, and on the pure function in
    `TestAccountDelay` — rather than paid for in every test that needs a
    lockout.
    """
    slept: list[float] = []
    monkeypatch.setattr(
        "app.api.routers.auth.time.sleep", lambda seconds: slept.append(seconds)
    )
    return slept


@pytest.fixture
def from_ip(api, monkeypatch):
    """Send requests as if from a chosen address.

    `TestClient` has one client address, so distinct sources are simulated
    through `X-Forwarded-For` with the proxy setting turned on. The setting
    being *off* by default is itself asserted, in `test_forwarded_for_ignored`.
    """
    monkeypatch.setattr(settings, "trust_proxy_header", True)

    def send(ip: str, email: str, password: str = "wrong-password"):
        return api.post(
            "/auth/login",
            data={"username": email, "password": password},
            headers={"X-Forwarded-For": ip},
        )

    return send


def _backdate(db, *, identifier: str, delta: timedelta) -> None:
    """Age every attempt for one identifier, so a window expires without waiting."""
    for row in db.scalars(
        select(models.AuthAttempt).where(models.AuthAttempt.identifier == identifier)
    ):
        row.at = row.at - delta
    db.commit()


_BASELINE = datetime.min.replace(tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def audit_baseline():
    """Scope every audit assertion to what *this test* caused.

    The `db` fixture rolls back, but the audit log is append-only and rows
    written by a real run against the developer's database are still there —
    running the app locally for five minutes leaves a dozen. A test asserting
    `len(entries) == 1` is then only correct on an empty machine, which is the
    same trap the Phase 4 dashboard tests already paid for.

    This is the one table where the usual escape hatch does not exist: you
    cannot delete the noise, because a Postgres trigger refuses to.
    """
    global _BASELINE
    _BASELINE = datetime.now(timezone.utc)
    yield


def _entries(db, action: str) -> list[models.AuditLog]:
    """Read this test's audit rows, deliberately without autoflush.

    The `no_autoflush` is what makes the persistence tests mean anything. The
    route under test shares this exact session, so a row that was only `add`ed
    and never committed would still be flushed into the query by SQLAlchemy's
    default autoflush and the assertion would pass on a bug. Suppressing it
    means these tests see only what was actually committed — which is the whole
    claim `services/audit.record` makes.
    """
    with db.no_autoflush:
        return list(
            db.scalars(
                select(models.AuditLog)
                .where(models.AuditLog.action == action, models.AuditLog.at >= _BASELINE)
                .order_by(models.AuditLog.at)
            )
        )


# --- Brute force: the per-IP lockout --------------------------------------


class TestIpLockout:
    def test_locks_out_after_the_configured_failures(self, api, analyst, instant):
        for _ in range(settings.login_ip_max_failures):
            response = api.post(
                "/auth/login", data={"username": analyst.email, "password": "nope"}
            )
            assert response.status_code == 401

        blocked = api.post(
            "/auth/login", data={"username": analyst.email, "password": "nope"}
        )
        assert blocked.status_code == 429
        # Without Retry-After a client can only guess, and guessing means
        # hammering — the exact behaviour the limit exists to stop.
        assert int(blocked.headers["Retry-After"]) > 0

    def test_the_lockout_also_refuses_the_correct_password(self, api, analyst, instant):
        """A lockout that the right password walks through is not a lockout.

        This is the assertion that catches an implementation which checks the
        limit only on the failure path.
        """
        for _ in range(settings.login_ip_max_failures):
            api.post("/auth/login", data={"username": analyst.email, "password": "nope"})

        response = api.post(
            "/auth/login", data={"username": analyst.email, "password": PASSWORD}
        )
        assert response.status_code == 429

    def test_the_lockout_releases_when_the_window_passes(self, api, db, analyst, instant):
        for _ in range(settings.login_ip_max_failures):
            api.post("/auth/login", data={"username": analyst.email, "password": "nope"})
        assert (
            api.post("/auth/login", data={"username": analyst.email, "password": PASSWORD})
        ).status_code == 429

        _backdate(
            db,
            identifier="testclient",
            delta=timedelta(minutes=settings.login_ip_window_minutes + 1),
        )

        released = api.post(
            "/auth/login", data={"username": analyst.email, "password": PASSWORD}
        )
        assert released.status_code == 200

    def test_a_successful_login_does_not_refund_the_ip_budget(self, api, analyst, other_user, instant):
        """An attacker holding one valid account must not be able to reset their spray.

        The IP counter is failures-in-window regardless of successes, so signing
        in legitimately from the same host does not buy more guesses.
        """
        for _ in range(settings.login_ip_max_failures - 1):
            api.post("/auth/login", data={"username": analyst.email, "password": "nope"})

        assert (
            api.post("/auth/login", data={"username": other_user.email, "password": PASSWORD})
        ).status_code == 200

        api.post("/auth/login", data={"username": analyst.email, "password": "nope"})
        assert (
            api.post("/auth/login", data={"username": analyst.email, "password": "nope"})
        ).status_code == 429

    def test_forwarded_for_is_ignored_by_default(self, api, analyst, instant):
        """The header is caller-supplied, so trusting it is trusting the attacker.

        With `TRUST_PROXY_HEADER` off, rotating `X-Forwarded-For` must not buy
        an unlimited number of attempts — otherwise the lockout is keyed on a
        string the attacker picks, which is no lockout at all.
        """
        for index in range(settings.login_ip_max_failures):
            api.post(
                "/auth/login",
                data={"username": analyst.email, "password": "nope"},
                headers={"X-Forwarded-For": f"203.0.113.{index}"},
            )

        blocked = api.post(
            "/auth/login",
            data={"username": analyst.email, "password": "nope"},
            headers={"X-Forwarded-For": "203.0.113.250"},
        )
        assert blocked.status_code == 429


# --- Brute force: the account side is a delay, never a lock ----------------


class TestAccountIsNeverLocked:
    def test_a_sprayed_account_stays_usable(self, api, db, analyst, from_ip, instant):
        """The failure mode the design exists to avoid.

        A distributed spray against one account — every request from a fresh
        address, so the per-IP lockout never fills — must not take that account
        offline. If it did, anyone who knows an address could deny service to
        its owner with a handful of requests.
        """
        for index in range(settings.login_ip_max_failures * 3):
            assert from_ip(f"198.51.100.{index}", analyst.email).status_code == 401

        # The real user, from their own address, still gets in.
        response = api.post(
            "/auth/login",
            data={"username": analyst.email, "password": PASSWORD},
            headers={"X-Forwarded-For": "192.0.2.7"},
        )
        assert response.status_code == 200

        # ...and it cost them a delay, not a lockout.
        assert instant, "the account delay should have been applied to the attacker"
        assert max(instant) <= settings.login_delay_max_seconds

    def test_each_sprayed_address_still_burns_its_own_budget(self, analyst, from_ip, instant):
        """The attacker is not free either: every address they use dies after five."""
        for _ in range(settings.login_ip_max_failures):
            assert from_ip("198.51.100.99", analyst.email).status_code == 401
        assert from_ip("198.51.100.99", analyst.email).status_code == 429

    def test_a_success_resets_the_delay(self, api, db, analyst, instant):
        account = ratelimit.account_key(analyst.email)
        for _ in range(3):
            api.post("/auth/login", data={"username": analyst.email, "password": "nope"})
        assert ratelimit.consecutive_failures(db, identifier=account, action=ratelimit.LOGIN) == 3

        api.post("/auth/login", data={"username": analyst.email, "password": PASSWORD})

        # The person who knows the password is not made to wait for a spray
        # that targeted them earlier.
        assert ratelimit.consecutive_failures(db, identifier=account, action=ratelimit.LOGIN) == 0

    def test_an_unknown_address_is_delayed_too(self, api, instant):
        """Otherwise the delay itself enumerates accounts: fast means "no such user"."""
        unknown = f"ghost-{uuid.uuid4().hex[:8]}@aipcc.io"
        for _ in range(settings.login_delay_after_failures + 1):
            api.post("/auth/login", data={"username": unknown, "password": "nope"})
        assert instant and instant[-1] > 0


class TestAccountDelay:
    def test_no_delay_below_the_threshold(self):
        for failures in range(settings.login_delay_after_failures + 1):
            assert ratelimit.account_delay(failures) == 0.0

    def test_the_delay_doubles_then_caps(self):
        after = settings.login_delay_after_failures
        assert ratelimit.account_delay(after + 1) == 2.0
        assert ratelimit.account_delay(after + 2) == 4.0
        # The cap is not cosmetic: each delayed request holds a threadpool
        # thread, so an uncapped backoff is a denial of service on ourselves.
        assert ratelimit.account_delay(after + 20) == settings.login_delay_max_seconds


# --- The other rate-limited routes ----------------------------------------


class TestOtherRoutes:
    def test_registration_is_capped_per_address(self, api):
        def register(index: int):
            return api.post(
                "/auth/register",
                json={
                    "first_name": "Reg",
                    "last_name": "Tester",
                    "email": f"reg-{uuid.uuid4().hex[:10]}@aipcc.io",
                    "password": "a-long-enough-password",
                },
            )

        for index in range(settings.register_ip_max_per_hour):
            assert register(index).status_code == 201, "under the cap"

        # Counts every attempt, not only failures: the abuse here is bulk
        # *successful* registration.
        assert register(99).status_code == 429

    def test_change_password_locks_after_repeated_wrong_current(self, api, analyst_auth):
        body = {"current_password": "not-it", "new_password": "a-long-enough-password"}
        for _ in range(settings.password_change_max_failures):
            assert api.post("/auth/change-password", json=body, headers=analyst_auth).status_code == 400

        blocked = api.post("/auth/change-password", json=body, headers=analyst_auth)
        assert blocked.status_code == 429

    def test_a_change_password_lockout_cannot_be_inflicted_by_a_stranger(
        self, api, analyst, analyst_auth, other_auth, db
    ):
        """Reaching the route at all needs a session for that exact account.

        This is why a hard lock is safe here and not on login: the budget can
        only be spent by the account holder.
        """
        body = {"current_password": "not-it", "new_password": "a-long-enough-password"}
        for _ in range(settings.password_change_max_failures + 2):
            api.post("/auth/change-password", json=body, headers=other_auth)

        # The other user burned their own budget, not the analyst's.
        assert api.post(
            "/auth/change-password",
            json={"current_password": PASSWORD, "new_password": "a-long-enough-password"},
            headers=analyst_auth,
        ).status_code == 204

    def test_public_share_reads_are_throttled(self, api, db, monkeypatch):
        monkeypatch.setattr(settings, "share_ip_max_per_minute", 3)
        for _ in range(3):
            # 404 — the token is nonsense. The throttle counts attempts before
            # the token is resolved, so probing costs the same as using a link.
            assert api.get("/share/shr_nonexistent_token").status_code == 404
        assert api.get("/share/shr_nonexistent_token").status_code == 429


# --- Security headers ------------------------------------------------------


class TestSecurityHeaders:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            ("X-Frame-Options", "DENY"),
        ],
    )
    def test_present_on_a_real_response(self, api, analyst_auth, name, expected):
        response = api.get("/auth/me", headers=analyst_auth)
        assert response.status_code == 200
        assert response.headers[name] == expected

    def test_present_on_an_error_response(self, api):
        """Headers set by a route decorator would be missing here.

        A 401 is produced by an exception handler, not by route code, and it is
        exactly the kind of response an attacker sees most of.
        """
        response = api.get("/auth/me")
        assert response.status_code == 401
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]

    def test_permissions_policy_disables_unused_capabilities(self, api):
        policy = api.get("/health").headers["Permissions-Policy"]
        for capability in ("camera=()", "microphone=()", "geolocation=()", "payment=()"):
            assert capability in policy

    def test_the_api_policy_forbids_every_source(self, api):
        assert api.get("/health").headers["Content-Security-Policy"].startswith(
            "default-src 'none'"
        )

    def test_the_docs_policy_is_relaxed_enough_to_render(self):
        """One CSP for the whole app serves `/docs` as a blank page.

        Swagger UI is a real HTML document pulling script and CSS from a CDN
        with an inline bootstrap. Under `default-src 'none'` it loads nothing
        and shows nothing — which no unit test of the middleware constant would
        have caught, and which is why this was checked in a browser too.
        """
        policy = dict(middleware.headers_for("/docs", "http"))["Content-Security-Policy"]
        assert "https://cdn.jsdelivr.net" in policy
        assert "'unsafe-inline'" in policy
        # Still not framable, and still no wildcard.
        assert "frame-ancestors 'none'" in policy
        assert "*" not in policy

        # `/openapi.json` is data, not a page, so it keeps the strict policy.
        assert dict(middleware.headers_for("/openapi.json", "http"))[
            "Content-Security-Policy"
        ].startswith("default-src 'none'")

    def test_hsts_is_withheld_over_plain_http(self, api):
        """Sending it on `http://localhost` is spec-forbidden and a real foot-gun.

        A browser that caches HSTS for `localhost` refuses plain HTTP for every
        other project on the machine, with no obvious cause.
        """
        assert "Strict-Transport-Security" not in api.get("/health").headers

    def test_hsts_is_sent_over_https(self):
        headers = dict(middleware.headers_for("/health", "https"))
        assert headers["Strict-Transport-Security"] == middleware.HSTS

    def test_it_appends_and_never_overwrites(self):
        """A route that set its own framing policy knows something we do not.

        Driven at the ASGI layer against a stub that already sets one of the
        headers, because no route in this app currently does — and the point of
        the rule is the route somebody adds later.
        """
        captured: dict = {}

        async def stub(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"x-frame-options", b"SAMEORIGIN")],
                }
            )
            await send({"type": "http.response.body", "body": b""})

        async def record(message):
            if message["type"] == "http.response.start":
                captured.update(
                    {k.decode().lower(): v.decode() for k, v in message["headers"]}
                )

        async def noop():
            return {"type": "http.request"}

        import anyio

        wrapped = middleware.SecurityHeadersMiddleware(stub)
        anyio.run(
            wrapped, {"type": "http", "path": "/x", "scheme": "http"}, noop, record
        )

        assert captured["x-frame-options"] == "SAMEORIGIN", "the route's value survived"
        assert captured["x-content-type-options"] == "nosniff", "ours was still added"


# --- The audit trail -------------------------------------------------------


class TestAuditWrites:
    def test_a_successful_login_is_recorded(self, api, db, analyst):
        api.post("/auth/login", data={"username": analyst.email, "password": PASSWORD})
        entries = _entries(db, audit.LOGIN_SUCCESS)
        assert entries and entries[-1].actor_id == analyst.user_id
        assert entries[-1].source_ip == "testclient"

    def test_a_failed_login_survives_the_raised_request(self, api, db, analyst, instant):
        """The trap this phase was warned about, tested the only way that proves it.

        The route raises 401, so in production `get_db` closes a session with
        an uncommitted transaction — which rolls it back. An audit row that was
        merely `add`ed is gone, and the log ends up containing every login
        except the ones worth investigating.

        Reading the row straight after the request does *not* demonstrate this:
        the test session is the route's session and an intervening query has
        already autoflushed the row into the same transaction, so an
        uncommitted row is still visible. Verified by removing the commit — the
        naive assertion passed anyway.

        `db.rollback()` is what closes that gap. It discards to the savepoint,
        exactly as closing an uncommitted session would, so only a row that was
        genuinely committed is still there afterwards.
        """
        email = analyst.email

        api.post("/auth/login", data={"username": email, "password": "wrong"})
        db.rollback()

        entries = _entries(db, audit.LOGIN_FAILURE)
        assert len(entries) == 1, "the failure was not committed and did not survive"
        assert entries[0].outcome == audit.FAILURE
        assert entries[0].actor_label == email.lower()
        assert entries[0].detail["known_account"] is True

    def test_a_failed_login_is_never_attributed_to_the_account(
        self, api, db, analyst, instant
    ):
        """Nobody proved they were this user — that is what a failed login is.

        Recording `actor_id = <that user>` would state in the log that the user
        did this. The account is the *target* of the attempt; the actor is
        whoever was at that address, and they are unauthenticated by
        definition. Found by reading the rendered log, where a row saying
        "admin@aipcc.io — Login failure" was indistinguishable from something
        the admin had actually done.
        """
        api.post("/auth/login", data={"username": analyst.email, "password": "wrong"})

        entry = _entries(db, audit.LOGIN_FAILURE)[-1]
        assert entry.actor_type == audit.ANONYMOUS
        assert entry.actor_id is None
        # ...but the account is still filterable, as the target.
        assert (entry.target_type, entry.target_id) == ("user", str(analyst.user_id))

    def test_a_failed_attempt_is_counted_even_though_the_request_raised(
        self, api, db, analyst, instant
    ):
        """The same durability requirement, for the rate-limit state.

        A lockout counter that only persists on the success path counts
        nothing, because a brute-force attempt never takes the success path.
        """
        email = analyst.email

        api.post("/auth/login", data={"username": email, "password": "wrong"})
        db.rollback()

        with db.no_autoflush:
            attempts = db.scalars(
                select(models.AuthAttempt).where(
                    models.AuthAttempt.action == ratelimit.LOGIN,
                    models.AuthAttempt.successful.is_(False),
                )
            ).all()
        # One keyed on the address, one on the account.
        assert {a.scope for a in attempts} == {ratelimit.IP, ratelimit.ACCOUNT}

    def test_a_failure_against_an_unknown_address_is_recorded_too(self, api, db, instant):
        unknown = f"ghost-{uuid.uuid4().hex[:8]}@aipcc.io"
        api.post("/auth/login", data={"username": unknown, "password": "wrong"})

        entry = _entries(db, audit.LOGIN_FAILURE)[-1]
        # No actor row to point at, but the attempted address is the whole
        # value of the entry — a run of these is a spray.
        assert entry.actor_id is None
        assert entry.actor_type == audit.ANONYMOUS
        assert entry.actor_label == unknown.lower()
        assert entry.detail["known_account"] is False

    def test_a_lockout_is_its_own_event(self, api, db, analyst, instant):
        for _ in range(settings.login_ip_max_failures + 1):
            api.post("/auth/login", data={"username": analyst.email, "password": "nope"})

        blocked = _entries(db, audit.LOGIN_BLOCKED)
        assert blocked and blocked[-1].outcome == audit.BLOCKED

    def test_logout_is_recorded(self, api, db, analyst, analyst_auth):
        assert api.post("/auth/logout", headers=analyst_auth).status_code == 204
        assert _entries(db, audit.LOGOUT)[-1].actor_id == analyst.user_id

    def test_password_change_records_both_outcomes(self, api, db, analyst_auth):
        api.post(
            "/auth/change-password",
            json={"current_password": "wrong", "new_password": "a-long-enough-password"},
            headers=analyst_auth,
        )
        api.post(
            "/auth/change-password",
            json={"current_password": PASSWORD, "new_password": "a-long-enough-password"},
            headers=analyst_auth,
        )
        outcomes = [e.outcome for e in _entries(db, audit.PASSWORD_CHANGE)]
        assert outcomes == [audit.FAILURE, audit.SUCCESS]

    def test_a_role_change_records_the_transition(self, api, db, admin_auth, analyst):
        api.patch(
            f"/users/{analyst.user_id}/role", json={"role": "admin"}, headers=admin_auth
        )
        entry = _entries(db, audit.USER_ROLE_CHANGE)[-1]
        # A privilege escalation is only visible as a transition — "role: admin"
        # alone cannot be told from an account that always was one.
        assert entry.detail["from"] == "analyst"
        assert entry.detail["to"] == "admin"

    def test_a_user_deletion_outlives_the_user(self, api, db, admin_auth, other_user):
        email = other_user.email
        user_id = other_user.user_id
        assert api.delete(f"/users/{user_id}", headers=admin_auth).status_code == 204

        entry = _entries(db, audit.USER_DELETE)[-1]
        assert entry.target_id == str(user_id)
        # There is no foreign key on the audit log for exactly this reason: a
        # cascade would erase the record of what a deleted user did.
        assert entry.detail["email"] == email
        assert db.get(models.Users, user_id) is None

    def test_api_key_create_and_revoke_are_recorded_without_the_secret(
        self, api, db, admin_auth
    ):
        created = api.post("/api-keys", json={"name": "n8n"}, headers=admin_auth)
        assert created.status_code == 201
        secret = created.json()["secret"]
        key_id = created.json()["key_id"]

        api.delete(f"/api-keys/{key_id}", headers=admin_auth)

        rows = _entries(db, audit.API_KEY_CREATE) + _entries(db, audit.API_KEY_REVOKE)
        assert len(rows) == 2
        for row in rows:
            assert secret not in str(row.detail)
            assert row.detail["prefix"]

    def test_report_classification_export_and_delete_are_recorded(
        self, api, db, analyst_auth, analyst_report
    ):
        api.patch(
            f"/reports/{analyst_report}/classification",
            json={"classification": "Confidential"},
            headers=analyst_auth,
        )
        api.get(f"/reports/{analyst_report}/export?format=pdf", headers=analyst_auth)
        api.delete(f"/reports/{analyst_report}", headers=analyst_auth)

        classify = _entries(db, audit.REPORT_CLASSIFY)[-1]
        assert (classify.detail["from"], classify.detail["to"]) == ("Internal", "Confidential")

        export_row = _entries(db, audit.REPORT_EXPORT)[-1]
        # The classification travels with the export: "who took a Confidential
        # report out of the system" is the question this row answers.
        assert export_row.detail["classification"] == "Confidential"
        assert export_row.detail["format"] == "pdf"

        assert _entries(db, audit.REPORT_DELETE)[-1].target_id == str(analyst_report)

    def test_share_create_and_revoke_are_recorded_without_the_token(
        self, api, db, analyst_auth, analyst_report
    ):
        created = api.post(
            f"/reports/{analyst_report}/shares", json={"label": "vendor"}, headers=analyst_auth
        )
        assert created.status_code == 201
        token = created.json()["token"]
        share_id = created.json()["share_id"]

        api.delete(f"/shares/{share_id}", headers=analyst_auth)

        rows = _entries(db, audit.SHARE_CREATE) + _entries(db, audit.SHARE_REVOKE)
        assert len(rows) == 2
        for row in rows:
            # A capability written into a table an admin reads is a capability
            # an admin can use.
            assert token not in str(row.detail)

    def test_an_integrity_change_is_recorded_but_a_repeat_check_is_not(
        self, api, db, analyst_auth, analyst_report
    ):
        body = {"integrity_state": "TAMPERED", "observed_hash": "a" * 64}
        api.patch(f"/api/report/integrity/{analyst_report}", json=body, headers=analyst_auth)
        api.patch(f"/api/report/integrity/{analyst_report}", json=body, headers=analyst_auth)

        entries = _entries(db, audit.INTEGRITY_CHANGE)
        # The FIM engine re-checks on a schedule. Recording every verdict would
        # bury the real events under a thousand rows a day saying "still fine".
        assert len(entries) == 1
        assert entries[0].detail == {"from": "UNKNOWN", "to": "TAMPERED"}
        assert entries[0].outcome == audit.FAILURE

    def test_an_api_key_caller_is_distinguishable_from_a_person(
        self, api, db, admin_auth, analyst_report
    ):
        """`actor_type` is inferred from how the request authenticated.

        Both credential types arrive in the same `Authorization: Bearer`
        header, so without this the log cannot tell an n8n workflow from the
        admin whose account it runs as — and "did a person do this?" is the
        first question asked about anything unexpected.
        """
        created = api.post("/api-keys", json={"name": "n8n"}, headers=admin_auth)
        machine = {"Authorization": f"Bearer {created.json()['secret']}"}

        response = api.patch(
            f"/api/report/integrity/{analyst_report}",
            json={"integrity_state": "SEALED"},
            headers=machine,
        )
        assert response.status_code == 200

        assert _entries(db, audit.INTEGRITY_CHANGE)[-1].actor_type == audit.API_KEY
        assert _entries(db, audit.API_KEY_CREATE)[-1].actor_type == audit.USER


class TestRedaction:
    def test_forbidden_keys_never_reach_the_row(self, db, analyst):
        entry = audit.record(
            db,
            action=audit.LOGIN_SUCCESS,
            actor=analyst,
            detail={
                "password": "hunter2",
                "access_token": "ey.J.hdr",
                "api_key_secret": "aipcc_abc",
                "note": "kept",
            },
        )
        assert entry.detail["note"] == "kept"
        for key in ("password", "access_token", "api_key_secret"):
            assert entry.detail[key] == audit.REDACTED

    def test_a_nested_structure_cannot_smuggle_one_past(self, db, analyst):
        entry = audit.record(
            db,
            action=audit.LOGIN_SUCCESS,
            actor=analyst,
            detail={"outer": {"password": "hunter2"}},
        )
        # Flattened to a clipped string rather than stored as a dict, so the
        # key-name check above cannot be bypassed one level down.
        assert isinstance(entry.detail["outer"], str)

    def test_long_values_are_clipped(self, db, analyst):
        """"Never record full document contents" is a length problem, not only a naming one."""
        entry = audit.record(
            db, action=audit.LOGIN_SUCCESS, actor=analyst, detail={"excerpt": "x" * 50_000}
        )
        assert len(entry.detail["excerpt"]) <= audit.MAX_VALUE_LENGTH + 1


class TestAppendOnly:
    def test_the_api_exposes_no_write_path(self):
        """Enforced against the route table, not by reading the module.

        A future PATCH /audit/{id} would fail here even if it were added in a
        different file.
        """
        writes = [
            (route.path, sorted(route.methods))
            for route in app.routes
            if getattr(route, "path", "").startswith("/audit")
            and getattr(route, "methods", set()) - {"GET", "HEAD", "OPTIONS"}
        ]
        assert writes == []

    def test_the_database_refuses_an_update(self, db, analyst):
        audit.record(db, action=audit.LOGIN_SUCCESS, actor=analyst)

        savepoint = db.begin_nested()
        with pytest.raises(DatabaseError, match="append-only"):
            db.execute(text("UPDATE audit_log SET action = 'tampered'"))
        savepoint.rollback()

    def test_the_database_refuses_a_delete(self, db, analyst):
        audit.record(db, action=audit.LOGIN_SUCCESS, actor=analyst)

        savepoint = db.begin_nested()
        with pytest.raises(DatabaseError, match="append-only"):
            db.execute(text("DELETE FROM audit_log"))
        savepoint.rollback()

    def test_the_database_refuses_a_truncate(self, db, analyst):
        """TRUNCATE never fires a row-level trigger, so it needs its own.

        Without the statement trigger, "append-only" is one `TRUNCATE
        audit_log` away from being false.
        """
        audit.record(db, action=audit.LOGIN_SUCCESS, actor=analyst)

        savepoint = db.begin_nested()
        with pytest.raises(DatabaseError, match="append-only"):
            db.execute(text("TRUNCATE audit_log"))
        savepoint.rollback()

    def test_prune_with_a_zero_window_clears_everything(self, db):
        """`--days 0` is the only way to empty the table, and it must work.

        Found live: `older_than or default` treated `timedelta(0)` as absent,
        because a zero timedelta is falsy. The command reported "pruned 0" and
        left every row in place.
        """
        ratelimit.record(
            db, scope=ratelimit.IP, identifier="10.0.0.1",
            action=ratelimit.LOGIN, successful=False,
        )
        assert ratelimit.prune(db, older_than=timedelta(0)) >= 1
        assert db.scalar(select(models.AuthAttempt.attempt_id).limit(1)) is None

    def test_prune_never_touches_the_audit_log(self, db, analyst):
        entry = audit.record(db, action=audit.LOGIN_SUCCESS, actor=analyst)

        ratelimit.record(
            db, scope=ratelimit.IP, identifier="10.0.0.9",
            action=ratelimit.LOGIN, successful=False,
        )
        assert ratelimit.prune(db, older_than=timedelta(seconds=-1)) >= 1

        survivor = db.scalar(
            select(models.AuditLog.audit_id).where(
                models.AuditLog.audit_id == entry.audit_id
            )
        )
        assert survivor == entry.audit_id


# --- The admin view --------------------------------------------------------


class TestAuditEndpoint:
    def test_an_analyst_cannot_read_it(self, api, analyst_auth):
        assert api.get("/audit", headers=analyst_auth).status_code == 403

    def test_it_requires_authentication(self, api):
        assert api.get("/audit").status_code == 401

    def test_an_api_key_cannot_read_it(self, api, admin_auth):
        """Same containment as `/users` and `/api-keys`.

        This endpoint is the most useful single read in the application for
        somebody who should not have it, and a machine key lives in a
        credential store it can be copied out of.
        """
        created = api.post("/api-keys", json={"name": "n8n"}, headers=admin_auth)
        machine = {"Authorization": f"Bearer {created.json()['secret']}"}
        assert api.get("/audit", headers=machine).status_code == 403

    def test_an_admin_sees_entries_newest_first(self, api, db, admin_auth, analyst, instant):
        api.post("/auth/login", data={"username": analyst.email, "password": "nope"})

        page = api.get("/audit", headers=admin_auth).json()
        assert page["total"] >= 1
        stamps = [item["at"] for item in page["items"]]
        assert stamps == sorted(stamps, reverse=True)

    def test_filtering_by_action(self, api, admin_auth, analyst, instant):
        api.post("/auth/login", data={"username": analyst.email, "password": "nope"})

        page = api.get(
            "/audit", params={"action": audit.LOGIN_FAILURE}, headers=admin_auth
        ).json()
        assert page["items"]
        assert {item["action"] for item in page["items"]} == {audit.LOGIN_FAILURE}

    def test_filtering_by_actor_uuid_and_by_label(self, api, admin_auth, analyst):
        api.post("/auth/login", data={"username": analyst.email, "password": PASSWORD})

        by_id = api.get(
            "/audit", params={"actor": str(analyst.user_id)}, headers=admin_auth
        ).json()
        assert by_id["items"]
        assert {item["actor_id"] for item in by_id["items"]} == {str(analyst.user_id)}

        # The same parameter also accepts free text, so the filter is usable
        # from a row where only the address is on screen.
        by_label = api.get(
            "/audit", params={"actor": analyst.email.split("@")[0]}, headers=admin_auth
        ).json()
        assert by_label["items"]

    def test_pagination_reports_the_total(self, api, admin_auth, analyst, instant):
        for _ in range(3):
            api.post("/auth/login", data={"username": analyst.email, "password": "nope"})

        page = api.get("/audit", params={"limit": 1}, headers=admin_auth).json()
        assert len(page["items"]) == 1
        # Without the total a paginated view cannot tell "this is the end" from
        # "the next page failed" — the same empty-vs-failed rule as every list.
        assert page["total"] >= 3

    def test_the_filter_vocabulary_is_the_closed_action_list(self, api, admin_auth):
        filters = api.get("/audit/filters", headers=admin_auth).json()
        assert set(filters["actions"]) == set(audit.ACTIONS)
        assert filters["outcomes"] == [audit.SUCCESS, audit.FAILURE, audit.BLOCKED]

    def test_reads_are_not_themselves_audited(self, api, db, admin_auth):
        def count() -> int:
            with db.no_autoflush:
                return db.scalar(
                    select(func.count())
                    .select_from(models.AuditLog)
                    .where(models.AuditLog.at >= _BASELINE)
                ) or 0

        before = count()
        api.get("/audit", headers=admin_auth)
        api.get("/audit", headers=admin_auth)
        api.get("/audit/filters", headers=admin_auth)

        # Otherwise the page shows its own visit as the newest entry, and a
        # scheduled dashboard fills the log with the fact that it looked at it.
        assert count() == before


def test_the_audit_row_stamps_utc(db, analyst):
    entry = audit.record(db, action=audit.LOGIN_SUCCESS, actor=analyst)
    assert entry.at.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - entry.at).total_seconds()) < 60
