"""Security alert schemas.

Alerts come from two directions — an n8n workflow posting to
`POST /api/security/alert`, and (later) the app itself — so the create schema
is forgiving about *shape* while staying strict about *meaning*: severity is
normalised to the app's ladder on the way in, because the dashboard counts by
it and a bucket called "CRITICAL" that is separate from "critical" is a bug.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

AlertStatus = Literal["open", "resolved"]

# The same ladder as `lib/format.js` and `services/analytics.severity_bucket`.
SEVERITIES = ("low", "medium", "high", "critical")


def _normalize_severity(value: object) -> object:
    """Fold free text onto the ladder.

    The FIM workflow sends "CRITICAL"; a person might send "Sev 1". Both mean
    the same thing and must land in the same bucket. Anything unrecognisable
    becomes "medium" rather than being rejected — refusing an alert because its
    severity was spelled oddly loses the alert, which is worse than filing it
    one notch off.
    """
    if not isinstance(value, str):
        return value
    text = value.strip().lower()
    if text in SEVERITIES:
        return text
    if text.startswith(("crit", "sev")):
        return "critical"
    if text.startswith("high"):
        return "high"
    if text.startswith(("med", "mod")):
        return "medium"
    if text.startswith(("low", "info")):
        return "low"
    return "medium"


Severity = Annotated[str, BeforeValidator(_normalize_severity)]


class AlertCreate(BaseModel):
    """Body of POST /api/security/alert."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    message: str = Field(min_length=1)
    # Which workflow or subsystem raised this. "Who is telling me?" is the
    # first question an analyst asks about an alert they did not expect.
    source: str = Field(default="n8n", max_length=120)
    severity: Severity = "medium"
    report_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None


class AlertUpdate(BaseModel):
    status: AlertStatus


class Alert(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alert_id: uuid.UUID
    severity: str
    source: str
    message: str
    status: str
    report_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    user_id: uuid.UUID
    created_at: datetime | None = None
    resolved_at: datetime | None = None
