"""Dashboard aggregation endpoints.

Two things are worth testing here beyond the happy path, because both are
places this could quietly lie:

* **Scoping.** An analyst's totals must not include another analyst's reports.
  A leak here is invisible — the number is simply larger than it should be.
* **Severity normalisation.** The column is free text written by a model.
  "CRITICAL ", "Sev 1" and "critical" are one bucket; "banana" is `unknown`,
  not silently dropped.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db import models

ENDPOINTS = [
    "/dashboard/summary",
    "/dashboard/reports-over-time",
    "/dashboard/severity",
    "/dashboard/top-attack-types",
    "/dashboard/anomalies-over-time",
]


def _midnight() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _report(db, owner, *, days_ago: int = 0, status: str = "complete") -> models.Report:
    """A report owned by `owner`, generated `days_ago` days back at midday."""
    now = datetime.now(timezone.utc)
    document = models.Document(
        document_name="log.csv",
        document_size=1.0,
        document_extension=".csv",
        document_path="/tmp/log.csv",
        created_at=now,
        modified_at=now,
        uploaded_at=now,
        user_id=owner.user_id,
    )
    db.add(document)
    db.flush()

    report = models.Report(
        report_name="Report",
        document_id=document.document_id,
        user_id=owner.user_id,
        generated_at=_midnight() - timedelta(days=days_ago) + timedelta(hours=12),
        classification="Internal",
        status=status,
    )
    db.add(report)
    db.flush()
    return report


def _attack(db, report, *, name="Brute Force", mitre="T1110", level="High"):
    db.add(
        models.AttackType(
            report_id=report.report_id,
            attack_name=name,
            attack_mitre_technique_id=mitre,
            attack_mitre_technique_name=name,
            risk_level=level,
        )
    )
    db.flush()


def _risk(db, report, *, level="Medium"):
    db.add(models.RiskAssessment(report_id=report.report_id, risk_name="R", risk_level=level))
    db.flush()


def _anomaly(db, report, *, counted=None):
    db.add(models.Anomaly(report_id=report.report_id, anomaly_name="A", counted=counted))
    db.flush()


# --- Auth ------------------------------------------------------------------


@pytest.mark.parametrize("path", ENDPOINTS)
def test_requires_authentication(api, path):
    assert api.get(path).status_code == 401


@pytest.mark.parametrize("path", ENDPOINTS)
def test_authenticated_analyst_is_allowed(api, analyst_auth, path):
    assert api.get(path, headers=analyst_auth).status_code == 200


# --- KPI summary -----------------------------------------------------------


def test_summary_counts_only_the_callers_reports(api, db, analyst, other_user, analyst_auth):
    mine = _report(db, analyst)
    _attack(db, mine, level="Critical")
    _report(db, analyst, status="failed")

    theirs = _report(db, other_user)
    _attack(db, theirs, level="Critical")

    body = api.get("/dashboard/summary", headers=analyst_auth).json()
    assert body["total_reports"] == 2
    assert body["documents_ingested"] == 2
    assert body["critical_findings"] == 1
    assert body["attention_required"] == 1


def test_summary_for_admin_spans_every_user(api, db, analyst, other_user, admin, admin_auth):
    # An admin sees the whole database, and the developer's database is not
    # empty — so this measures the delta rather than an absolute. Both new
    # reports must land in it; an analyst-scoped query would see only one.
    before = api.get("/dashboard/summary", headers=admin_auth).json()

    _attack(db, _report(db, analyst), level="Critical")
    _attack(db, _report(db, other_user), level="Critical")

    after = api.get("/dashboard/summary", headers=admin_auth).json()
    assert after["total_reports"] - before["total_reports"] == 2
    assert after["critical_findings"] - before["critical_findings"] == 2


def test_summary_counts_partial_and_failed_as_attention(api, db, analyst, analyst_auth):
    _report(db, analyst, status="complete")
    _report(db, analyst, status="partial")
    _report(db, analyst, status="failed")

    body = api.get("/dashboard/summary", headers=analyst_auth).json()
    assert body["attention_required"] == 2


def test_summary_of_a_new_account_is_all_zeros(api, analyst_auth):
    body = api.get("/dashboard/summary", headers=analyst_auth).json()
    assert body == {
        "total_reports": 0,
        "critical_findings": 0,
        "documents_ingested": 0,
        "attention_required": 0,
        "open_alerts": 0,
    }


# --- Reports over time -----------------------------------------------------


def test_reports_over_time_returns_one_bucket_per_day_including_empty_ones(
    api, db, analyst, analyst_auth
):
    _report(db, analyst, days_ago=0)
    _report(db, analyst, days_ago=0)
    _report(db, analyst, days_ago=3, status="partial")

    series = api.get("/dashboard/reports-over-time?days=7", headers=analyst_auth).json()

    assert len(series) == 7
    assert [bucket["day"] for bucket in series] == sorted(bucket["day"] for bucket in series)
    assert series[-1]["total"] == 2
    assert series[-4]["total"] == 1
    assert series[-4]["attention"] == 1
    assert series[0]["total"] == 0


def test_reports_over_time_excludes_reports_older_than_the_window(
    api, db, analyst, analyst_auth
):
    _report(db, analyst, days_ago=30)
    series = api.get("/dashboard/reports-over-time?days=7", headers=analyst_auth).json()
    assert sum(bucket["total"] for bucket in series) == 0


def test_reports_over_time_is_scoped_to_the_caller(api, db, analyst, other_user, analyst_auth):
    _report(db, analyst)
    _report(db, other_user)
    series = api.get("/dashboard/reports-over-time?days=7", headers=analyst_auth).json()
    assert sum(bucket["total"] for bucket in series) == 1


@pytest.mark.parametrize("days", [0, -1, 366])
def test_reports_over_time_rejects_an_out_of_range_window(api, analyst_auth, days):
    response = api.get(f"/dashboard/reports-over-time?days={days}", headers=analyst_auth)
    assert response.status_code == 422


# --- Severity --------------------------------------------------------------


def test_severity_always_returns_every_bucket_low_to_critical(api, analyst_auth):
    body = api.get("/dashboard/severity", headers=analyst_auth).json()
    assert [slice_["severity"] for slice_ in body] == [
        "unknown",
        "low",
        "medium",
        "high",
        "critical",
    ]
    assert all(slice_["count"] == 0 for slice_ in body)


def test_severity_normalises_free_text_from_the_model(api, db, analyst, analyst_auth):
    report = _report(db, analyst)
    for level in ["CRITICAL ", "critical", "Sev 1", "High risk", "Moderate", "med", "informational"]:
        _attack(db, report, level=level)

    counts = {s["severity"]: s["count"] for s in api.get("/dashboard/severity", headers=analyst_auth).json()}
    assert counts["critical"] == 3  # CRITICAL, critical, Sev 1
    assert counts["high"] == 1
    assert counts["medium"] == 2  # Moderate, med
    assert counts["low"] == 1  # informational


def test_severity_buckets_null_and_unrecognised_values_as_unknown(
    api, db, analyst, analyst_auth
):
    report = _report(db, analyst)
    _attack(db, report, level=None)
    _attack(db, report, level="banana")

    counts = {s["severity"]: s["count"] for s in api.get("/dashboard/severity", headers=analyst_auth).json()}
    assert counts["unknown"] == 2


def test_severity_counts_attack_risks_and_general_risks_together(
    api, db, analyst, analyst_auth
):
    report = _report(db, analyst)
    _attack(db, report, level="High")
    _risk(db, report, level="High")

    counts = {s["severity"]: s["count"] for s in api.get("/dashboard/severity", headers=analyst_auth).json()}
    assert counts["high"] == 2


def test_severity_is_scoped_to_the_caller(api, db, analyst, other_user, analyst_auth):
    _attack(db, _report(db, analyst), level="High")
    _attack(db, _report(db, other_user), level="High")

    counts = {s["severity"]: s["count"] for s in api.get("/dashboard/severity", headers=analyst_auth).json()}
    assert counts["high"] == 1


# --- Top attack types ------------------------------------------------------


def test_top_attack_types_ranks_by_frequency_and_keeps_the_mitre_id(
    api, db, analyst, analyst_auth
):
    report = _report(db, analyst)
    for _ in range(3):
        _attack(db, report, name="Phishing", mitre="T1566")
    _attack(db, report, name="Brute Force", mitre="T1110")

    body = api.get("/dashboard/top-attack-types", headers=analyst_auth).json()
    assert [row["attack_name"] for row in body] == ["Phishing", "Brute Force"]
    assert body[0]["count"] == 3
    assert body[0]["attack_mitre_technique_id"] == "T1566"


def test_top_attack_types_folds_case_and_whitespace_variants_together(
    api, db, analyst, analyst_auth
):
    report = _report(db, analyst)
    _attack(db, report, name="SQL Injection", mitre="T1190")
    _attack(db, report, name="sql injection", mitre="T1190")
    _attack(db, report, name="  SQL INJECTION ", mitre="T1190")

    body = api.get("/dashboard/top-attack-types", headers=analyst_auth).json()
    assert len(body) == 1
    assert body[0]["count"] == 3


def test_top_attack_types_ignores_unnamed_attacks(api, db, analyst, analyst_auth):
    report = _report(db, analyst)
    _attack(db, report, name=None)
    _attack(db, report, name="Phishing")

    body = api.get("/dashboard/top-attack-types", headers=analyst_auth).json()
    assert [row["attack_name"] for row in body] == ["Phishing"]


def test_top_attack_types_honours_the_limit(api, db, analyst, analyst_auth):
    report = _report(db, analyst)
    for index in range(5):
        _attack(db, report, name=f"Technique {index}")

    body = api.get("/dashboard/top-attack-types?limit=2", headers=analyst_auth).json()
    assert len(body) == 2


def test_top_attack_types_is_scoped_to_the_caller(api, db, analyst, other_user, analyst_auth):
    _attack(db, _report(db, analyst), name="Phishing")
    _attack(db, _report(db, other_user), name="Phishing")

    body = api.get("/dashboard/top-attack-types", headers=analyst_auth).json()
    assert body[0]["count"] == 1


def test_top_attack_types_for_admin_aggregates_across_users(
    api, db, analyst, other_user, admin, admin_auth
):
    name = "Cross-tenant technique"

    def phishing_count(headers):
        body = api.get("/dashboard/top-attack-types?limit=50", headers=headers).json()
        return next((row["count"] for row in body if row["attack_name"] == name), 0)

    _attack(db, _report(db, analyst), name=name)
    _attack(db, _report(db, other_user), name=name)

    assert phishing_count(admin_auth) == 2


# --- Anomalies over time ---------------------------------------------------


def test_anomalies_over_time_reports_findings_and_summed_occurrences(
    api, db, analyst, analyst_auth
):
    report = _report(db, analyst, days_ago=1)
    _anomaly(db, report, counted=10)
    _anomaly(db, report, counted=32)

    series = api.get("/dashboard/anomalies-over-time?days=5", headers=analyst_auth).json()
    assert len(series) == 5
    assert series[-2] == {"day": series[-2]["day"], "findings": 2, "events": 42}


def test_anomalies_over_time_treats_a_missing_count_as_zero_events(
    api, db, analyst, analyst_auth
):
    report = _report(db, analyst)
    _anomaly(db, report, counted=None)

    series = api.get("/dashboard/anomalies-over-time?days=3", headers=analyst_auth).json()
    assert series[-1]["findings"] == 1
    assert series[-1]["events"] == 0


def test_anomalies_over_time_is_scoped_to_the_caller(
    api, db, analyst, other_user, analyst_auth
):
    _anomaly(db, _report(db, analyst), counted=5)
    _anomaly(db, _report(db, other_user), counted=5)

    series = api.get("/dashboard/anomalies-over-time?days=3", headers=analyst_auth).json()
    assert sum(bucket["findings"] for bucket in series) == 1
