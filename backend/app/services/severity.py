"""The severity ladder, defined once.

`risk_level` is free text produced by an LLM. The prompts ask for
Low/Medium/High/Critical and the field is nullable, so "Severe", "Med.",
"CRITICAL " and nothing at all all turn up in real data. Folding those into one
ladder is the only way a count means anything.

That fold had been written twice — as a SQL `CASE` in `analytics.py` for the
dashboard, and as prefix tests in `frontend/src/lib/format.js` for the UI. A
third copy for the exporter would have been the point where they drift, so the
prefix table lives here and `analytics.severity_bucket` now *builds its SQL
from it*. Two runtimes, one definition. The JavaScript copy stays a copy — it
runs in a browser and cannot import this — but it is now the only one.
"""

from __future__ import annotations

# Ordered low → critical, so a stacked chart reads bottom-up in severity order.
SEVERITY_ORDER: tuple[str, ...] = ("unknown", "low", "medium", "high", "critical")

# First match wins, so order matters. Prefix rather than equality: "Critical.",
# "critical risk" and "CRITICAL" are the same finding, and refusing to see that
# understates the number these counts exist to show.
SEVERITY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("crit", "critical"),
    ("sev", "critical"),
    ("high", "high"),
    ("med", "medium"),
    ("mod", "medium"),
    ("low", "low"),
    ("info", "low"),
)

UNKNOWN = "unknown"


def bucket(value: object) -> str:
    """Fold one free-text severity into the ladder."""
    if value is None:
        return UNKNOWN
    text = str(value).strip().lower()
    for prefix, name in SEVERITY_PREFIXES:
        if text.startswith(prefix):
            return name
    return UNKNOWN


def counts(items: list, field: str = "risk_level") -> dict[str, int]:
    """Tally a list of findings by severity, every bucket present.

    Absent buckets are zeros rather than missing keys: a caller rendering a
    tally should show "Critical 0", not omit the row and leave the reader to
    work out whether it was zero or unmeasured.
    """
    tally = dict.fromkeys(SEVERITY_ORDER, 0)
    for item in items or []:
        value = getattr(item, field, None) if not isinstance(item, dict) else item.get(field)
        tally[bucket(value)] += 1
    return tally
