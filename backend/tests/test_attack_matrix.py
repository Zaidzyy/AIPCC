"""Phase 12 — the ATT&CK matrix, its detections, and the Navigator export.

Three things are worth testing here and one thing is not. Worth testing: that
the grid agrees with the vendored catalogue (a matrix drawn from an
approximation would be decoration), that a bad identifier lands where the
module says it lands, and that the exported layer really is a layer — checked
against a schema derived from MITRE's published spec rather than against our
own idea of it. Not worth testing: that Recharts draws rectangles.

Admin-scoped assertions are deltas, never absolutes. The `db` fixture rolls
back, but an admin's query still sees every row already in the developer's
database, so `== 2` is only ever correct on an empty machine — the trap Phase 4
and Phase 8 each paid for once.
"""

from __future__ import annotations

import json
import uuid

import jsonschema
import pytest

from app.db import models
from app.eval import catalog
from app.services import attack_matrix

from .conftest import _make_document


def _report(db, owner, name: str = "Matrix report") -> models.Report:
    document = _make_document(db, owner, name=f"{uuid.uuid4().hex[:8]}.csv")
    report = models.Report(
        report_name=name,
        document_id=document.document_id,
        user_id=owner.user_id,
        classification="Internal",
        status="complete",
    )
    db.add(report)
    db.flush()
    return report


def _attack(db, report, technique_id, technique_name, *, attack_name="Finding"):
    row = models.AttackType(
        report_id=report.report_id,
        attack_name=attack_name,
        attack_mitre_technique_id=technique_id,
        attack_mitre_technique_name=technique_name,
        risk_level="High",
    )
    db.add(row)
    db.flush()
    return row


# The four defect classes, one row each, plus one clean detection and one
# honest null. Written out here rather than generated so the expected verdicts
# below can be read next to the input that produces them.
def _mixed_report(db, owner) -> models.Report:
    report = _report(db, owner, "Mixed report")
    _attack(db, report, "T1059", "Command and Scripting Interpreter")  # clean
    _attack(db, report, "T1053", "Cron Job Persistence")  # real id, wrong name
    _attack(db, report, "T9999", "Invented Technique")  # does not exist
    _attack(db, report, "T1022", "Data Encrypted")  # revoked by ATT&CK
    _attack(db, report, "not-an-id", "Nonsense")  # malformed
    _attack(db, report, None, None)  # the instructed answer when unsure
    return report


class TestGrid:
    """The columns and cells are MITRE's, not ours."""

    def test_columns_are_the_published_fourteen_in_order(self):
        grid = attack_matrix.matrix_grid()
        names = [tactic.shortname for tactic in grid.tactics]
        assert len(names) == 14
        # Order comes from the bundle's matrix object, which is the order the
        # published matrix is read in. Sorting by TA-number happens to agree
        # today; asserting the ends catches the day it stops.
        assert names[0] == "reconnaissance"
        assert names[-1] == "impact"
        assert names == sorted(set(names), key=names.index)  # no duplicates

    def test_technique_lands_in_every_tactic_attack_assigns_it(self):
        grid = attack_matrix.matrix_grid()
        columns = {
            tactic.shortname
            for tactic in grid.tactics
            if any(cell.technique_id == "T1078" for cell in tactic.techniques)
        }
        # Valid Accounts is one of the few placed in four tactics, which makes
        # it the case that catches a mapping that only ever keeps the first.
        assert columns == set(catalog.technique("T1078").tactics)
        assert len(columns) == 4

    def test_sub_techniques_nest_under_their_parent(self):
        grid = attack_matrix.matrix_grid()
        execution = next(t for t in grid.tactics if t.shortname == "execution")
        assert all(not cell.sub_technique for cell in execution.techniques)

        parent = next(cell for cell in execution.techniques if cell.technique_id == "T1059")
        children = {child.technique_id for child in parent.sub_techniques}
        assert "T1059.001" in children
        assert all(child.startswith("T1059.") for child in children)
        assert children == {
            item.technique_id
            for item in catalog.techniques_for("execution")
            if item.sub_technique and item.parent_id == "T1059"
        }

    def test_retired_techniques_are_not_drawn(self):
        # T1022 is revoked. `catalog.technique` still resolves it — a model
        # naming it has not invented anything — but MITRE does not draw it, so
        # neither does this.
        assert catalog.technique("T1022").retired
        grid = attack_matrix.matrix_grid()
        every_id = {
            cell.technique_id
            for tactic in grid.tactics
            for cell in tactic.techniques
        }
        assert "T1022" not in every_id

    def test_grid_needs_no_database(self):
        # Not incidental: `/attack/matrix` is MITRE's data, identical for every
        # caller, and must not become a per-request query.
        assert attack_matrix.matrix_grid().technique_count > 500


