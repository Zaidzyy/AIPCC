"""Building an attack graph out of what a report already contains.

**No second extraction pass.** The nodes come from typed columns — an anomaly's
`user_id`, `user_name`, `source_ip`, `destination_ip`, `protocol`, and a
timeline event's `entity` — and the edges come from those same rows plus the
citations Phase 10 recorded. Asking a model to extract entities would produce a
second set of claims needing a second validator, and the whole shape of this
project is that model output is checked before it is believed.

**Identity, which was the decision this module exists to get right.** In a
security tool, merging two real principals into one node is a far worse error
than showing the same person twice: the first hides a relationship that is not
there and invents one that is, and nobody can tell by looking. So:

* Normalisation is **case, whitespace and surrounding punctuation only**.
  `JDOE`, `jdoe ` and `"jdoe"` are one node. **`j.doe` and `jdoe` are not**, and
  neither are `jdoe@corp.com` and `jdoe@partner.com` — stripping a separator or
  a domain is exactly the guess that merges two people.
* Two *different* identifiers are merged only when a single log row asserts
  they denote the same principal — an anomaly carrying both `user_id=4471` and
  `user_name=rlee` is the schema saying so, not a similarity heuristic — **and
  only when the pairing is unambiguous across the whole report**. If one name
  is seen against several ids, that name is a label rather than an identity and
  nothing merges. This is not hypothetical: the first run of this module
  against real generated data produced a node called `application` carrying the
  aliases `20`, `21`, `37` and `system`, because a transitive union had walked
  through a generic display name and welded four principals together.
* Node **type** is a shape guess and is allowed to be one; node **identity**
  never is. Guessing that `vpn-gw-01` is a host puts the wrong icon on a
  correct node. Guessing that two names are one person puts a relationship on
  the canvas that was never observed.

Nothing here fuzzy-matches, and that is the point: the failure mode of this
module is a duplicate node, never a fabricated identity.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.schemas.graph import AttackGraph, GraphEdge, GraphFinding, GraphNode
from app.services.severity import SEVERITY_ORDER, UNKNOWN, bucket

# A readable graph is the deliverable; a hairball is not. 60 nodes is about
# what fits on a laptop screen at a legible label size, and anything dropped is
# reported rather than silently absent.
MAX_NODES = 60
# Findings listed per node. A node in a busy report can be touched by dozens;
# the drawer shows the strongest and says how many there were.
MAX_FINDINGS_PER_NODE = 12

_WHITESPACE = re.compile(r"\s+")
# Trimmed from the ends only. Anything internal is part of the identifier.
_EDGE_PUNCTUATION = "\"'`<>[](){},;:. \t"

_IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_IPV6 = re.compile(r"^[0-9a-f:]+$", re.IGNORECASE)
_HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9-]+)*\.[a-z]{2,}$", re.I)
# `vpn-gw-01`, `wks-4471`: hyphenated, undotted, unspaced.
_SHORT_HOSTNAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$", re.I)

# Extensions that make a path a *running thing* rather than a *stored thing*.
# `.com` is deliberately absent. It was an executable extension in 1985 and is
# the most common TLD now, so keeping it turns `attacker.example.com` into a
# process — found by a test, which is the only way anyone would notice.
_EXECUTABLE = {
    ".exe", ".dll", ".sys", ".scr", ".msi",
    ".ps1", ".sh", ".bash", ".bat", ".cmd", ".py", ".pl", ".rb", ".jar", ".vbs",
}
_DOCUMENT = {
    ".csv", ".log", ".txt", ".json", ".xml", ".pdf", ".doc", ".docx", ".xls",
    ".xlsx", ".zip", ".tar", ".gz", ".7z", ".key", ".pem", ".conf", ".cfg", ".ini",
}


# Values a model writes when a field has no value. They are the model saying
# "absent", not naming a principal, and drawing `n/a` as an actor on a graph an
# analyst reads is worse than leaving the edge unattached. Matched after
# normalisation, so "N/A " and "None" are covered too.
NULL_MARKERS = frozenset(
    {"n/a", "na", "none", "null", "nil", "unknown", "unspecified", "-", "--", "?"}
)


def normalize(value: str | None) -> str:
    """Fold one written identifier to its comparison key.

    Case, whitespace and *surrounding* punctuation. Nothing else, ever — see
    the module docstring for why every additional rule here is a way to merge
    two people who are not the same person.
    """
    if not value:
        return ""
    return _WHITESPACE.sub(" ", value.strip().strip(_EDGE_PUNCTUATION)).casefold()


def classify(label: str) -> str:
    """Guess what kind of thing a free-text entity is, or admit that it cannot.

    Only the timeline's `entity` needs this: users and addresses arrive from
    columns that already say what they are. An entity that matches nothing
    stays `entity` rather than being filed under whichever of the four types
    looks least wrong.
    """
    text = label.strip()
    if not text:
        return "entity"

    if _IPV4.match(text) and all(0 <= int(part) <= 255 for part in text.split(".")):
        return "host"
    if ":" in text and _IPV6.match(text) and text.count(":") >= 2:
        return "host"

    lowered = text.casefold()
    has_path = "/" in text or "\\" in text
    basename = re.split(r"[\\/]", lowered)[-1]
    extension = f".{basename.rsplit('.', 1)[1]}" if "." in basename else ""

    if extension in _EXECUTABLE:
        return "process"
    if extension in _DOCUMENT or has_path:
        return "file"
    if _HOSTNAME.match(lowered):
        return "host"
    if _SHORT_HOSTNAME.match(lowered):
        # `vpn-gw-01`, `wks-4471`, `dc-01` — the RFC 1123 short-hostname shape,
        # and what a timeline entity almost always is when it is hyphenated,
        # unspaced and undotted. A guess, and it only decides which icon the
        # node gets: identity is settled before this is ever consulted.
        return "host"
    return "entity"


# --- Node accumulation ----------------------------------------------------


@dataclass
class _Node:
    key: str
    label: str
    type: str
    aliases: set[str] = field(default_factory=set)
    observations: int = 0
    findings: list[GraphFinding] = field(default_factory=list)
    # Chunk ids cited by the findings this node came from. Used to attach the
    # sections that carry a severity — anomalies and timeline rows carry none.
    chunks: set[int] = field(default_factory=set)


class _Builder:
    def __init__(self) -> None:
        self.nodes: dict[str, _Node] = {}
        self.edges: dict[tuple[str, str, str], GraphEdge] = {}
        # Union-find over user identifiers. Only ever unioned from a single row
        # carrying two identifiers for one principal.
        self.parent: dict[str, str] = {}

    # -- identity ---------------------------------------------------------

    def find(self, key: str) -> str:
        root = key
        while self.parent.get(root, root) != root:
            root = self.parent[root]
        while self.parent.get(key, key) != root:
            key, self.parent[key] = self.parent[key], root
        return root

    def union(self, left: str, right: str) -> None:
        """Merge two identifiers that one log row said were the same principal.

        Deliberately not commutative in effect: the surviving node keeps the
        first label seen, and the other becomes an alias, so a report always
        renders the same way.
        """
        a, b = self.find(left), self.find(right)
        if a == b:
            return
        self.parent[b] = a
        loser = self.nodes.pop(b, None)
        winner = self.nodes.get(a)
        if loser and winner:
            winner.aliases.add(loser.label)
            winner.aliases.update(loser.aliases)
            winner.observations += loser.observations
            winner.findings.extend(loser.findings)
            winner.chunks |= loser.chunks
            self._rewire(b, a)

    def _rewire(self, old: str, new: str) -> None:
        for key in list(self.edges):
            source, target, kind = key
            if old not in (source, target):
                continue
            edge = self.edges.pop(key)
            edge.source = new if source == old else source
            edge.target = new if target == old else target
            if edge.source == edge.target:
                continue  # a merge turned an edge into a self-loop
            self.add_edge(edge.source, edge.target, kind, edge.label, edge.weight)

    # -- nodes and edges ---------------------------------------------------

    def add_node(self, raw: str | None, node_type: str) -> str | None:
        key = normalize(raw)
        if not key or key in NULL_MARKERS:
            return None
        key = self.find(key)
        node = self.nodes.get(key)
        if node is None:
            node = _Node(key=key, label=(raw or "").strip(), type=node_type)
            self.nodes[key] = node
        elif node.type == "entity" and node_type != "entity":
            # A column that knows what it is beats a shape guess.
            node.type = node_type
        node.observations += 1
        return key

    def add_edge(
        self, source: str, target: str, kind: str, label: str | None = None, weight: int = 1
    ) -> None:
        if source == target:
            return
        # Undirected in effect for the pairs that are symmetric; the key is
        # ordered so A→B and B→A do not become two arcs across the canvas.
        key = (source, target, kind) if source < target else (target, source, kind)
        existing = self.edges.get(key)
        if existing is None:
            self.edges[key] = GraphEdge(
                source=key[0], target=key[1], kind=kind, label=label, weight=weight
            )
        else:
            existing.weight += weight
            existing.label = existing.label or label


# --- Construction ---------------------------------------------------------


def build_graph(db: Session, report: models.Report) -> AttackGraph:
    """Nodes and edges for one report."""
    builder = _Builder()

    anomalies = db.scalars(
        select(models.Anomaly)
        .where(models.Anomaly.report_id == report.report_id)
        .order_by(models.Anomaly.id)
    ).all()
    events = db.scalars(
        select(models.Timeline)
        .where(models.Timeline.report_id == report.report_id)
        .order_by(models.Timeline.id)
    ).all()

    evidence = _evidence_by_item(db, report.report_id)

    mergeable = unambiguous_user_pairs(anomalies)
    for anomaly in anomalies:
        _add_anomaly(builder, anomaly, evidence.get(anomaly.id, set()), mergeable)
    for event in events:
        _add_event(builder, event, evidence.get(event.id, set()))

    if not builder.nodes:
        return AttackGraph(
            report_id=report.report_id,
            empty_reason=(
                "This report records no entities. Its anomalies and timeline "
                "carry no users, addresses or named actors to draw."
            ),
        )

    _attach_scored_findings(db, report, builder, evidence)
    _add_co_occurrence_edges(builder)

    return _assemble(report, builder)


def _evidence_by_item(db: Session, report_id: uuid.UUID) -> dict[uuid.UUID, set[int]]:
    """Which chunks each finding cited. Phase 10's table, read sideways."""
    rows = db.execute(
        select(models.FindingEvidence.item_id, models.FindingEvidence.chunk_id).where(
            models.FindingEvidence.report_id == report_id
        )
    ).all()
    grouped: dict[uuid.UUID, set[int]] = defaultdict(set)
    for item_id, chunk_id in rows:
        grouped[item_id].add(chunk_id)
    return grouped


