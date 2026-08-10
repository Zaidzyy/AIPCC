"""What an exported report *contains*, independent of file format.

The DOCX and the PDF are built from the same `Layout`, produced once by
`build_layout`. Neither renderer reads a `ReportSections` object and neither
knows a field name: they walk headings, labelled paragraphs and table rows. So
the two files cannot disagree about content — only about typography — and a new
report field is added in one place rather than two.

Two rendering shapes, chosen per section by the shape of the data:

* **Findings** for the narrative sections (attack types, risk assessment,
  vulnerabilities). Their fields are paragraphs of prose; a six-column table of
  paragraphs is unreadable on paper at any width.
* **Tables** for the enumerative sections (anomalies, timeline, threat intel),
  whose fields are short and whose value is in the comparison down the column.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.schemas.report import ReportDetail, ReportSections, ThreatIntelItem
from app.schemas.share import SharedReport
from app.services.severity import SEVERITY_ORDER, bucket, counts

DASH = "—"

SEVERITY_LABELS = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "unknown": "Unrated",
}

# Critical first. A tally is read top-down looking for the worst thing in it.
TALLY_ORDER = tuple(reversed(SEVERITY_ORDER))


@dataclass(frozen=True)
class ExportSource:
    """Everything an export may show about one report.

    Deliberately not a `ReportDetail`. The share path builds one of these too,
    and it does so by *omission*: `file_hash` and `reference` are left null so a
    link recipient cannot be handed the sealed hash or an internal identifier
    just because they asked for the PDF instead of the web page. If the
    exporter read `ReportDetail` directly, the shared export would have to
    remember to strip fields, and the next field added would leak by default.
    """

    report_name: str
    classification: str
    status: str
    generated_at: datetime | None
    document_name: str | None
    integrity_state: str
    integrity_checked_at: datetime | None
    sections: ReportSections
    threat_intel: list[ThreatIntelItem] = field(default_factory=list)
    file_hash: str | None = None
    reference: str | None = None
    # Printed under the title on the shared copy. A document that leaves the
    # building should say on its face that it did.
    provenance: str | None = None


@dataclass(frozen=True)
class Finding:
    heading: str
    subtitle: str | None
    severity: str | None
    fields: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Section:
    title: str
    caption: str
    empty_note: str
    findings: tuple[Finding, ...] = ()
    columns: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    # Relative column widths, same length as `columns`.
    weights: tuple[float, ...] = ()

    @property
    def is_table(self) -> bool:
        return bool(self.columns)

    @property
    def count(self) -> int:
        return len(self.rows) if self.is_table else len(self.findings)


@dataclass(frozen=True)
class Layout:
    title: str
    classification: str
    provenance: str | None
    meta: tuple[tuple[str, str], ...]
    tally: tuple[tuple[str, int], ...]
    totals: tuple[tuple[str, int], ...]
    sections: tuple[Section, ...]
    filename_stem: str


# --- Section definitions --------------------------------------------------
# (label, attribute) pairs. Order here is the order on the page.

_ATTACK_FIELDS = (
    ("Description", "attack_description"),
    ("Risk", "risk_name"),
    ("Assessment", "risk_description"),
    ("Impact", "impact"),
    ("Likelihood", "likelihood"),
    ("Mitigation", "mitigation"),
)

_RISK_FIELDS = (
    ("Assessment", "risk_description"),
    ("Impact", "impact"),
    ("Likelihood", "likelihood"),
    ("Mitigation", "mitigation"),
)

_VULN_FIELDS = (
    ("Description", "vulnerability_description"),
    ("CVE", "cve_description"),
    ("CWE", "cwe_description"),
)


def build_layout(source: ExportSource) -> Layout:
    """Turn a report into the format-independent document."""
    sections = source.sections
    risks = [*sections.attack_types, *sections.general_risk_assessment]

    return Layout(
        title=source.report_name,
        classification=source.classification,
        provenance=source.provenance,
        meta=_meta(source),
        tally=tuple(
            (SEVERITY_LABELS[key], counts(risks)[key]) for key in TALLY_ORDER
        ),
        totals=(
            ("Attack types", len(sections.attack_types)),
            ("Risk assessments", len(sections.general_risk_assessment)),
            ("Vulnerabilities", len(sections.vulnerabilities)),
            ("Anomalies", len(sections.anomalies)),
            ("Timeline events", len(sections.timeline)),
            ("Enriched indicators", len(source.threat_intel)),
        ),
        sections=(
            _attack_types(sections),
            _risk_assessment(sections),
            _vulnerabilities(sections),
            _anomalies(sections),
            _timeline(sections),
            _threat_intel(source.threat_intel),
        ),
        filename_stem=_filename_stem(source),
    )


def _meta(source: ExportSource) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = [
        ("Source document", source.document_name or "not recorded"),
        ("Generated", _timestamp(source.generated_at)),
        ("Generation status", _status_label(source.status)),
        ("Source integrity", _integrity_label(source)),
    ]
    if source.reference:
        rows.insert(0, ("Reference", source.reference))
    if source.file_hash:
        rows.append(("Sealed SHA-256", source.file_hash))
    return tuple(rows)


_STATUS_LABELS = {
    "complete": "Complete — every section was generated",
    "partial": "Partial — one or more sections could not be generated",
    "failed": "Failed — no section could be generated",
    "pending": "Pending",
    "generating": "Generating",
}


def _status_label(status: str) -> str:
    return _STATUS_LABELS.get(str(status).lower(), str(status))


def _integrity_label(source: ExportSource) -> str:
    """Say what was checked and when, never just a colour word.

    UNKNOWN is spelled out as the absence of a check rather than shortened to
    "Unverified", because on paper there is no grey badge to carry the meaning.
    """
    checked = source.integrity_checked_at
    state = str(source.integrity_state or "UNKNOWN").upper()
    if state == "SEALED":
        return f"Sealed — the source log still matches its recorded hash (checked {_timestamp(checked)})"
    if state == "TAMPERED":
        return f"TAMPERED — the source log no longer matches its recorded hash (checked {_timestamp(checked)})"
    return "Not verified — the source log has not been checked since this report was generated"


def _attack_types(sections: ReportSections) -> Section:
    return Section(
        title="Attack types",
        caption="Techniques identified in the source log, mapped to MITRE ATT&CK.",
        empty_note="No attack techniques were identified in this log.",
        findings=tuple(
            Finding(
                heading=_text(item.attack_name) or "Unnamed technique",
                subtitle=_join(
                    " ",
                    _text(item.attack_mitre_technique_id),
                    _text(item.attack_mitre_technique_name),
                ),
                severity=bucket(item.risk_level),
                fields=_fields(item, _ATTACK_FIELDS),
            )
            for item in sections.attack_types
        ),
    )


def _risk_assessment(sections: ReportSections) -> Section:
    return Section(
        title="Risk assessment",
        caption="Risks arising from the activity above, independent of any one technique.",
        empty_note="No general risks were assessed for this log.",
        findings=tuple(
            Finding(
                heading=_text(item.risk_name) or "Unnamed risk",
                subtitle=None,
                severity=bucket(item.risk_level),
                fields=_fields(item, _RISK_FIELDS),
            )
            for item in sections.general_risk_assessment
        ),
    )


def _vulnerabilities(sections: ReportSections) -> Section:
    return Section(
        title="Vulnerabilities",
        caption="Weaknesses the log evidences, with CVE and CWE references where identified.",
        empty_note="No vulnerabilities were identified in this log.",
        findings=tuple(
            Finding(
                heading=_text(item.vulnerability_name) or "Unnamed vulnerability",
                subtitle=_join(
                    "  ·  ", _text(item.cve_id), _text(item.cwe_id)
                ),
                severity=None,
                fields=_fields(item, _VULN_FIELDS),
            )
            for item in sections.vulnerabilities
        ),
    )


def _anomalies(sections: ReportSections) -> Section:
    return Section(
        title="Anomalies",
        caption="Activity that stands out from the rest of the log.",
        empty_note="No anomalies were identified in this log.",
        columns=("Anomaly", "Principal", "Source → destination", "Proto", "Count", "Window"),
        # "Count" needs enough room not to wrap its own heading onto two lines.
        weights=(2.4, 1.7, 2.4, 0.8, 0.95, 2.05),
        rows=tuple(
            (
                _cell(item.anomaly_name) or _cell(item.anomaly_id),
                _cell(_join(" / ", _text(item.user_name), _text(item.user_id))),
                _cell(_join(" → ", _text(item.source_ip), _text(item.destination_ip))),
                _cell(item.protocol),
                _cell(item.counted),
                _cell(_join(" – ", _text(item.first_occurrence), _text(item.last_occurrence))),
            )
            for item in sections.anomalies
        ),
    )


def _timeline(sections: ReportSections) -> Section:
    return Section(
        title="Timeline",
        caption="The sequence of events reconstructed from the log.",
        empty_note="No timeline could be reconstructed from this log.",
        columns=("Timestamp", "Event", "Entity", "Duration"),
        weights=(2.0, 3.6, 2.4, 1.2),
        rows=tuple(
            (
                _cell(item.time_stamp),
                _cell(item.event_name),
                _cell(item.entity),
                _cell(item.duration),
            )
            for item in sections.timeline
        ),
    )


def _threat_intel(indicators: list[ThreatIntelItem]) -> Section:
    return Section(
        title="Threat intelligence",
        caption="Reputation for indicators observed in the log, as returned by external providers.",
        empty_note="No indicators from this log were enriched.",
        columns=("Indicator", "Type", "Source", "Score", "Risk", "Country"),
        weights=(3.0, 1.0, 1.4, 0.9, 1.3, 1.0),
        rows=tuple(
            (
                _cell(item.indicator),
                _cell(item.indicator_type),
                _cell(item.source),
                _cell(item.reputation_score),
                _cell(item.risk_level),
                _cell(item.country),
            )
            for item in indicators
        ),
    )


# --- Value handling -------------------------------------------------------


def _fields(item: object, spec: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    """Label/value pairs, dropping the ones the model left null.

    An omitted field is better than a page of "—": on screen a dash sits in a
    dense grid and reads as "nothing here", but printed as its own labelled
    paragraph it reads as a defect in the document.
    """
    resolved = []
    for label, attribute in spec:
        value = _text(getattr(item, attribute, None))
        if value:
            resolved.append((label, value))
    return tuple(resolved)


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _cell(value: object) -> str:
    """A table cell. Null becomes an em dash, never the string "None"."""
    return _text(value) or DASH


def _join(separator: str, *parts: str | None) -> str | None:
    present = [part for part in parts if part]
    return separator.join(present) if present else None


def _timestamp(value: datetime | None) -> str:
    if value is None:
        return "never"
    return value.strftime("%d %b %Y, %H:%M UTC")


_SLUG = re.compile(r"[^A-Za-z0-9]+")


def _filename_stem(source: ExportSource) -> str:
    """A filename that survives every filesystem and every mail client."""
    slug = _SLUG.sub("-", source.report_name).strip("-").lower()[:60]
    stamp = (source.generated_at or datetime.now()).strftime("%Y%m%d")
    return f"{slug or 'security-report'}-{stamp}"


# --- Adapters -------------------------------------------------------------


def source_from_detail(detail: ReportDetail, *, document_name: str | None) -> ExportSource:
    """The owner's export: everything the Report Detail page shows."""
    return ExportSource(
        report_name=detail.report_name,
        classification=detail.classification,
        status=detail.status,
        generated_at=detail.generated_at,
        document_name=document_name,
        integrity_state=detail.integrity_state,
        integrity_checked_at=detail.integrity_checked_at,
        sections=detail.sections,
        threat_intel=detail.threat_intel,
        file_hash=detail.file_hash,
        reference=str(detail.report_id),
    )


def source_from_shared(shared: SharedReport) -> ExportSource:
    """A link holder's export.

    `file_hash` and `reference` stay null — see `ExportSource`. `SharedReport`
    does not carry either one, so this cannot accidentally start including them.
    """
    return ExportSource(
        report_name=shared.report_name,
        classification=shared.classification,
        status=shared.status,
        generated_at=shared.generated_at,
        document_name=shared.document_name,
        integrity_state=shared.integrity_state,
        integrity_checked_at=shared.integrity_checked_at,
        sections=shared.sections,
        threat_intel=shared.threat_intel,
        provenance="Read-only copy, shared by link",
    )
