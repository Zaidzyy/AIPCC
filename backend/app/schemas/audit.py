"""Audit log API contract.

Every string field is `str` on the way out, never a constrained type. This is
the same asymmetry as `UserPublic.email` and `ReportSummary.classification`,
and here it matters more than anywhere else: the audit log is append-only, so a
row that a future validator would reject can never be corrected or removed. If
the response model rejected it, the whole listing would 500 — and the way to
fix that would be to relax the model, which is where we already are.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    audit_id: uuid.UUID
    at: datetime
    action: str
    outcome: str
    actor_type: str
    actor_id: uuid.UUID | None = None
    actor_label: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    source_ip: str | None = None
    correlation_id: str | None = None
    detail: dict | None = None


class AuditPage(BaseModel):
    """A page of entries plus the total, so the UI can say "50 of 1,284".

    Without the total a paginated view cannot distinguish "this is the end" from
    "the next page failed to load" — the same distinction between empty and
    failed that every list in this app is required to make.
    """

    items: list[AuditEntry]
    total: int
    limit: int
    offset: int


class AuditActor(BaseModel):
    actor_id: uuid.UUID | None = None
    actor_label: str | None = None


class AuditFilters(BaseModel):
    """The filter vocabulary, read from the log rather than hardcoded in the UI.

    `actions` is the closed list the code can emit; `actors` is who actually
    appears. Offering a filter that matches nothing is how a security view
    convinces someone that nothing happened.
    """

    actions: list[str]
    actors: list[AuditActor]
    outcomes: list[str]
