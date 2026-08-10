"""Report export to PDF and DOCX.

Split the way the code is: `build_layout` owns *what the document says*, so
content is asserted there once rather than twice through two file formats; the
renderers own *what kind of file comes out*, so they are asserted on structure.
Parsing prose back out of a PDF to check a sentence made it in would be testing
a PDF text-extraction library, not this code.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import datetime, timezone

import pytest

from app.schemas.report import (
    AnomalyItem,
    AttackTypeItem,
    ReportDetail,
    ReportSections,
    RiskAssessmentItem,
    ThreatIntelItem,
    TimelineItem,
    VulnerabilityItem,
)
from app.services import export
from app.services.export.layout import ExportSource, build_layout, source_from_detail
from app.services.severity import bucket, counts

PDF_MAGIC = b"%PDF-"
# Every OOXML file is a zip. `PK\x03\x04` is the local file header.
DOCX_MAGIC = b"PK\x03\x04"
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _sections(**overrides) -> ReportSections:
    base = {
        "attack_types": [
            AttackTypeItem(
                attack_name="Credential stuffing",
                attack_mitre_technique_id="T1110.004",
                attack_mitre_technique_name="Brute Force: Credential Stuffing",
                attack_description="812 failed authentications from one source.",
                risk_name="Account takeover",
                risk_level="Critical",
                impact="Full network access",
                likelihood="High",
                mitigation="Enforce MFA.",
            )
        ],
        "general_risk_assessment": [
            RiskAssessmentItem(risk_name="No lockout policy", risk_level="Sev 2")
        ],
        "vulnerabilities": [
            VulnerabilityItem(vulnerability_name="Outdated OpenSSH", cve_id="CVE-2024-6387")
        ],
        "anomalies": [
            AnomalyItem(anomaly_name="Off-hours login", source_ip="203.0.113.44", counted=17)
        ],
        "timeline": [TimelineItem(event_name="First failure", time_stamp="02:11")],
    }
    base.update(overrides)
    return ReportSections(**base)


def _source(**overrides) -> ExportSource:
    base = {
        "report_name": "Q3 Perimeter Log Review",
        "classification": "Confidential",
        "status": "partial",
        "generated_at": datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc),
        "document_name": "vpn-auth.csv",
        "integrity_state": "SEALED",
        "integrity_checked_at": datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc),
        "sections": _sections(),
        "reference": str(uuid.uuid4()),
        "file_hash": "a" * 64,
    }
    base.update(overrides)
    return ExportSource(**base)


class TestLayout:
    def test_every_section_is_present_even_when_empty(self):
        layout = build_layout(_source(sections=ReportSections()))
        titles = [section.title for section in layout.sections]
        assert titles == [
            "Attack types",
            "Risk assessment",
            "Vulnerabilities",
            "Anomalies",
            "Timeline",
            "Threat intelligence",
        ]
        # An absent section would read as a rendering failure. A section that
        # says why it is empty reads as a finding.
        assert all(section.count == 0 for section in layout.sections)
        assert all(section.empty_note for section in layout.sections)

    def test_severity_tally_folds_free_text(self):
        """"Sev 2" and "Critical" are one bucket — the same fold the dashboard uses."""
        layout = build_layout(_source())
        tally = dict(layout.tally)
        assert tally["Critical"] == 2
        assert sum(tally.values()) == 2

    def test_tally_is_critical_first(self):
        labels = [label for label, _ in build_layout(_source()).tally]
        assert labels == ["Critical", "High", "Medium", "Low", "Unrated"]

    def test_null_fields_are_dropped_from_findings(self):
        """A page of em dashes reads as a broken document, not a sparse one."""
        layout = build_layout(_source())
        risk = layout.sections[1].findings[0]
        assert risk.fields == ()
        assert risk.heading == "No lockout policy"

    def test_null_table_cells_become_dashes(self):
        """A table keeps its grid, so a gap has to be visibly a gap."""
        anomalies = build_layout(_source()).sections[3]
        assert anomalies.rows[0] == (
            "Off-hours login",
            "—",
            "203.0.113.44",
            "—",
            "17",
            "—",
        )

    def test_table_weights_match_column_count(self):
        for section in build_layout(_source()).sections:
            if section.is_table:
                assert len(section.weights) == len(section.columns)
                assert all(len(row) == len(section.columns) for row in section.rows)

    def test_unnamed_findings_still_get_a_heading(self):
        layout = build_layout(
            _source(sections=_sections(attack_types=[AttackTypeItem(risk_level="High")]))
        )
        assert layout.sections[0].findings[0].heading == "Unnamed technique"

    def test_unverified_integrity_is_stated_not_coloured(self):
        """On paper there is no grey badge to carry "nobody checked this"."""
        layout = build_layout(_source(integrity_state="UNKNOWN", integrity_checked_at=None))
        integrity = dict(layout.meta)["Source integrity"]
        assert "not verified" in integrity.lower()

    def test_filename_is_slugged(self):
        layout = build_layout(_source(report_name="Q3: perimeter/log review!!"))
        assert layout.filename_stem == "q3-perimeter-log-review-20260714"

    def test_hostile_report_name_cannot_reach_the_filename(self):
        layout = build_layout(_source(report_name='../../etc/passwd"; rm -rf /'))
        assert layout.filename_stem.startswith("etc-passwd-rm-rf")
        assert not set(layout.filename_stem) - set("abcdefghijklmnopqrstuvwxyz0123456789-")


class TestRenderers:
    @pytest.mark.parametrize(
        ("export_format", "magic", "media_type"),
        [("pdf", PDF_MAGIC, "application/pdf"), ("docx", DOCX_MAGIC, DOCX_MEDIA_TYPE)],
    )
    def test_produces_a_valid_file(self, export_format, magic, media_type):
        rendered = export.render(_source(), export_format)
        assert rendered.content.startswith(magic)
        assert rendered.media_type == media_type
        assert rendered.filename.endswith(f".{export_format}")

    @pytest.mark.parametrize("export_format", ["pdf", "docx"])
    def test_an_empty_report_still_renders(self, export_format):
        """A report where every section failed is the one most worth exporting."""
        rendered = export.render(_source(sections=ReportSections()), export_format)
        assert len(rendered.content) > 1000

    def test_docx_is_a_readable_package(self):
        rendered = export.render(_source(), "docx")
        with zipfile.ZipFile(io.BytesIO(rendered.content)) as archive:
            assert "word/document.xml" in archive.namelist()
            body = archive.read("word/document.xml").decode("utf-8")
            properties = archive.read("docProps/core.xml").decode("utf-8")
        assert "Credential stuffing" in body
        assert "Q3 Perimeter Log Review" in body
        # The caveat has to be legible to whoever checks a file's properties
        # before forwarding it, not only to whoever opens it.
        assert "Confidential" in properties

    def test_docx_escapes_markup_in_model_output(self):
        """An LLM will emit angle brackets. They must not become XML."""
        sections = _sections(
            attack_types=[AttackTypeItem(attack_name="<script>alert(1)</script>")]
        )
        rendered = export.render(_source(sections=sections), "docx")
        with zipfile.ZipFile(io.BytesIO(rendered.content)) as archive:
            body = archive.read("word/document.xml").decode("utf-8")
        assert "&lt;script&gt;" in body
        assert "<script>" not in body

    def test_pdf_renders_markup_in_model_output(self):
        """ReportLab treats a Paragraph as markup, so the same input must be escaped."""
        sections = _sections(
            attack_types=[
                AttackTypeItem(
                    attack_name="AT&T breach <b>",
                    attack_description="5 < 10 & 10 > 5",
                )
            ]
        )
        # An unescaped "<b>" raises inside ReportLab's parser rather than
        # rendering wrong, so simply completing is the assertion.
        assert export.render(_source(sections=sections), "pdf").content.startswith(PDF_MAGIC)


class TestExportEndpoint:
    def test_pdf(self, api, analyst_auth, analyst_report):
        response = api.get(f"/reports/{analyst_report}/export", headers=analyst_auth)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(PDF_MAGIC)
        assert "attachment; filename=" in response.headers["content-disposition"]

    def test_docx(self, api, analyst_auth, analyst_report):
        response = api.get(
            f"/reports/{analyst_report}/export", params={"format": "docx"}, headers=analyst_auth
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == DOCX_MEDIA_TYPE
        assert response.content.startswith(DOCX_MAGIC)

    def test_defaults_to_pdf(self, api, analyst_auth, analyst_report):
        response = api.get(f"/reports/{analyst_report}/export", headers=analyst_auth)
        assert response.content.startswith(PDF_MAGIC)

    def test_unknown_format_is_rejected(self, api, analyst_auth, analyst_report):
        response = api.get(
            f"/reports/{analyst_report}/export", params={"format": "xlsx"}, headers=analyst_auth
        )
        assert response.status_code == 422

    def test_requires_authentication(self, api, analyst_report):
        assert api.get(f"/reports/{analyst_report}/export").status_code == 401

    def test_another_users_report_is_not_found(self, api, analyst_auth, other_report):
        assert api.get(f"/reports/{other_report}/export", headers=analyst_auth).status_code == 404

    def test_admin_can_export_anything(self, api, admin_auth, analyst_report):
        response = api.get(f"/reports/{analyst_report}/export", headers=admin_auth)
        assert response.status_code == 200


class TestSourceAdapters:
    def test_owner_export_carries_the_seal_and_the_reference(self):
        detail = ReportDetail(
            report_id=uuid.uuid4(),
            report_name="R",
            document_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            classification="Internal",
            status="complete",
            sections=ReportSections(),
            file_hash="b" * 64,
        )
        source = source_from_detail(detail, document_name="log.csv")
        assert source.file_hash == "b" * 64
        assert source.reference == str(detail.report_id)
        assert source.provenance is None

    def test_threat_intel_reaches_the_document(self):
        indicators = [
            ThreatIntelItem(
                id=uuid.uuid4(),
                indicator="203.0.113.44",
                indicator_type="ip",
                source="abuseipdb",
                reputation_score=94,
                risk_level="CRITICAL",
                country="RU",
            )
        ]
        layout = build_layout(_source(threat_intel=indicators))
        intel = layout.sections[-1]
        assert intel.rows[0][0] == "203.0.113.44"
        assert dict(layout.totals)["Enriched indicators"] == 1


class TestSeverityLadder:
    """The exporter, the dashboard and the UI must agree on what "Sev 1" means."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Critical", "critical"),
            ("CRITICAL ", "critical"),
            ("Sev 1", "critical"),
            ("High risk", "high"),
            ("Med.", "medium"),
            ("Moderate", "medium"),
            ("informational", "low"),
            ("Severe", "critical"),
            ("banana", "unknown"),
            (None, "unknown"),
            ("", "unknown"),
        ],
    )
    def test_buckets(self, value, expected):
        assert bucket(value) == expected

    def test_counts_include_empty_buckets(self):
        tally = counts([RiskAssessmentItem(risk_level="High")])
        assert tally == {"unknown": 0, "low": 0, "medium": 0, "high": 1, "critical": 0}

    def test_sql_case_is_generated_from_the_same_table(self):
        """Guards the dedup: analytics must not grow its own copy of the ladder."""
        from app.db import models
        from app.services import analytics
        from app.services.severity import SEVERITY_PREFIXES

        compiled = str(
            analytics.severity_bucket(models.AttackType.risk_level).compile(
                compile_kwargs={"literal_binds": True}
            )
        ).lower()
        for prefix, name in SEVERITY_PREFIXES:
            assert f"'{prefix}%'" in compiled
            assert f"'{name}'" in compiled
