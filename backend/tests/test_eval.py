"""Phase 11: the evaluation harness.

The harness is the thing that says how good the output is, so the tests that
matter are the ones proving it can say "bad". A validator that never fails is
indistinguishable from no validator, and a gate that cannot trip is decoration.
Most of this file feeds the harness output it should reject.
"""

from __future__ import annotations

import json

import pytest

from app.core.config import settings
from app.eval import catalog, harness
from app.eval import metrics as metrics_module
from app.eval.replay import CASSETTE, FixtureMiss, ReplayProvider, prompt_key
from app.eval.run import check_gate, summarize
from app.eval.validators import validate_sections
from app.schemas.report import (
    AttackTypeItem,
    ReportGenerationResult,
    ReportSections,
    VulnerabilityItem,
)

# --- The vendored catalogues ----------------------------------------------


class TestCatalogue:
    def test_it_is_the_real_attack_catalogue(self):
        """Spot-checked against facts, so a truncated or fake file fails here.

        A hand-typed approximation would make every hallucination number this
        project reports a fiction, so the data is checked rather than trusted.
        """
        assert catalog.technique_count() > 600
        assert catalog.technique("T1110").name == "Brute Force"
        assert catalog.technique("T1105").name == "Ingress Tool Transfer"
        assert catalog.technique("T1059.001").name == "PowerShell"
        assert catalog.technique("T1059.001").sub_technique is True

    def test_it_is_the_real_cwe_catalogue(self):
        assert catalog.weakness_count() > 800
        assert "Cross-site Scripting" in catalog.weakness("CWE-79").name
        assert "SQL Injection" in catalog.weakness("CWE-89").name
        assert catalog.weakness("CWE-287").name == "Improper Authentication"

    def test_retired_techniques_are_kept_and_marked(self):
        """T1022 is real but revoked.

        Dropping it would score a model that named it as having fabricated an
        identifier, which would make the hallucination rate climb with the
        calendar rather than with model behaviour.
        """
        retired = catalog.technique("T1022")
        assert retired is not None
        assert retired.retired is True
        assert retired.name == "Data Encrypted"

    def test_provenance_travels_with_the_data(self):
        info = catalog.source_info()
        for key in ("mitre_attack", "cwe"):
            assert info[key]["url"].startswith("https://")
            assert len(info[key]["sha256"]) == 64
            assert info[key]["licence"]
            assert info[key]["version"]

    def test_lookup_is_case_and_whitespace_tolerant_but_not_fuzzy(self):
        assert catalog.technique(" t1110 ") is not None
        # A decorated string is a *formatting* failure and must not be hidden:
        # any downstream tool consuming these ids would choke on it.
        assert catalog.technique("T1110 (Brute Force)") is None


# --- Validators, fed deliberately bad output ------------------------------


def _attacks(*items) -> ReportSections:
    return ReportSections(attack_types=list(items))