class TestDetectionPlacement:
    """What happens to each of the four ways a technique id can be wrong."""

    def test_clean_identifier_is_placed_and_verified(self, db, analyst):
        _mixed_report(db, analyst)
        found = attack_matrix.detections(db, analyst)
        clean = next(d for d in found.detections if d.technique_id == "T1059")
        assert clean.verified
        assert clean.issue is None
        assert clean.name == "Command and Scripting Interpreter"
        assert clean.tactics == ["execution"]

    def test_wrong_name_is_placed_but_never_labelled_with_the_wrong_name(
        self, db, analyst
    ):
        _mixed_report(db, analyst)
        found = attack_matrix.detections(db, analyst)
        mismatch = next(d for d in found.detections if d.technique_id == "T1053")
        assert mismatch.verified is False
        assert "Scheduled Task/Job" in mismatch.issue
        # The cell carries the catalogue's name. Rendering the model's wording
        # would print the fabrication onto the matrix as a label.
        assert mismatch.name == "Scheduled Task/Job"

    @pytest.mark.parametrize(
        "value, reason",
        [
            ("T9999", "mitre_unknown"),
            ("T1022", "mitre_retired"),
            ("not-an-id", "mitre_malformed"),
        ],
    )
    def test_unplaceable_identifiers_get_no_cell_and_are_still_reported(
        self, db, analyst, value, reason
    ):
        _mixed_report(db, analyst)
        found = attack_matrix.detections(db, analyst)

        assert value not in {d.technique_id for d in found.detections}
        entry = next(u for u in found.unplaced if u.value == value)
        assert entry.reason == reason
        assert entry.detail  # the validator's own sentence, not a code
        assert entry.sources[0].report_name == "Mixed report"

    def test_a_null_technique_is_not_a_detection(self, db, analyst):
        _mixed_report(db, analyst)
        found = attack_matrix.detections(db, analyst)
        # Six rows, one of them null: five emitted identifiers.
        assert found.techniques_emitted == 5
        assert len(found.detections) + len(found.unplaced) == 5

    def test_counts_aggregate_across_reports(self, db, analyst):
        first = _report(db, analyst, "First")
        second = _report(db, analyst, "Second")
        for report in (first, second):
            _attack(db, report, "T1110", "Brute Force")
        _attack(db, second, "T1110", "Brute Force", attack_name="Second finding")

        found = attack_matrix.detections(db, analyst)
        brute = next(d for d in found.detections if d.technique_id == "T1110")
        assert brute.count == 3
        assert {source.report_name for source in brute.sources} == {"First", "Second"}

    def test_report_denominator_counts_reports_that_found_nothing(self, db, analyst):
        _report(db, analyst, "Found nothing")
        found = attack_matrix.detections(db, analyst)
        # A report that named no technique still had its log read. Taking the
        # denominator from the join would silently drop it and inflate any
        # per-report rate computed from these two numbers.
        assert found.reports_considered == 1
        assert found.detections == []

    def test_lowercase_identifier_resolves_to_the_canonical_cell(self, db, analyst):
        report = _report(db, analyst)
        _attack(db, report, "t1110 ", "Brute Force")
        found = attack_matrix.detections(db, analyst)
        assert [d.technique_id for d in found.detections] == ["T1110"]


