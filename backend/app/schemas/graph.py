"""The attack graph: entities named in one report, and how they relate.

Everything here is derived from rows this system already stores — the typed
columns on `anomalies` and `timeline_events`, plus the citations Phase 10
recorded. There is no second LLM pass: a graph produced by asking the model to
extract entities would be a second set of claims to validate, and this project
already has one.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

# user | host | process | file | entity
#
# `entity` is the honest fallback and not a fifth category anybody wanted: the
# timeline's `entity` column is free text, so "Unauthorised user" and "System"
# arrive alongside `10.14.2.37` and `powershell.exe`. Filing those under `user`
# because three of the four types are taken would be a guess rendered as a fact.
NodeType = str


class GraphFinding(BaseModel):
    """One finding that touches a node, and why it is attached to it."""

    section: str
    item_id: uuid.UUID | None = None
    title: str | None = None
    detail: str | None = None
    risk_level: str | None = None
    # evidence | mention | source — how this finding reached this node. Shown
    # in the UI, because "the model wrote this IP in its description" and "this
    # finding cites the same log rows" are different strengths of claim.
    basis: str


class GraphNode(BaseModel):
    id: str
    label: str
    type: NodeType
    # Other spellings of the same entity that were merged into this node, and
    # the reason each merge was allowed. Always shown: a merge is a claim.
    aliases: list[str] = Field(default_factory=list)
    risk: str = "unknown"
    degree: int = 0
    observations: int = 0
    findings: list[GraphFinding] = Field(default_factory=list)


class GraphEdge(BaseModel):
    source: str
    target: str
    # originates_from | connects_to | accesses | co_occurs
    kind: str
    label: str | None = None
    weight: int = 1
    risk: str = "unknown"


class AttackGraph(BaseModel):
    report_id: uuid.UUID
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    # Denominators and honesty about what was left out. A graph that silently
    # drops nodes to stay readable is a graph that lies about the report.
    total_nodes: int = 0
    total_edges: int = 0
    truncated: bool = False
    # Why there is nothing to draw, when there is nothing to draw.
    empty_reason: str | None = None