def unambiguous_user_pairs(anomalies) -> set[tuple[str, str]]:
    """Name/id pairs safe to treat as one principal.

    A pair qualifies only when *neither* half was ever seen against a different
    counterpart in this report. `rlee` seen only with `4471` is one person
    written two ways; `application` seen with `20`, `21` and `37` is a display
    label, and merging through it would weld three principals into one — which
    is exactly what the first version of this function did.
    """
    names: dict[str, set[str]] = defaultdict(set)
    ids: dict[str, set[str]] = defaultdict(set)
    for anomaly in anomalies:
        name, identifier = normalize(anomaly.user_name), normalize(anomaly.user_id)
        if not name or not identifier or name == identifier:
            continue
        names[name].add(identifier)
        ids[identifier].add(name)
    return {
        (name, next(iter(counterparts)))
        for name, counterparts in names.items()
        if len(counterparts) == 1 and len(ids[next(iter(counterparts))]) == 1
    }


def _add_anomaly(
    builder: _Builder,
    anomaly: models.Anomaly,
    chunks: set[int],
    mergeable: set[tuple[str, str]],
) -> None:
    """One anomaly row: up to three nodes and the edges the row itself asserts."""
    user_keys = [
        key
        for key in (
            builder.add_node(anomaly.user_name, "user"),
            builder.add_node(anomaly.user_id, "user"),
        )
        if key
    ]
    # The only merge this module ever performs, and only for a pair the whole
    # report agrees on. (`user_id` here is a value read out of the log, never a
    # row key.) The name is added first, so it survives as the label.
    pair = (normalize(anomaly.user_name), normalize(anomaly.user_id))
    if len(user_keys) == 2 and pair in mergeable:
        builder.union(user_keys[0], user_keys[1])

    user = builder.find(user_keys[0]) if user_keys else None
    source = builder.add_node(anomaly.source_ip, "host")
    destination = builder.add_node(anomaly.destination_ip, "host")

    finding = GraphFinding(
        section="anomalies",
        item_id=anomaly.id,
        title=anomaly.anomaly_name,
        detail=_anomaly_detail(anomaly),
        basis="source",
    )
    for key in {builder.find(k) for k in (*user_keys, source, destination) if k}:
        node = builder.nodes[builder.find(key)]
        node.findings.append(finding)
        node.chunks |= chunks

    if user and source:
        builder.add_edge(user, source, "originates_from")
    if source and destination:
        builder.add_edge(source, destination, "connects_to", anomaly.protocol)
    if user and destination and not source:
        # Only when there is no source to route through — otherwise the graph
        # would assert a direct relationship the row does not describe.
        builder.add_edge(user, destination, "accesses")


