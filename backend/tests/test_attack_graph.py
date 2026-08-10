"""Phase 14 — the attack graph.

The thing worth testing hardest is the one the phase called out: **entity
normalisation must not over-merge**. In a security tool, two real principals
collapsed into one node hides a relationship that exists and asserts one that
does not, and nobody can tell by looking at the picture. Every other property
here — the edges an anomaly row asserts, the risk a node inherits, ownership
scoping — is easier to get right and easier to notice when it is wrong.

The over-merge test is a regression test, not a hypothetical: the first version
of this module produced a node called `application` carrying the aliases `20`,
`21`, `37` and `system`, because a transitive union walked through a generic
display name.
"""

from __future__ import annotations

import uuid

import pytest

from app.db import models
from app.services import attack_graph

from .conftest import _make_document


def _report(db, owner, name: str = "Graph report") -> models.Report:
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


def _anomaly(db, report, **fields):
    row = models.Anomaly(report_id=report.report_id, **fields)
    db.add(row)
    db.flush()
    return row


def _event(db, report, entity, name="Event"):
    row = models.Timeline(report_id=report.report_id, entity=entity, event_name=name)
    db.add(row)
    db.flush()
    return row


def _attack(db, report, **fields):
    row = models.AttackType(report_id=report.report_id, **fields)
    db.add(row)
    db.flush()
    return row


def _evidence(db, report, item_id, chunk_id, section="anomalies"):
    db.add(
        models.FindingEvidence(
            report_id=report.report_id,
            section=section,
            item_id=item_id,
            chunk_id=chunk_id,
            excerpt="log line",
        )
    )
    db.flush()


def node(graph, label):
    return next(n for n in graph.nodes if n.label.casefold() == label.casefold())


class TestNormalisation:
    """Case and whitespace, and nothing else."""

    @pytest.mark.parametrize(
        "left, right",
        [("jdoe", "JDOE"), ("jdoe", " jdoe "), ("jdoe", '"jdoe"'), ("a  b", "a b")],
    )
    def test_same_identifier_written_differently_is_one_key(self, left, right):
        assert attack_graph.normalize(left) == attack_graph.normalize(right)

    @pytest.mark.parametrize(
        "left, right",
        [
            ("jdoe", "j.doe"),
            ("jdoe", "j_doe"),
            ("jdoe", "j-doe"),
            ("jdoe@corp.com", "jdoe@partner.com"),
            ("jdoe@corp.com", "jdoe"),
            ("CORP\\jdoe", "jdoe"),
        ],
    )
    def test_different_identifiers_stay_different(self, left, right):
        # Every one of these would be a plausible "obvious" normalisation, and
        # every one of them merges two people who may not be the same person.
        assert attack_graph.normalize(left) != attack_graph.normalize(right)

    def test_a_duplicate_node_is_the_acceptable_failure(self, db, analyst):
        report = _report(db, analyst)
        _anomaly(db, report, anomaly_name="A", user_id="jdoe", source_ip="10.0.0.1")
        _anomaly(db, report, anomaly_name="B", user_id="j.doe", source_ip="10.0.0.2")

        graph = attack_graph.build_graph(db, report)
        labels = {n.label for n in graph.nodes if n.type == "user"}
        # Two nodes, not one. This is the *desired* outcome: leaving a
        # duplicate is recoverable by a human reading the graph; merging two
        # real principals is not.
        assert labels == {"jdoe", "j.doe"}


    @pytest.mark.parametrize("marker", ["n/a", "N/A ", "none", "unknown", "-"])
    def test_a_null_marker_is_not_an_entity(self, db, analyst, marker):
        # Found by looking at a real graph: `n/a` had become a user node with
        # its own edges, which reads as an actor the log never named.
        report = _report(db, analyst)
        _anomaly(db, report, anomaly_name="A", user_id=marker, source_ip="10.0.0.1")

        graph = attack_graph.build_graph(db, report)
        assert [n.label for n in graph.nodes] == ["10.0.0.1"]


class TestIdentityMerging:
    def test_a_row_carrying_both_identifiers_yields_one_node(self, db, analyst):
        report = _report(db, analyst)
        _anomaly(
            db, report, anomaly_name="A", user_id="4471", user_name="rlee",
            source_ip="10.0.0.1",
        )
        _anomaly(
            db, report, anomaly_name="B", user_id="4471", user_name="rlee",
            source_ip="10.0.0.2",
        )

        graph = attack_graph.build_graph(db, report)
        users = [n for n in graph.nodes if n.type == "user"]
        assert len(users) == 1
        assert users[0].label == "rlee"
        # The merge is a claim, so it is shown rather than silently applied.
        assert users[0].aliases == ["4471"]

    def test_an_ambiguous_display_name_merges_nothing(self, db, analyst):
        """The regression this module was rewritten for.

        `application` is a label, not an identity. A transitive union through
        it welded three principals into one node — which reads on the canvas as
        one actor touching three hosts, an assertion the log never made.
        """
        report = _report(db, analyst)
        for identifier in ("20", "21", "37"):
            _anomaly(
                db,
                report,
                anomaly_name="A",
                user_id=identifier,
                user_name="application",
                source_ip=f"10.0.0.{identifier}",
            )

        graph = attack_graph.build_graph(db, report)
        merged = [n for n in graph.nodes if n.label == "application"]
        assert merged, "the display name should still be a node"
        assert merged[0].aliases == [], "an ambiguous pairing must not merge"
        assert {n.label for n in graph.nodes if n.type == "user"} == {
            "application",
            "20",
            "21",
            "37",
        }

    def test_the_pairing_must_be_unambiguous_in_both_directions(self, db, analyst):
        report = _report(db, analyst)
        # One id, two names — the mirror of the case above.
        _anomaly(db, report, anomaly_name="A", user_id="4471", user_name="rlee")
        _anomaly(db, report, anomaly_name="B", user_id="4471", user_name="r.lee")

        graph = attack_graph.build_graph(db, report)
        assert all(n.aliases == [] for n in graph.nodes)