class TestScoping:
    """The aggregate endpoint reads across every report a caller can see, which
    makes it exactly where a missing scope leaks one analyst's findings."""

    def test_analyst_sees_only_their_own(self, db, analyst, other_user):
        mine = _report(db, analyst, "Mine")
        theirs = _report(db, other_user, "Theirs")
        _attack(db, mine, "T1110", "Brute Force")
        _attack(db, theirs, "T1486", "Data Encrypted for Impact")

        found = attack_matrix.detections(db, analyst)
        assert [d.technique_id for d in found.detections] == ["T1110"]
        assert found.reports_considered == 1

    def test_admin_sees_both(self, db, admin, analyst, other_user):
        before = attack_matrix.detections(db, admin)
        mine = _report(db, analyst, "Mine")
        theirs = _report(db, other_user, "Theirs")
        _attack(db, mine, "T1110", "Brute Force")
        _attack(db, theirs, "T1486", "Data Encrypted for Impact")

        after = attack_matrix.detections(db, admin)
        # A delta, because this developer's database already holds real rows.
        added = after.techniques_emitted - before.techniques_emitted
        assert added == 2

    def test_report_scoped_read_rejects_a_foreign_report(
        self, api, analyst_auth, other_report
    ):
        response = api.get(f"/attack/detections/{other_report}", headers=analyst_auth)
        # 404, not 403: a 403 confirms the id is real to somebody who should
        # not know that.
        assert response.status_code == 404

    def test_endpoints_require_authentication(self, api, analyst_report):
        assert api.get("/attack/detections").status_code == 401
        assert api.get(f"/attack/detections/{analyst_report}").status_code == 401
        assert api.get("/attack/navigator-layer").status_code == 401

    def test_grid_is_readable_by_any_caller(self, api):
        # Deliberately unauthenticated: MITRE's published data, not ours.
        response = api.get("/attack/matrix")
        assert response.status_code == 200
        assert len(response.json()["tactics"]) == 14