def _anomaly_detail(anomaly: models.Anomaly) -> str | None:
    parts = []
    if anomaly.counted is not None:
        parts.append(f"{anomaly.counted} occurrence(s)")
    if anomaly.protocol:
        parts.append(anomaly.protocol)
    if anomaly.first_occurrence:
        parts.append(f"from {anomaly.first_occurrence}")
    if anomaly.last_occurrence:
        parts.append(f"to {anomaly.last_occurrence}")
    return " · ".join(parts) or None


def _add_event(builder: _Builder, event: models.Timeline, chunks: set[int]) -> None:
    key = builder.add_node(event.entity, classify(event.entity or ""))
    if key is None:
        return
    node = builder.nodes[builder.find(key)]
    node.findings.append(
        GraphFinding(
            section="timeline",
            item_id=event.id,
            title=event.event_name,
            detail=" · ".join(part for part in (event.time_stamp, event.duration) if part)
            or None,
            basis="source",
        )
    )
    node.chunks |= chunks


def _attach_scored_findings(
    db: Session,
    report: models.Report,
    builder: _Builder,
    evidence: dict[uuid.UUID, set[int]],
) -> None:
    """Give each node the severity of the findings that actually concern it.

    Anomalies and timeline events carry no severity of their own — the columns
    do not exist — so a node's risk has to come from the sections that do. Two
    ways in, and which one was used is recorded on the finding:

    * **evidence** — the finding cites a chunk that a finding this node came
      from also cites. Both were read out of the same log rows, which is the
      strongest link available without asking a model anything.
    * **mention** — the node's label appears verbatim in the finding's text. A
      weaker claim, and labelled as one, but an address written into an attack
      description is a real signal and dropping it would leave most graphs
      uncoloured.
    """
    scored: list[tuple[str, object, str | None, str | None, str | None]] = []
    for row in db.scalars(
        select(models.AttackType).where(models.AttackType.report_id == report.report_id)
    ):
        scored.append(
            ("attack_types", row.id, row.attack_name, row.risk_level, _text(row))
        )
    for row in db.scalars(
        select(models.RiskAssessment).where(
            models.RiskAssessment.report_id == report.report_id
        )
    ):
        scored.append(
            ("general_risk_assessment", row.id, row.risk_name, row.risk_level, _text(row))
        )
    for row in db.scalars(
        select(models.Vulnerability).where(
            models.Vulnerability.report_id == report.report_id
        )
    ):
        scored.append(
            # Vulnerabilities carry no severity column of their own — the CVE
            # would have to be looked up to get one — so they contribute a
            # finding to the node without contributing a colour.
            ("vulnerabilities", row.id, row.vulnerability_name, None, _text(row))
        )

    # Aliases are scanned too. A merged node is keyed on the display name, and
    # a finding is at least as likely to write the login: "Ana Silva" is the
    # node, "a.silva" is what the attack description says.
    mentions = {
        node.key: [
            pattern
            for pattern in (
                _mention_pattern(node.key),
                *(_mention_pattern(normalize(alias)) for alias in node.aliases),
            )
            if pattern is not None
        ]
        for node in builder.nodes.values()
    }

    for section, item_id, title, risk_level, text in scored:
        cited = evidence.get(item_id, set())
        haystack = (text or "").casefold()
        for node in builder.nodes.values():
            basis = None
            if cited and node.chunks & cited:
                basis = "evidence"
            elif any(pattern.search(haystack) for pattern in mentions.get(node.key, ())):
                basis = "mention"
            if basis is None:
                continue
            node.findings.append(
                GraphFinding(
                    section=section,
                    item_id=item_id,
                    title=title,
                    detail=None,
                    risk_level=risk_level,
                    basis=basis,
                )
            )