class TestClassification:
    @pytest.mark.parametrize(
        "label, expected",
        [
            ("10.14.2.37", "host"),
            ("999.1.1.1", "entity"),  # shaped like an address, is not one
            ("fe80::1ff:fe23:4567", "host"),
            ("attacker.example.com", "host"),
            ("vpn-gw-01", "host"),
            ("powershell.exe", "process"),
            ("/usr/bin/curl", "file"),
            ("C:\\Windows\\System32\\cmd.exe", "process"),
            ("payroll-export.csv", "file"),
            ("Unauthorised user", "entity"),
        ],
    )
    def test_shapes(self, label, expected):
        assert attack_graph.classify(label) == expected


class TestEdges:
    def test_an_anomaly_row_asserts_exactly_the_edges_it_contains(self, db, analyst):
        report = _report(db, analyst)
        _anomaly(
            db,
            report,
            anomaly_name="Spray",
            user_name="rlee",
            source_ip="10.0.0.1",
            destination_ip="10.0.0.2",
            protocol="SMB",
        )

        graph = attack_graph.build_graph(db, report)
        kinds = {(e.kind, e.label) for e in graph.edges}
        assert ("originates_from", None) in kinds
        assert ("connects_to", "SMB") in kinds
        # And nothing else: the row does not say the user reached the
        # destination directly, so the graph must not either.
        assert len(graph.edges) == 2

    def test_a_user_reaches_a_destination_directly_only_with_no_source(
        self, db, analyst
    ):
        report = _report(db, analyst)
        _anomaly(db, report, anomaly_name="A", user_name="rlee", destination_ip="10.0.0.9")

        graph = attack_graph.build_graph(db, report)
        assert [e.kind for e in graph.edges] == ["accesses"]

    def test_repeated_observations_thicken_one_edge(self, db, analyst):
        report = _report(db, analyst)
        for _ in range(3):
            _anomaly(
                db, report, anomaly_name="A", source_ip="10.0.0.1",
                destination_ip="10.0.0.2", protocol="TCP",
            )

        graph = attack_graph.build_graph(db, report)
        assert len(graph.edges) == 1
        assert graph.edges[0].weight == 3

    def test_shared_citations_connect_entities_no_column_relates(self, db, analyst):
        """How a timeline entity joins the graph at all.

        It has no address and no user column; what it has is a citation, and
        two findings read out of the same log rows are related.
        """
        report = _report(db, analyst)
        anomaly = _anomaly(db, report, anomaly_name="A", source_ip="10.0.0.1")
        event = _event(db, report, "wks-4471")
        _evidence(db, report, anomaly.id, chunk_id=7)
        _evidence(db, report, event.id, chunk_id=7, section="timeline")

        graph = attack_graph.build_graph(db, report)
        co = [e for e in graph.edges if e.kind == "co_occurs"]
        assert len(co) == 1
        assert {co[0].source, co[0].target} == {"10.0.0.1", "wks-4471"}

    def test_a_chunk_naming_everything_creates_no_edges(self, db, analyst):
        # A chunk cited by half the report is not evidence of a specific
        # relationship; it is a chunk. Without this the graph becomes a clique
        # the moment one retrieval hit is shared widely.
        report = _report(db, analyst)
        for index in range(8):
            row = _event(db, report, f"host-{index}")
            _evidence(db, report, row.id, chunk_id=1, section="timeline")

        graph = attack_graph.build_graph(db, report)
        assert [e for e in graph.edges if e.kind == "co_occurs"] == []