class TestMitreValidation:
    def test_a_valid_technique_passes(self):
        result = validate_sections(
            _attacks(
                AttackTypeItem(
                    attack_name="Brute force",
                    attack_mitre_technique_id="T1110",
                    attack_mitre_technique_name="Brute Force",
                )
            )
        )
        assert result.issues == []
        assert result.techniques_emitted == 1

    def test_an_invented_technique_id_is_caught(self):
        result = validate_sections(
            _attacks(AttackTypeItem(attack_mitre_technique_id="T9999"))
        )
        assert [i.kind for i in result.issues] == ["mitre_unknown"]
        assert result.invalid_identifiers == 1

    def test_a_real_id_with_an_invented_name_is_caught(self):
        """The failure this validator exists for.

        `T1022` labelled "Remote Code Execution via Web Application" is a real
        id with a wrong name. No format check catches it, and it reads
        perfectly plausibly to anyone without the catalogue open — which is
        exactly the error observed from a local model and quoted in the phase
        brief.
        """
        result = validate_sections(
            _attacks(
                AttackTypeItem(
                    attack_mitre_technique_id="T1022",
                    attack_mitre_technique_name="Remote Code Execution via Web Application",
                )
            )
        )
        kinds = [i.kind for i in result.issues]
        assert "mitre_name_mismatch" in kinds
        detail = next(i for i in result.issues if i.kind == "mitre_name_mismatch").detail
        assert "Data Encrypted" in detail

    def test_a_retired_technique_is_noted_but_not_a_hallucination(self):
        result = validate_sections(
            _attacks(
                AttackTypeItem(
                    attack_mitre_technique_id="T1022",
                    attack_mitre_technique_name="Data Encrypted",
                )
            )
        )
        assert [i.kind for i in result.issues] == ["mitre_retired"]
        # Recorded, but not counted against the model: ATT&CK retired it, the
        # model did not invent it.
        assert result.invalid_identifiers == 0

    @pytest.mark.parametrize("bad", ["1110", "TT1110", "T111", "technique 1110"])
    def test_a_malformed_technique_id_is_caught(self, bad):
        result = validate_sections(_attacks(AttackTypeItem(attack_mitre_technique_id=bad)))
        assert [i.kind for i in result.issues] == ["mitre_malformed"]

    @pytest.mark.parametrize(
        "claimed",
        [
            "Brute Force",
            "brute force",
            "Brute-Force",
            # Providers write the parent:child convention out in full.
            "Credential Access: Brute Force",
            "Brute Force (Password Guessing)",
        ],
    )
    def test_name_comparison_tolerates_wording_but_not_meaning(self, claimed):
        result = validate_sections(
            _attacks(
                AttackTypeItem(
                    attack_mitre_technique_id="T1110",
                    attack_mitre_technique_name=claimed,
                )
            )
        )
        assert result.issues == [], f"{claimed!r} should be accepted for T1110"

    def test_a_substring_of_the_official_name_is_not_accepted(self):
        """Otherwise a wrong-but-adjacent technique slips through."""
        result = validate_sections(
            _attacks(
                AttackTypeItem(
                    attack_mitre_technique_id="T1110",
                    attack_mitre_technique_name="Brute",
                )
            )
        )
        assert [i.kind for i in result.issues] == ["mitre_name_mismatch"]

    def test_a_null_identifier_is_not_an_error(self):
        """Null is the instructed answer when the model cannot identify one."""
        result = validate_sections(_attacks(AttackTypeItem(attack_name="Something")))
        assert result.issues == []
        assert result.techniques_emitted == 0


class TestCveAndCweValidation:
    def test_a_well_formed_cve_passes(self):
        result = validate_sections(
            ReportSections(vulnerabilities=[VulnerabilityItem(cve_id="CVE-2021-44228")])
        )
        assert result.issues == []

    @pytest.mark.parametrize("bad", ["CVE-21-4", "2021-44228", "CVE-2021", "CVE-YYYY-NNNN"])
    def test_a_malformed_cve_is_caught(self, bad):
        result = validate_sections(
            ReportSections(vulnerabilities=[VulnerabilityItem(cve_id=bad)])
        )
        assert [i.kind for i in result.issues] == ["cve_malformed"]

    def test_cve_existence_is_deliberately_not_checked(self):
        """A plausible but non-existent CVE passes, and the docs say so.

        Verifying existence needs a network call against an unbounded list that
        grows daily. A gate that needs the internet fails on a bad day and is
        deleted on the next, so the harness checks the format and says that is
        what it checked.
        """
        result = validate_sections(
            ReportSections(vulnerabilities=[VulnerabilityItem(cve_id="CVE-2099-99999")])
        )
        assert result.issues == []

    def test_a_non_existent_cwe_is_caught(self):
        result = validate_sections(
            ReportSections(vulnerabilities=[VulnerabilityItem(cwe_id="CWE-99999")])
        )
        assert [i.kind for i in result.issues] == ["cwe_unknown"]

    def test_a_real_cwe_passes(self):
        result = validate_sections(
            ReportSections(vulnerabilities=[VulnerabilityItem(cwe_id="CWE-79")])
        )
        assert result.issues == []


# --- The golden dataset ---------------------------------------------------


