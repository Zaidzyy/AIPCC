"""The audit trail: who did what, to what, from where, and when.

**Append-only, enforced twice.** No endpoint updates or deletes an audit row —
and a Postgres trigger raises on UPDATE, DELETE and TRUNCATE against the table
regardless. The trigger is the one that still holds after somebody adds a
well-meaning "clean up old audit entries" endpoint two years from now. See the
`d4b7f2a19c30` migration.

**A failed login has to be recorded even though its request raises.** The
request-scoped session is closed without committing when a route raises, so an
audit row merely `add`ed on that path is silently lost — which would leave the
log recording every login except the ones worth investigating. `record()`
therefore commits. The rule at the call sites follows from that: call it either
immediately after the business commit, or immediately before raising, so the
commit it performs has nothing else of its own pending.

It uses the caller's injected session rather than opening its own, so the test
suite's rolled-back transaction contains the audit writes too. A private
`SessionLocal()` would write straight past the fixture into the real database.

**What must never land here** is enforced rather than trusted: `detail` values
are redacted by key name and truncated by length, so no call site can leak a
password, a token, a key secret or a document's contents into the log by
passing the wrong dict.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.db import models
from app.services import ratelimit

# --- Vocabulary -----------------------------------------------------------
#
# Dotted `subject.verb`, so the admin filter can group by prefix and a new
# action sorts next to its siblings. Closed on purpose: `ACTIONS` is what the
# filter dropdown offers, and an action recorded but not listed here is one
# nobody will ever filter for.

LOGIN_SUCCESS = "auth.login.success"
LOGIN_FAILURE = "auth.login.failure"
LOGIN_BLOCKED = "auth.login.blocked"
LOGOUT = "auth.logout"
REGISTER = "auth.register"
PASSWORD_CHANGE = "auth.password_change"

USER_CREATE = "user.create"
USER_ROLE_CHANGE = "user.role_change"
USER_STATUS_CHANGE = "user.status_change"
USER_DELETE = "user.delete"

API_KEY_CREATE = "api_key.create"
API_KEY_REVOKE = "api_key.revoke"

REPORT_CREATE = "report.create"
REPORT_DELETE = "report.delete"
REPORT_CLASSIFY = "report.classification_change"
REPORT_EXPORT = "report.export"
INTEGRITY_CHANGE = "report.integrity_change"

SHARE_CREATE = "share.create"
SHARE_REVOKE = "share.revoke"

ACTIONS: tuple[str, ...] = (
    LOGIN_SUCCESS,
    LOGIN_FAILURE,
    LOGIN_BLOCKED,
    LOGOUT,
    REGISTER,
    PASSWORD_CHANGE,
    USER_CREATE,
    USER_ROLE_CHANGE,
    USER_STATUS_CHANGE,
    USER_DELETE,
    API_KEY_CREATE,
    API_KEY_REVOKE,
    REPORT_CREATE,
    REPORT_DELETE,
    REPORT_CLASSIFY,
    REPORT_EXPORT,
    INTEGRITY_CHANGE,
    SHARE_CREATE,
    SHARE_REVOKE,
)

SUCCESS = "success"
FAILURE = "failure"
BLOCKED = "blocked"

USER = "user"
API_KEY = "api_key"
ANONYMOUS = "anonymous"
SYSTEM = "system"

# --- Redaction ------------------------------------------------------------

REDACTED = "[redacted]"

# Matched as substrings of the *key*, case-folded. Deliberately blunt: a detail
# field named `reset_token_hint` is not worth arguing about, and the cost of a
# false positive is a dash in an admin table while the cost of a false negative
# is a credential in permanent storage.
_FORBIDDEN_KEYS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "authorization",
    "api_key",
)

# Long enough for a filename, a classification or a reason; far too short for a
# log file. "Never record full document contents" is a length problem as much
# as a naming one, and a call site that passes an excerpt gets it clipped.
MAX_VALUE_LENGTH = 500


def redact(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip forbidden keys and clip long values.

    Redacts rather than raising. An audit write is not the place to turn a
    programming mistake into a failed request — the row still gets written, and
    the `[redacted]` marker says plainly that something was dropped rather than
    quietly omitting the key.
    """
    if not detail:
        return None

    clean: dict[str, Any] = {}
    for key, value in detail.items():
        name = str(key)
        if any(word in name.casefold() for word in _FORBIDDEN_KEYS):
            clean[name] = REDACTED
            continue
        if isinstance(value, str) and len(value) > MAX_VALUE_LENGTH:
            clean[name] = value[:MAX_VALUE_LENGTH] + "…"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            clean[name] = value
        else:
            # Anything structured is flattened to its repr and clipped, so a
            # nested dict cannot smuggle a forbidden key past the check above.
            clean[name] = str(value)[:MAX_VALUE_LENGTH]
    return clean


# --- Writing --------------------------------------------------------------


def record(
    db: Session,
    *,
    action: str,
    outcome: str = SUCCESS,
    request: Request | None = None,
    actor: models.Users | None = None,
    actor_type: str | None = None,
    actor_label: str | None = None,
    target_type: str | None = None,
    target_id: object | None = None,
    detail: dict[str, Any] | None = None,
) -> models.AuditLog:
    """Append one row and commit it. See the module docstring on why it commits.

    `actor_type` is inferred from the request when an actor is given, so a
    route instrumented once records correctly whether it was reached with a
    session or with a machine key — which is exactly the distinction an
    investigator needs and exactly the one a call site would forget to pass.
    """
    resolved_type = actor_type or _actor_type(request, actor)

    entry = models.AuditLog(
        at=datetime.now(timezone.utc),
        action=action,
        outcome=outcome,
        actor_type=resolved_type,
        actor_id=actor.user_id if actor else None,
        actor_label=(actor_label or (actor.email if actor else None)),
        target_type=target_type,
        target_id=str(target_id)[:64] if target_id is not None else None,
        source_ip=_source_ip(request),
        # Phase 9's middleware sets this; until then it is None and the column
        # is simply empty rather than absent.
        correlation_id=getattr(request.state, "correlation_id", None) if request else None,
        detail=redact(detail),
    )
    db.add(entry)
    db.commit()
    return entry


def _actor_type(request: Request | None, actor: models.Users | None) -> str:
    if actor is None:
        return ANONYMOUS
    method = getattr(request.state, "auth_method", None) if request else None
    return API_KEY if method == "api_key" else USER


def _source_ip(request: Request | None) -> str | None:
    # Reuses the limiter's rule, so the address written to the log and the
    # address a lockout was keyed on can never disagree about who the caller
    # was — which is the first thing anyone checks when a block looks wrong.
    return ratelimit.client_ip(request) if request is not None else None


def actor_uuid(value: str) -> uuid.UUID | None:
    """Parse an actor filter that may be a uuid or a free-text label."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None