class TestRisk:
    def test_a_node_inherits_severity_from_a_finding_that_cites_the_same_rows(
        self, db, analyst
    ):
        report = _report(db, analyst)
        anomaly = _anomaly(db, report, anomaly_name="A", source_ip="10.0.0.1")
        attack = _attack(db, report, attack_name="Ransomware", risk_level="Critical")
        _evidence(db, report, anomaly.id, chunk_id=3)
        _evidence(db, report, attack.id, chunk_id=3, section="attack_types")

        graph = attack_graph.build_graph(db, report)
        host = node(graph, "10.0.0.1")
        assert host.risk == "critical"
        assert any(f.basis == "evidence" for f in host.findings)

    def test_a_verbatim_mention_is_a_weaker_basis_and_says_so(self, db, analyst):
        report = _report(db, analyst)
        _anomaly(db, report, anomaly_name="A", source_ip="10.0.0.1")
        _attack(
            db,
            report,
            attack_name="Beaconing",
            risk_level="High",
            attack_description="Repeated callbacks from 10.0.0.1 to a paste service.",
        )

        graph = attack_graph.build_graph(db, report)
        host = node(graph, "10.0.0.1")
        assert host.risk == "high"
        assert [f.basis for f in host.findings if f.section == "attack_types"] == [
            "mention"
        ]

    def test_a_mention_never_matches_a_longer_identifier(self, db, analyst):
        """`10.0.0.7` is not named by a finding that says `10.0.0.76`.

        A plain substring test attaches a critical severity to the wrong host,
        and it looks entirely plausible on the canvas.
        """
        report = _report(db, analyst)
        _anomaly(db, report, anomaly_name="A", source_ip="10.0.0.7")
        _attack(
            db,
            report,
            attack_name="Exfiltration",
            risk_level="Critical",
            attack_description="Bulk transfer from 10.0.0.76.",
        )

        graph = attack_graph.build_graph(db, report)
        assert node(graph, "10.0.0.7").risk == "unknown"

    def test_an_edge_takes_the_worse_of_its_two_ends(self, db, analyst):
        report = _report(db, analyst)
        _anomaly(
            db, report, anomaly_name="A", source_ip="10.0.0.1",
            destination_ip="10.0.0.2", protocol="TCP",
        )
        _attack(
            db, report, attack_name="X", risk_level="Critical",
            attack_description="Traffic to 10.0.0.2.",
        )

        graph = attack_graph.build_graph(db, report)
        assert graph.edges[0].risk == "critical"


class TestShapeAndLimits:
    def test_a_report_with_no_entities_says_so_rather_than_returning_nothing(
        self, db, analyst
    ):
        report = _report(db, analyst)
        _attack(db, report, attack_name="Something", risk_level="High")

        graph = attack_graph.build_graph(db, report)
        assert graph.nodes == []
        assert graph.edges == []
        # An empty canvas and a failed request must not look alike.
        assert graph.empty_reason
        assert "no entities" in graph.empty_reason

    def test_a_large_report_is_capped_and_admits_it(self, db, analyst, monkeypatch):
        monkeypatch.setattr(attack_graph, "MAX_NODES", 5)
        report = _report(db, analyst)
        for index in range(12):
            _anomaly(db, report, anomaly_name="A", source_ip=f"10.0.1.{index}")

        graph = attack_graph.build_graph(db, report)
        assert len(graph.nodes) == 5
        assert graph.total_nodes == 12
        # A graph that silently drops nodes to stay readable lies about the
        # report it claims to describe.
        assert graph.truncated is True

    def test_the_cap_keeps_the_worst_nodes(self, db, analyst, monkeypatch):
        monkeypatch.setattr(attack_graph, "MAX_NODES", 2)
        report = _report(db, analyst)
        for index in range(6):
            _anomaly(db, report, anomaly_name="A", source_ip=f"10.0.2.{index}")
        _attack(
            db, report, attack_name="X", risk_level="Critical",
            attack_description="Compromise of 10.0.2.4.",
        )

        graph = attack_graph.build_graph(db, report)
        assert "10.0.2.4" in {n.label for n in graph.nodes}

    def test_edges_never_dangle_after_truncation(self, db, analyst, monkeypatch):
        monkeypatch.setattr(attack_graph, "MAX_NODES", 2)
        report = _report(db, analyst)
        for index in range(6):
            _anomaly(
                db, report, anomaly_name="A", source_ip=f"10.0.3.{index}",
                destination_ip=f"10.0.4.{index}", protocol="TCP",
            )

        graph = attack_graph.build_graph(db, report)
        keys = {n.id for n in graph.nodes}
        assert all(e.source in keys and e.target in keys for e in graph.edges)


class TestEndpoint:
    def test_the_route_returns_the_graph(self, api, db, analyst, analyst_auth):
        report = _report(db, analyst)
        _anomaly(
            db, report, anomaly_name="A", user_name="rlee",
            source_ip="10.0.0.1", destination_ip="10.0.0.2", protocol="TCP",
        )

        response = api.get(f"/reports/{report.report_id}/graph", headers=analyst_auth)
        assert response.status_code == 200
        body = response.json()
        assert len(body["nodes"]) == 3
        assert len(body["edges"]) == 2

    def test_another_users_report_is_a_404(self, api, analyst_auth, other_report):
        response = api.get(f"/reports/{other_report}/graph", headers=analyst_auth)
        assert response.status_code == 404

    def test_authentication_is_required(self, api, analyst_report):
        assert api.get(f"/reports/{analyst_report}/graph").status_code == 401
