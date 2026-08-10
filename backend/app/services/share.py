"""Share-link rules.

The routes in `api/routers/shares.py` are thin; every decision about *whether* a
link may exist and *whether* it still works lives here, so both the owner-facing
and the anonymous path enforce the same thing.

Three refusals, three different answers, and the differences are deliberate:

* **Unknown or revoked -> 404.** Revoking a link is usually a response to it
  having leaked. A revoked link that answered "this used to work" would confirm
  to whoever leaked it that they had hold of something real, so revocation
  makes a link indistinguishable from one that never existed.
* **Expired -> 410 Gone.** The opposite case. Expiry is a scheduled ending, and
  the person holding the link was given it legitimately; telling them it aged
  out — and when — reveals nothing they did not already have, and is the
  difference between "ask for a new link" and "the app is broken".
* **Classification no longer permits it -> 403.** The report changed under the
  link. That is not a broken link and not a secret; it is a policy answer.

Classification is checked on **read**, not only on create. A report raised to
Confidential after a link was issued stops serving that link immediately —
which is the only version of "enforced server-side" that means anything, since
the link's holder never touches the UI that hides the button.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import share_token
from app.core.config import settings
from app.db import models
from app.schemas.report import FREELY_SHAREABLE
from app.schemas.share import ShareCreate

# Opening a link is a read. Writing `view_count` on every single one would turn
# it into a write and serialise concurrent readers on one row for a number
# nobody reads to the unit. A minute of resolution answers "is anyone using
# this link?" just as well.
VIEW_RESOLUTION = timedelta(minutes=1)


class ShareError(Exception):
    """Base for the three ways a share link can be refused."""


class ShareNotFound(ShareError):
    """No such link, or it was revoked. The two are answered identically."""


class ShareExpired(ShareError):
    """The link was valid and has passed its expiry."""

    def __init__(self, expires_at: datetime) -> None:
        super().__init__(f"this share link expired on {expires_at.isoformat()}")
        self.expires_at = expires_at


class ShareForbidden(ShareError):
    """The report's current classification does not permit link sharing."""


def requires_override(classification: str) -> bool:
    """True when sharing this classification needs a recorded justification."""
    return classification not in FREELY_SHAREABLE


def share_url(token: str) -> str:
    return f"{settings.share_base_url.rstrip('/')}/share/{token}"


def is_active(share: models.ReportShare, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if share.revoked:
        return False
    return share.expires_at is None or share.expires_at > now


def create_share(
    db: Session,
    *,
    report: models.Report,
    creator: models.Users,
    request: ShareCreate,
) -> tuple[models.ReportShare, str]:
    """Mint a link for `report`. Commits. Returns the row and the clear token.

    Raises `ShareForbidden` when the report is classified above what a link may
    carry and no justification was supplied. The justification *is* the
    override: there is no separate boolean, because a checkbox records that
    somebody clicked and a sentence records that somebody decided.
    """
    justification = (request.justification or "").strip() or None

    if requires_override(report.classification) and justification is None:
        raise ShareForbidden(
            f"a {report.classification} report can only be shared with a written "
            "justification, which is recorded against the link and raises an alert"
        )

    generated = share_token.generate_token()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=request.expires_in_hours)
        if request.expires_in_hours is not None
        else None
    )

    share = models.ReportShare(
        report_id=report.report_id,
        created_by=creator.user_id,
        prefix=generated.prefix,
        token_hash=generated.token_hash,
        label=request.label,
        expires_at=expires_at,
        classification_at_share=report.classification,
        # Only recorded when it was actually needed. Storing a justification
        # against an Internal link would make the audit trail read as though an
        # override had been taken when none was.
        override_justification=justification if requires_override(report.classification) else None,
    )
    db.add(share)

    if share.override_justification:
        # An override that lives only in a column nobody queries is not
        # oversight. The alerts table is the one place in this app where "look
        # at this" is already the contract, so the override lands there — owned
        # by the report's owner, like every other alert.
        db.add(
            models.SecurityAlert(
                severity="medium",
                source="share-link",
                message=(
                    f"{report.classification} report '{report.report_name}' was shared "
                    f"by a read-only link created by {creator.email}. "
                    f"Justification: {share.override_justification}"
                ),
                report_id=report.report_id,
                user_id=report.user_id,
            )
        )

    db.commit()
    db.refresh(share)
    return share, generated.token


def list_shares(db: Session, report_id: uuid.UUID) -> list[models.ReportShare]:
    return list(
        db.scalars(
            select(models.ReportShare)
            .where(models.ReportShare.report_id == report_id)
            .order_by(models.ReportShare.created_at.desc())
        ).all()
    )


def revoke_share(db: Session, share: models.ReportShare) -> models.ReportShare:
    """Retire a link. Idempotent — revoking twice is not an error."""
    if not share.revoked:
        share.revoked = True
        share.revoked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(share)
    return share


def resolve_share(db: Session, token: str) -> models.ReportShare:
    """Turn a clear token into its share row, or raise.

    This is the whole of the access control on the public routes, so every
    check that matters happens here and nowhere else.
    """
    prefix = share_token.extract_prefix(token)
    share = (
        db.scalar(select(models.ReportShare).where(models.ReportShare.prefix == prefix))
        if prefix
        else None
    )

    if share is None or not share_token.verify_token(token, share.token_hash):
        raise ShareNotFound("share link not found")
    if share.revoked:
        # Same exception as "no such link", by design. See the module docstring.
        raise ShareNotFound("share link not found")

    now = datetime.now(timezone.utc)
    if share.expires_at is not None and share.expires_at <= now:
        raise ShareExpired(share.expires_at)

    report = share.report
    if report is None:
        raise ShareNotFound("share link not found")

    # The classification the report carries *now*, not the one it carried when
    # the link was issued. A link created while the report was Internal must
    # stop working the moment somebody classifies it Confidential.
    if requires_override(report.classification) and not share.override_justification:
        raise ShareForbidden(
            f"this report is now classified {report.classification} and is no longer "
            "available by link"
        )

    if share.last_viewed_at is None or now - share.last_viewed_at > VIEW_RESOLUTION:
        share.view_count += 1
        share.last_viewed_at = now
        db.commit()

    return share
