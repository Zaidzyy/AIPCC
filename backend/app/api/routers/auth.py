"""Authentication: login, logout, self-registration, profile.

Login carries the two brute-force controls described in
`services/ratelimit.py` — a hard per-IP lockout and a per-account progressive
delay that is deliberately never a lock — and writes the log entries that make
a spray visible after the fact.

The ordering in `login` is the whole of it, and it is not arbitrary:

1. the IP lockout is checked *first*, so a locked-out address never reaches
   bcrypt and cannot be used to burn CPU;
2. the attempt is recorded and the audit row committed *before* the 401 is
   raised, because a route that raises never commits and a failure recorded
   only on the success path is not recorded;
3. the per-account delay is applied last, after the failure is already durable,
   so an attacker who hangs up mid-sleep has still been counted.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db import models
from app.db.session import get_db
from app.schemas.auth import PasswordChange, Token, UserCreate, UserPublic
from app.services import audit, ratelimit

router = APIRouter(prefix="/auth", tags=["auth"])

# Deliberately identical for "no such email" and "wrong password" so the
# endpoint cannot be used to enumerate registered addresses.
_BAD_CREDENTIALS = "incorrect email or password"


def _find_by_email(db: Session, email: str) -> models.Users | None:
    return db.scalar(
        select(models.Users).where(func.lower(models.Users.email) == email.lower())
    )


@router.post("/login", response_model=Token)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    """OAuth2 password flow. `username` is the user's email."""
    ip = ratelimit.client_ip(request)
    account = ratelimit.account_key(form.username)

    try:
        ratelimit.enforce(
            db,
            scope=ratelimit.IP,
            identifier=ip,
            action=ratelimit.LOGIN,
            quota=ratelimit.login_ip_quota(),
        )
    except HTTPException:
        # A locked-out address is worth a log line of its own. "Blocked" and
        # "failed" are different events: a run of failures is somebody
        # guessing, and a run of blocks is the control doing its job — and if
        # the blocks belong to a real user, it is the control doing harm.
        audit.record(
            db,
            action=audit.LOGIN_BLOCKED,
            outcome=audit.BLOCKED,
            request=request,
            actor_label=account,
            detail={"reason": "ip lockout"},
        )
        raise

    user = _find_by_email(db, form.username)

    # Verify even when the user is missing, so a wrong email and a wrong
    # password take comparable time and cannot be told apart by latency.
    stored_hash = user.password_hash if user else _DUMMY_HASH
    password_ok = verify_password(form.password, stored_hash)

    if user is None or not password_ok:
        _record_failure(db, request, ip=ip, account=account, user=user)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            _BAD_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.status.lower() != "active":
        # Counted as a failure: otherwise a disabled account is an unlimited
        # oracle for testing passwords with no rate limit attached to it.
        _record_failure(db, request, ip=ip, account=account, user=user, reason=user.status)
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"account is {user.status}")

    ratelimit.record(
        db, scope=ratelimit.ACCOUNT, identifier=account, action=ratelimit.LOGIN, successful=True
    )
    ratelimit.record(
        db, scope=ratelimit.IP, identifier=ip, action=ratelimit.LOGIN, successful=True
    )

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    audit.record(db, action=audit.LOGIN_SUCCESS, request=request, actor=user)

    return Token(
        access_token=create_access_token(user.user_id, user.role),
        expires_in=settings.access_token_expire_minutes * 60,
    )