class TestGolden:
    def test_the_log_chunks_with_real_row_provenance(self):
        chunks = harness.golden_chunks()
        assert chunks
        # Rows, not just lines: the golden log is tabular and its citations
        # must point at rows an analyst can open the CSV and read.
        assert all(chunk.row_start is not None for chunk in chunks)
        assert chunks[0].row_start == 0

    def test_the_labels_are_internally_consistent(self):
        attacks = harness.expected_attacks()
        assert len(attacks) >= 5
        ids = [label.id for label in attacks]
        assert len(ids) == len(set(ids)), "duplicate label ids"
        for label in attacks:
            assert label.match_any, f"{label.id} has no way to match"
            assert label.why, f"{label.id} has no stated justification"

    def test_every_labelled_technique_exists_in_the_catalogue(self):
        """The labels are held to the same standard as the model's output.

        A golden label naming a technique that does not exist would quietly
        make the MITRE agreement figure unreachable.
        """
        for label in harness.expected_attacks():
            if label.mitre:
                assert catalog.technique(label.mitre) is not None, label.mitre

    def test_the_benign_rows_the_labels_protect_are_really_in_the_log(self):
        text = harness.GOLDEN_LOG.read_text(encoding="utf-8")
        for label in harness.must_not_report():
            assert any(needle in text for needle in label.match_any), label.id


# --- Metrics --------------------------------------------------------------


def _result(sections: ReportSections, **kwargs) -> ReportGenerationResult:
    return ReportGenerationResult(sections=sections, **kwargs)


class TestMetrics:
    def _compute(self, sections, **kwargs):
        validation = validate_sections(sections)
        return metrics_module.compute(
            _result(sections, **kwargs),
            validation,
            expected_attacks=harness.expected_attacks(),
            expected_anomalies=harness.expected_anomalies(),
            forbidden=harness.must_not_report(),
            sections_total=5,
        )

    def test_a_zero_denominator_is_none_not_zero(self):
        """"Nothing to measure" must not print as "measured, and perfect"."""
        computed, _, _ = self._compute(ReportSections())
        assert computed.hallucination_rate is None
        assert computed.grounding_rate is None
        assert computed.recall == 0.0, "labels exist, so recall has a denominator"

    def test_bundling_shows_up_as_the_gap_between_the_two_recalls(self):
        """One narrative finding covering four labels is not four findings.

        Observed on the first live run: three attack findings covered seven
        labels because one described the whole campaign in passing.
        """
        everything = AttackTypeItem(
            attack_name="Campaign",
            attack_description=(
                "brute force, then powershell, then smb lateral movement, "
                "then a beacon, then the event log was cleared"
            ),
        )
        computed, attacks, _ = self._compute(_attacks(everything))

        assert len(attacks.matched) >= 4, "coverage credits every label mentioned"
        assert len(attacks.distinct) == 1, "one finding can satisfy only one label"
        assert computed.recall > computed.distinct_recall

    def test_reporting_benign_activity_is_a_false_positive(self):
        computed, attacks, _ = self._compute(
            _attacks(
                AttackTypeItem(
                    attack_name="Suspicious file access",
                    attack_description="rlee read onboarding.pdf from the share",
                )
            )
        )
        assert attacks.false_positives == ["rlee_benign"]
        assert computed.precision == 0.0

    def test_grounding_rate_counts_ungrounded_findings(self):
        computed, _, _ = self._compute(
            _attacks(AttackTypeItem(attack_name="A"), AttackTypeItem(attack_name="B")),
            ungrounded_findings=1,
        )
        assert computed.findings_total == 2
        assert computed.grounding_rate == 0.5

    def test_p95_is_a_measurement_that_happened(self):
        """Nearest-rank, not interpolated — an interpolated p95 over five
        samples invents a number between two real ones."""
        assert metrics_module._percentile([1.0, 2.0, 3.0, 4.0, 100.0], 0.95) == 100.0
        assert metrics_module._percentile([], 0.95) is None


# --- The gate -------------------------------------------------------------


class TestGate:
    def _payload(self, **metrics) -> dict:
        base = {
            "identifiers_emitted": 10,
            "invalid_identifiers": 0,
            "hallucination_rate": 0.0,
            "findings_total": 10,
            "findings_grounded": 10,
            "grounding_rate": 1.0,
            "section_success_rate": 1.0,
        }
        base.update(metrics)
        return {"metrics": base}

    def test_a_clean_run_passes(self):
        assert check_gate(self._payload()) == []

    def test_it_trips_on_hallucination(self):
        breaches = check_gate(
            self._payload(hallucination_rate=0.5, invalid_identifiers=5)
        )
        assert any("hallucination" in breach for breach in breaches)

    def test_it_trips_on_lost_grounding(self):
        breaches = check_gate(self._payload(grounding_rate=0.1, findings_grounded=1))
        assert any("grounding" in breach for breach in breaches)

    def test_it_trips_on_failed_sections(self):
        breaches = check_gate(self._payload(section_success_rate=0.2))
        assert any("section success" in breach for breach in breaches)

    def test_refusing_to_answer_is_not_a_passing_grade(self):
        """A report with nothing in it scores `None` on every rate.

        Without this, the cheapest way to pass the gate would be to emit
        nothing at all — a model with no findings has nothing to be wrong
        about, and every threshold above would wave it through.
        """
        breaches = check_gate(
            self._payload(
                identifiers_emitted=0, hallucination_rate=None,
                findings_total=0, grounding_rate=None,
            )
        )
        assert len(breaches) == 2
        assert any("nothing was measured" in breach for breach in breaches)

    def test_the_thresholds_come_from_config(self):
        """A quality bar is a project decision, not a constant in a function."""
        assert 0 <= settings.eval_max_hallucination_rate <= 1
        assert 0 <= settings.eval_min_grounding_rate <= 1