# Two characters is not an identifier, it is a coincidence waiting to match.
MIN_MENTION_LENGTH = 3


def _mention_pattern(key: str) -> re.Pattern | None:
    """Match a label as a whole identifier, never as a substring of a longer one.

    A plain `in` test makes `10.0.0.7` a mention of every finding that names
    `10.0.0.76`, which would attach a critical severity to the wrong host — the
    kind of wrong that looks completely plausible on a graph.

    The trailing lookahead rejects a dot only when a word character follows it,
    because a dot at the end of a sentence is punctuation and a dot in the
    middle of an address is not. Rejecting both — the obvious first version —
    means `10.0.0.2` is never matched in "Traffic to 10.0.0.2.", which is how
    most findings actually end.
    """
    if len(key) < MIN_MENTION_LENGTH:
        return None
    return re.compile(rf"(?<![\w.\-]){re.escape(key)}(?![\w\-])(?!\.\w)")


def _text(row) -> str:
    """Every free-text column on a finding, concatenated for the mention scan."""
    return " ".join(
        str(value)
        for value in vars(row).values()
        if isinstance(value, str)
    )


def _add_co_occurrence_edges(builder: _Builder) -> None:
    """Link entities whose findings were read out of the same log rows.

    This is what puts a timeline entity — which has no address and no user
    column — into the graph at all. It is a weaker claim than an anomaly's own
    columns and is drawn differently, but "these two were named in findings
    grounded in the same lines of the log" is a real relationship and it comes
    from Phase 10's citations rather than from guesswork.
    """
    by_chunk: dict[int, set[str]] = defaultdict(set)
    for node in builder.nodes.values():
        for chunk in node.chunks:
            by_chunk[chunk].add(node.key)

    for members in by_chunk.values():
        ordered = sorted(members)
        # A chunk naming half the report is not evidence of anything specific;
        # it is a chunk. Skipping those keeps the graph from turning into a
        # clique the moment one retrieval hit is shared widely.
        if len(ordered) > 6:
            continue
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                builder.add_edge(left, right, "co_occurs")