def _record_failure(
    db: Session,
    request: Request,
    *,
    ip: str,
    account: str,
    user: models.Users | None,
    reason: str | None = None,
) -> None:
    """Persist a failed attempt, log it, then apply the account delay.

    Everything durable happens before the sleep. A client that disconnects
    during the delay has still spent the attempt — otherwise the backoff would
    be trivially defeated by not waiting for the answer.

    The delay is keyed on the account and applied even when the account does
    not exist, using the attempted address as the key. Skipping it for unknown
    addresses would turn the delay itself into an account-enumeration oracle:
    fast means "no such user", slow means "that one is real".
    """
    for scope, identifier in ((ratelimit.IP, ip), (ratelimit.ACCOUNT, account)):
        ratelimit.record(
            db, scope=scope, identifier=identifier, action=ratelimit.LOGIN, successful=False
        )

    audit.record(
        db,
        action=audit.LOGIN_FAILURE,
        outcome=audit.FAILURE,
        request=request,
        # **The account is the target, never the actor.** Nobody proved they
        # were this user — that is what "failed login" means — so recording
        # `actor_id = <that user>` would say in the log that the user did this,
        # when the truth is that somebody tried to be them. The attempted
        # address goes in `actor_label`, which is what a spray looks like when
        # you read down the column, and the resolved account (if any) goes in
        # the target, which is what "attempts against this user" filters on.
        actor=None,
        actor_label=account,
        target_type="user" if user else None,
        target_id=user.user_id if user else None,
        detail={"reason": reason or "bad credentials", "known_account": user is not None},
    )

    failures = ratelimit.consecutive_failures(
        db, identifier=account, action=ratelimit.LOGIN
    )
    delay = ratelimit.account_delay(failures)
    if delay:
        time.sleep(delay)


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Record that a session ended.

    It does **not** invalidate the token, and pretending otherwise would be the
    kind of claim CLAUDE.md's LLM policy forbids elsewhere for the same reason:
    access tokens here are stateless JWTs, so one stays valid until it expires
    no matter what this route does. Revoking them would need a deny-list keyed
    on jti, checked on every request — a real feature with a real cost, not
    something to imply with an endpoint that returns 204.

    What it is for is the audit trail. "This account signed out at 14:02" is
    the line that makes "and acted at 14:40" worth investigating.
    """
    audit.record(db, action=audit.LOGOUT, request=request, actor=user)


@router.post("/register", response_model=UserPublic, status_code=201)
def register(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> UserPublic:
    """Self-registration. Always creates a non-privileged account.

    Roles are never taken from the request body — see users.py for the
    admin-only path that can set one.

    Rate-limited per source address and counting *every* attempt rather than
    only the failures: the abuse here is successful registration in bulk, so
    limiting failures would limit the one case nobody minds.
    """
    ip = ratelimit.client_ip(request)
    ratelimit.enforce(
        db,
        scope=ratelimit.IP,
        identifier=ip,
        action=ratelimit.REGISTER,
        quota=ratelimit.register_ip_quota(),
    )
    ratelimit.record(
        db, scope=ratelimit.IP, identifier=ip, action=ratelimit.REGISTER, successful=True
    )

    if _find_by_email(db, payload.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "email is already registered")

    user = models.Users(
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        role="analyst",
        status="Active",
        phone_number=payload.phone_number,
        password_hash=hash_password(payload.password),
        organization=payload.organization,
        location=payload.location,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    audit.record(
        db,
        action=audit.REGISTER,
        request=request,
        actor=user,
        target_type="user",
        target_id=user.user_id,
        detail={"role": user.role},
    )
    return UserPublic.model_validate(user)


@router.get("/me", response_model=UserPublic)
def read_me(user: models.Users = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(user)


@router.post("/change-password", status_code=204)
def change_password(
    payload: PasswordChange,
    request: Request,
    user: models.Users = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Change your own password.

    A hard lockout is safe here, unlike on login: reaching this route at all
    requires a valid session for this exact account, so only the account holder
    — or somebody who already has their token — can spend the budget. Nobody
    can lock a stranger out of changing their password.
    """
    account = ratelimit.account_key(user.email)
    quota = ratelimit.password_change_quota()
    ratelimit.enforce(
        db,
        scope=ratelimit.ACCOUNT,
        identifier=account,
        action=ratelimit.PASSWORD_CHANGE,
        quota=quota,
    )

    if not verify_password(payload.current_password, user.password_hash):
        ratelimit.record(
            db,
            scope=ratelimit.ACCOUNT,
            identifier=account,
            action=ratelimit.PASSWORD_CHANGE,
            successful=False,
        )
        audit.record(
            db,
            action=audit.PASSWORD_CHANGE,
            outcome=audit.FAILURE,
            request=request,
            actor=user,
            detail={"reason": "current password incorrect"},
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "current password is incorrect")

    user.password_hash = hash_password(payload.new_password)
    db.commit()

    ratelimit.record(
        db,
        scope=ratelimit.ACCOUNT,
        identifier=account,
        action=ratelimit.PASSWORD_CHANGE,
        successful=True,
    )
    audit.record(db, action=audit.PASSWORD_CHANGE, request=request, actor=user)


# A real bcrypt hash of a random string, compared against when the email is
# unknown so that path does the same work as a genuine verification.
_DUMMY_HASH = hash_password("not-a-real-password-placeholder")