# --- Replay ---------------------------------------------------------------


class TestReplay:
    def test_the_committed_fixtures_are_real_recordings(self):
        payload = json.loads(CASSETTE.read_text(encoding="utf-8"))
        about = payload["_about"]
        # Recorded from a real provider, not hand-written. If this ever says
        # "synthetic", every number the replayed gate reports means something
        # different and the docs have to say so.
        assert about["recorded_from"].startswith(("gemini:", "groq:", "ollama:"))
        assert payload["interactions"], "no recorded interactions"

    def test_replay_is_deterministic(self):
        """Same fixtures, same key, same answer — that is the whole point."""
        first, second = ReplayProvider(), ReplayProvider()
        prompt = json.loads(CASSETTE.read_text(encoding="utf-8"))["interactions"][0]
        key = prompt["key"]
        assert first._responses[(key, 1)] == second._responses[(key, 1)]

    def test_a_changed_prompt_misses_loudly(self):
        """Silently replaying a response to a *different* prompt would report
        the old model's quality as if it were the new prompt's."""
        provider = ReplayProvider()
        with pytest.raises(FixtureMiss, match="re-record"):
            import asyncio

            asyncio.run(provider._invoke("a prompt that was never recorded"))

    def test_a_replayed_call_reports_no_tokens(self):
        """It did not spend any. Reporting the recorded numbers as this run's
        would make a replayed run look like it cost money."""
        import asyncio

        payload = json.loads(CASSETTE.read_text(encoding="utf-8"))
        # Reconstruct a prompt that hashes to a recorded key by using the
        # recorded key directly — the provider only ever sees the hash.
        provider = ReplayProvider()
        recorded_key = payload["interactions"][0]["key"]
        provider._responses[(prompt_key("x"), 1)] = provider._responses[(recorded_key, 1)]

        _, usage = asyncio.run(provider._invoke("x"))
        assert usage.prompt_tokens is None
        assert usage.completion_tokens is None


# --- The whole run --------------------------------------------------------


class TestRun:
    def test_the_replayed_run_produces_a_full_result(self):
        """The end-to-end path CI takes, in the test suite."""
        import asyncio

        from app.eval.run import evaluate

        payload = asyncio.run(evaluate(live=False, record=False))

        assert payload["run"]["mode"] == "replay"
        # Every number is meaningless without the catalogue it was scored
        # against, so the versions travel with the result.
        assert payload["catalogues"]["mitre_attack"]["version"]
        assert payload["metrics"]["findings_total"] > 0
        assert check_gate(payload) == [], "the committed baseline must pass its own gate"

    def test_the_summary_says_which_mode_it_ran_in(self):
        """A replayed number describes the fixtures; a live one describes a
        model. Confusing the two is the main way this kind of harness lies."""
        text = summarize(
            {
                "metrics": metrics_module.Metrics().as_dict(),
                "run": {
                    "mode": "replay", "provider": "replay:x", "recorded_from": "gemini:y",
                    "golden_log": "g.csv", "golden_chunks": 3,
                    "thresholds": {},
                },
                "catalogues": {
                    "mitre_attack": {"version": "17.1"}, "cwe": {"version": "4.20"}
                },
                "attacks": {"missed": [], "false_positives": []},
                "anomalies": {"missed": []},
                "identifier_issues": [],
                "section_errors": [],
            }
        )
        assert "replayed" in text
        assert "not the current model" in text
        # A zero denominator renders as a dash, never as 0.0%.
        assert "—" in text