def _assemble(report: models.Report, builder: _Builder) -> AttackGraph:
    degree: dict[str, int] = defaultdict(int)
    for edge in builder.edges.values():
        degree[edge.source] += 1
        degree[edge.target] += 1

    nodes = []
    for node in builder.nodes.values():
        risk = _worst(node.findings)
        nodes.append(
            GraphNode(
                id=node.key,
                label=node.label or node.key,
                type=node.type,
                aliases=sorted(node.aliases),
                risk=risk,
                degree=degree.get(node.key, 0),
                observations=node.observations,
                findings=_rank(node.findings)[:MAX_FINDINGS_PER_NODE],
            )
        )

    total_nodes = len(nodes)
    total_edges = len(builder.edges)

    # Ranked by risk first, then by how connected they are: if something has to
    # be dropped it should be the isolated, unrated node, never the critical one.
    nodes.sort(
        key=lambda item: (-_rank_value(item.risk), -item.degree, -item.observations, item.label)
    )
    kept = nodes[:MAX_NODES]
    keys = {node.id for node in kept}
    edges = [
        edge
        for edge in builder.edges.values()
        if edge.source in keys and edge.target in keys
    ]
    risk_by_id = {node.id: node.risk for node in kept}
    for edge in edges:
        edge.risk = _worse(risk_by_id[edge.source], risk_by_id[edge.target])

    return AttackGraph(
        report_id=report.report_id,
        nodes=kept,
        edges=edges,
        total_nodes=total_nodes,
        total_edges=total_edges,
        truncated=total_nodes > len(kept),
    )


def _rank_value(risk: str) -> int:
    return SEVERITY_ORDER.index(risk) if risk in SEVERITY_ORDER else -1


def _worst(findings: list[GraphFinding]) -> str:
    levels = [bucket(f.risk_level) for f in findings if f.risk_level]
    if not levels:
        return UNKNOWN
    return max(levels, key=_rank_value)


def _worse(left: str, right: str) -> str:
    return left if _rank_value(left) >= _rank_value(right) else right


def _rank(findings: list[GraphFinding]) -> list[GraphFinding]:
    """Strongest claim first: worst severity, then evidence over mention."""
    strength = {"source": 2, "evidence": 1, "mention": 0}
    return sorted(
        findings,
        key=lambda f: (-_rank_value(bucket(f.risk_level)), -strength.get(f.basis, 0)),
    )
