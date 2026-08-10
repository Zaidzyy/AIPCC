"""Authentication rate limiting.

**Two controls, because there are two attacks.**

*Per source IP — a hard lockout.* Five failures in fifteen minutes and that
address gets 429 until the oldest of them ages out. This is the control that
actually stops a flood: one host cannot get past five guesses.

*Per account — a progressive delay, and never a lock.* A per-account lockout is
the textbook answer and it is a trap: it hands anyone a one-request denial of
service against any address they can guess, which trades one vulnerability for
another. So the account side sleeps instead — 2s, 4s, 8s — and the account
stays answerable to the person who actually knows the password. It exists to
blunt a *distributed* spray, where every request comes from a fresh address and
the per-IP counter never fills.

**Where the state lives.** Postgres, in `auth_attempts`. In-process memory is
wrong the moment there is a second worker — each replica would get its own
counter, so N replicas mean N times the allowed attempts, and a restart clears
it. Redis is the conventional answer and would be O(1) with a native TTL, but
it is a fifth container and a hard dependency that forces a fail-open /
fail-closed decision on the login path. The honest cost of the Postgres choice:
one write and one indexed count per authentication attempt, and no automatic
expiry — `python -m app.db.prune` handles that. At authentication volume this
is nothing. It would be the wrong choice for a per-request API limiter.

**Fail-closed.** If the counting query raises, the request is refused rather
than allowed. A limiter that disappears when the database is unhappy is a
limiter an attacker can remove by making the database unhappy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models

# --- Vocabulary -----------------------------------------------------------

IP = "ip"
ACCOUNT = "account"

LOGIN = "login"
REGISTER = "register"
PASSWORD_CHANGE = "password_change"
SHARE = "share"

_TOO_MANY = "too many attempts; try again later"


@dataclass(frozen=True)
class Quota:
    """A sliding window: at most `limit` matching rows within `period`."""

    limit: int
    period: timedelta
    # Login and password change count only failures — a successful login must
    # not spend the budget of the person who knows their password. Register and
    # share count every attempt, because there is no "failure" to key on.
    failures_only: bool = True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def login_ip_quota() -> Quota:
    return Quota(
        limit=settings.login_ip_max_failures,
        period=timedelta(minutes=settings.login_ip_window_minutes),
    )


def register_ip_quota() -> Quota:
    return Quota(
        limit=settings.register_ip_max_per_hour,
        period=timedelta(hours=1),
        failures_only=False,
    )


def password_change_quota() -> Quota:
    return Quota(
        limit=settings.password_change_max_failures,
        period=timedelta(minutes=settings.password_change_window_minutes),
    )


def share_ip_quota() -> Quota:
    return Quota(
        limit=settings.share_ip_max_per_minute,
        period=timedelta(minutes=1),
        failures_only=False,
    )


# --- Client identity ------------------------------------------------------


def client_ip(request: Request) -> str:
    """The address a per-IP limit is keyed on.

    `X-Forwarded-For` is ignored unless `TRUST_PROXY_HEADER` says something in
    front of this app overwrites it. The header is caller-supplied: trusting it
    with no such proxy turns the lockout into one keyed on a string the
    attacker picks — no lockout at all — and simultaneously lets anyone lock
    out somebody else's address by claiming it. Being wrong in the other
    direction (everyone behind one proxy shares a counter) is a usability
    problem; being wrong in this direction is the absence of the feature.
    """
    if settings.trust_proxy_header:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded.strip():
            return forwarded.split(",")[0].strip()[:64]
    return request.client.host[:64] if request.client else "unknown"


def account_key(email: str) -> str:
    """Accounts are keyed case-insensitively, as `_find_by_email` looks them up."""
    return email.strip().lower()[:255]


# --- Recording and counting -----------------------------------------------


def record(
    db: Session,
    *,
    scope: str,
    identifier: str,
    action: str,
    successful: bool,
) -> None:
    """Persist one attempt.

    Committed immediately. A failure that is only recorded if the surrounding
    request goes on to succeed is not recorded at all — and the request this
    matters most for is the one that raises 401 straight afterwards.
    """
    if not settings.rate_limit_enabled or not identifier:
        return
    db.add(
        models.AuthAttempt(
            scope=scope,
            identifier=identifier[:255],
            action=action,
            successful=successful,
            at=_now(),
        )
    )
    db.commit()


def _conditions(scope: str, identifier: str, action: str, quota: Quota, since: datetime):
    conditions = [
        models.AuthAttempt.scope == scope,
        models.AuthAttempt.identifier == identifier,
        models.AuthAttempt.action == action,
        models.AuthAttempt.at >= since,
    ]
    if quota.failures_only:
        conditions.append(models.AuthAttempt.successful.is_(False))
    return conditions


def enforce(
    db: Session,
    *,
    scope: str,
    identifier: str,
    action: str,
    quota: Quota,
) -> None:
    """Raise 429 when `identifier` has spent its window.

    One query, not two: the count and the oldest timestamp are read together,
    because between two round trips the window can move and produce a
    `Retry-After` for an attempt that has already aged out.

    That `Retry-After` counts from the *oldest* attempt still inside the
    window, which is the moment the count first drops below the limit.
    Reporting the whole period instead would tell a locked-out user to wait
    longer than they actually have to.
    """
    if not settings.rate_limit_enabled or not identifier:
        return

    now = _now()
    conditions = _conditions(scope, identifier, action, quota, now - quota.period)

    count, oldest = db.execute(
        select(func.count(), func.min(models.AuthAttempt.at))
        .select_from(models.AuthAttempt)
        .where(*conditions)
    ).one()

    if (count or 0) < quota.limit:
        return

    seconds = (
        (oldest + quota.period - now).total_seconds()
        if oldest is not None
        else quota.period.total_seconds()
    )
    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        _TOO_MANY,
        headers={"Retry-After": str(max(1, math.ceil(seconds)))},
    )


def consecutive_failures(db: Session, *, identifier: str, action: str) -> int:
    """Failures for this account since its last success.

    Counting since the last success rather than over a fixed window is what
    makes the delay reset when the real user signs in: the person who knows the
    password is not made to wait for a spray that targeted them an hour ago.
    """
    if not identifier:
        return 0

    last_success = db.scalar(
        select(func.max(models.AuthAttempt.at)).where(
            models.AuthAttempt.scope == ACCOUNT,
            models.AuthAttempt.identifier == identifier,
            models.AuthAttempt.action == action,
            models.AuthAttempt.successful.is_(True),
        )
    )

    statement = (
        select(func.count())
        .select_from(models.AuthAttempt)
        .where(
            models.AuthAttempt.scope == ACCOUNT,
            models.AuthAttempt.identifier == identifier,
            models.AuthAttempt.action == action,
            models.AuthAttempt.successful.is_(False),
        )
    )
    if last_success is not None:
        statement = statement.where(models.AuthAttempt.at > last_success)
    return db.scalar(statement) or 0


def account_delay(failures: int) -> float:
    """Seconds to wait before answering, given consecutive failures.

    Exponential from the threshold and hard-capped. The cap is not cosmetic:
    a delayed login holds one threadpool thread for its duration, so an
    unbounded backoff would be a denial of service we inflicted on ourselves.
    The per-IP lockout is what keeps the number of concurrently-sleeping
    requests small — a single address is cut off after five.
    """
    if not settings.rate_limit_enabled:
        return 0.0
    over = failures - settings.login_delay_after_failures
    if over <= 0:
        return 0.0
    return float(min(2.0**over, settings.login_delay_max_seconds))


def prune(db: Session, *, older_than: timedelta | None = None) -> int:
    """Delete attempt rows past their usefulness. Returns the number removed.

    Only ever called against `auth_attempts`. The audit log has no equivalent
    and cannot acquire one — a Postgres trigger refuses DELETE on that table.
    """
    # `is None`, not `or`. A zero timedelta is falsy, so `older_than=timedelta(0)`
    # — which is exactly what `--days 0` produces, and the only way to clear the
    # table — silently fell back to the 30-day default and reported "pruned 0".
    period = (
        older_than
        if older_than is not None
        else timedelta(days=settings.auth_attempt_retention_days)
    )
    cutoff = _now() - period
    result = db.execute(delete(models.AuthAttempt).where(models.AuthAttempt.at < cutoff))
    db.commit()
    return result.rowcount or 0
