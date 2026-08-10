"""Share-link request and response shapes.

Two audiences, two schemas, and the split between them is the security boundary:

* `ShareLink` is what the **owner** sees — every share on their report, when it
  expires, how often it has been opened, why a Confidential override was taken.
* `SharedReport` is what an **anonymous link holder** sees. It is built by
  listing what may be exposed rather than by removing what may not, which is
  why it does not inherit from `ReportDetail`. Inheriting and deleting fields
  means the next field added to `ReportDetail` leaks by default; here it has to
  be added on purpose.

What `SharedReport` therefore never carries: `user_id`, the owner's name or
address, `document_id`, `report_id`, the sealed file hash, or any identifier
that could be walked to a second report.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.report import IntegrityState, ReportSections, ThreatIntelItem

# A link nobody bounds is a link that outlives the reason it was made. The
# default is a week; "never" stays available because a permanently published
# Public report is a real case, and it is one revoke away either way.
DEFAULT_EXPIRY_HOURS = 7 * 24
MAX_EXPIRY_HOURS = 365 * 24


class ShareCreate(BaseModel):
    """Body of POST /reports/{report_id}/shares."""

    # Null means "does not expire". Absent means the default window, so a client
    # that sends nothing gets a bounded link rather than a permanent one.
    expires_in_hours: int | None = Field(default=DEFAULT_EXPIRY_HOURS, ge=1, le=MAX_EXPIRY_HOURS)
    label: str | None = Field(default=None, max_length=120)
    # Required to share a Confidential report, and stored verbatim. Free text on
    # purpose: the point of an override is that a person took responsibility for
    # it in their own words, which a checkbox does not record.
    justification: str | None = Field(default=None, min_length=10, max_length=500)


class ShareLink(BaseModel):
    """One share, as its owner sees it."""

    model_config = ConfigDict(from_attributes=True)

    share_id: uuid.UUID
    report_id: uuid.UUID
    label: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    revoked: bool = False
    revoked_at: datetime | None = None
    last_viewed_at: datetime | None = None
    view_count: int = 0
    classification_at_share: str
    override_justification: str | None = None
    # Derived rather than stored: "is this link live right now" is a question
    # about the clock, and a stored answer would be wrong the moment it passed.
    active: bool = True


class ShareCreated(ShareLink):
    """The create response — the only time the token itself exists.

    `token` is never readable again: only its SHA-256 is stored. `url` is the
    assembled link, so the UI does not have to know how to build one.
    """

    token: str
    url: str


class SharedReport(BaseModel):
    """A report as an anonymous link holder sees it.

    Everything here is about the report; nothing here is about the account that
    owns it. `document_name` is included because a finding without its source
    is not reviewable, and the name of a log file the recipient was sent a
    report about is not a fact the link discloses for the first time.
    """

    report_name: str
    classification: str
    status: str
    generated_at: datetime | None = None
    document_name: str | None = None
    integrity_state: IntegrityState = "UNKNOWN"
    integrity_checked_at: datetime | None = None
    sections: ReportSections
    threat_intel: list[ThreatIntelItem] = Field(default_factory=list)
    # So the page can say when the link stops working rather than letting the
    # recipient discover it on the morning they need it.
    expires_at: datetime | None = None