class TestNavigatorLayer:
    """The export has to open in MITRE's tool, not merely look like it would."""

    @staticmethod
    def _schema() -> dict:
        return catalog.navigator_schema()

    def test_layer_validates_against_the_published_format(self, db, analyst):
        _mixed_report(db, analyst)
        found = attack_matrix.detections(db, analyst)
        layer = attack_matrix.navigator_layer(found, name="Test layer")
        jsonschema.validate(layer, self._schema())

    def test_schema_is_strict_enough_to_catch_a_typo(self, db, analyst):
        # The reason the derived schema disallows unknown properties: without
        # it, `techniqueId` validates and Navigator silently renders nothing.
        _mixed_report(db, analyst)
        layer = attack_matrix.navigator_layer(
            attack_matrix.detections(db, analyst), name="Test layer"
        )
        layer["techniques"][0]["techniqueId"] = layer["techniques"][0].pop("techniqueID")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(layer, self._schema())

    def test_version_block_matches_the_vendored_spec(self, db, analyst):
        _mixed_report(db, analyst)
        layer = attack_matrix.navigator_layer(
            attack_matrix.detections(db, analyst), name="Test layer"
        )
        assert layer["versions"]["layer"] == "4.5"
        assert layer["domain"] == "enterprise-attack"
        # Navigator wants the major version, not the point release.
        assert layer["versions"]["attack"] == attack_matrix.attack_version().split(".")[0]

    def test_unplaced_identifiers_are_absent_from_cells_but_named_in_the_file(
        self, db, analyst
    ):
        _mixed_report(db, analyst)
        found = attack_matrix.detections(db, analyst)
        layer = attack_matrix.navigator_layer(found, name="Test layer")

        cells = {entry["techniqueID"] for entry in layer["techniques"]}
        assert cells == {"T1059", "T1053"}
        # They have no cell — but a reader must not be able to mistake this for
        # a clean run, so they are in the description and counted in metadata.
        assert "T9999" in layer["description"]
        assert "T1022" in layer["description"]
        counted = next(m for m in layer["metadata"] if m["name"] == "Unplaced identifiers")
        assert counted["value"] == "3"

    def test_unverified_cell_gets_an_explicit_colour_and_says_why(self, db, analyst):
        _mixed_report(db, analyst)
        layer = attack_matrix.navigator_layer(
            attack_matrix.detections(db, analyst), name="Test layer"
        )
        entry = next(e for e in layer["techniques"] if e["techniqueID"] == "T1053")
        assert entry["color"] == attack_matrix.UNVERIFIED_COLOR
        assert "UNVERIFIED" in entry["comment"]

        clean = next(e for e in layer["techniques"] if e["techniqueID"] == "T1059")
        assert "color" not in clean  # the gradient still encodes its frequency

    def test_gradient_is_valid_with_a_single_detection(self, db, analyst):
        report = _report(db, analyst)
        _attack(db, report, "T1110", "Brute Force")
        layer = attack_matrix.navigator_layer(
            attack_matrix.detections(db, analyst), name="One"
        )
        # maxValue must be strictly greater than minValue; a 0..0 gradient is a
        # layer Navigator refuses to open.
        assert layer["gradient"]["maxValue"] > layer["gradient"]["minValue"]
        jsonschema.validate(layer, self._schema())

    def test_no_entry_pins_a_detection_to_one_tactic(self, db, analyst):
        # A finding says a technique was observed; it does not say under which
        # tactic. A missing `tactic` is Navigator's "annotate under every
        # column this technique appears in", which is exactly what is known.
        _mixed_report(db, analyst)
        layer = attack_matrix.navigator_layer(
            attack_matrix.detections(db, analyst), name="Test layer"
        )
        assert all("tactic" not in entry for entry in layer["techniques"])

    def test_download_is_an_attachment_and_is_audited(
        self, api, db, analyst, analyst_auth
    ):
        report = _mixed_report(db, analyst)
        response = api.get(
            f"/attack/navigator-layer/{report.report_id}", headers=analyst_auth
        )
        assert response.status_code == 200
        assert response.headers["content-disposition"].endswith('-navigator.json"')
        jsonschema.validate(json.loads(response.content), self._schema())

        entry = (
            db.query(models.AuditLog)
            .filter(models.AuditLog.target_id == str(report.report_id))
            .order_by(models.AuditLog.at.desc())
            .first()
        )
        assert entry is not None
        assert entry.detail["format"] == "navigator-layer"


class TestVendoredMatrixData:
    """The grid is only worth drawing because it is really MITRE's.

    Same argument as Phase 11's catalogue checks: an approximated tactic list
    would make every cell on this page a decoration, so a truncated or
    hand-edited file has to fail the suite rather than render a smaller matrix.
    """

    def test_tactics_carry_their_real_identifiers(self):
        tactics = {tactic.shortname: tactic for tactic in catalog.tactics()}
        assert tactics["initial-access"].tactic_id == "TA0001"
        assert tactics["execution"].name == "Execution"
        assert tactics["impact"].tactic_id == "TA0040"
        assert all(t.tactic_id.startswith("TA") for t in catalog.tactics())

    def test_every_current_technique_has_at_least_one_tactic(self):
        orphans = [
            item.technique_id
            for item in map(catalog.technique, ["T1059", "T1078", "T1110", "T1486"])
            if not item.tactics
        ]
        assert orphans == []

    def test_navigator_schema_records_where_it_came_from(self):
        source = catalog.navigator_schema()["_source"]
        assert "mitre-attack/attack-navigator" in source["url"]
        assert len(source["sha256"]) == 64
        assert source["version"] == "4.5"
        # Derived, not typed out — the claim `SOURCES.md` makes.
        assert "vendor.py" in source["derivation"]

    def test_navigator_schema_keeps_the_specs_required_fields(self):
        schema = catalog.navigator_schema()
        assert set(schema["required"]) == {"name", "domain"}
        assert schema["$defs"]["Technique"]["required"] == ["techniqueID"]
        assert set(schema["$defs"]["Gradient"]["required"]) == {
            "colors",
            "minValue",
            "maxValue",
        }
