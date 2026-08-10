"""The ATT&CK matrix: its grid, and what a report detected on it.

Three shapes, and the distinction between the first two is the whole point of
the phase:

* `MatrixGrid` — the published matrix. Columns and cells straight from the
  vendored catalogue, identical for every caller, cacheable forever.
* `Detection` — a technique *this* report named, joined onto that grid.
* `UnplacedDetection` — a technique this report named that **cannot** be joined
  onto it, and why. These are the ones that matter: an identifier the model
  invented has no cell to sit in, and quietly dropping it would let the matrix
  claim a clean run over output that was not clean.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# --- The grid -------------------------------------------------------------


class MatrixTechnique(BaseModel):
    """One cell of the published matrix."""

    technique_id: str
    name: str
    sub_technique: bool
    # Present on parents only, and empty for a technique with none. The UI
    # collapses these under the parent rather than giving each its own cell:
    # 679 placed techniques against 211 parents is the difference between a
    # matrix and a wall.
    sub_techniques: list[MatrixTechnique] = Field(default_factory=list)


class MatrixTactic(BaseModel):
    """One column."""

    tactic_id: str
    shortname: str
    name: str
    description: str = ""
    techniques: list[MatrixTechnique] = Field(default_factory=list)


class MatrixGrid(BaseModel):
    attack_version: str
    tactics: list[MatrixTactic]
    technique_count: int


# --- What was detected ----------------------------------------------------


class DetectionSource(BaseModel):
    """One report that named this technique, and what it called it."""

    report_id: uuid.UUID
    report_name: str
    generated_at: datetime
    attack_name: str | None = None
    risk_level: str | None = None


class Detection(BaseModel):
    """A technique named by at least one report, placed on the matrix."""

    technique_id: str
    # The catalogue's name, always — never the model's. The two disagreeing is
    # exactly the `mitre_name_mismatch` case below, and rendering the model's
    # wording on a matrix cell would print a fabrication as a label.
    name: str
    tactics: list[str]
    sub_technique: bool
    parent_id: str
    count: int
    verified: bool
    # Populated only when `verified` is false: the validator's own sentence.
    issue: str | None = None
    sources: list[DetectionSource] = Field(default_factory=list)


class UnplacedDetection(BaseModel):
    """A technique the model emitted that has no cell on the matrix.

    Either the identifier does not exist, is not shaped like one, or names a
    technique ATT&CK has retired and no longer draws. Reported beside the
    matrix rather than on it — see `services/attack_matrix.py` for why these
    are shown at all instead of being dropped.
    """

    value: str
    reason: str
    detail: str
    count: int
    sources: list[DetectionSource] = Field(default_factory=list)


class DetectionSet(BaseModel):
    attack_version: str
    scope: str  # "report" | "all"
    report_id: uuid.UUID | None = None
    detections: list[Detection] = Field(default_factory=list)
    unplaced: list[UnplacedDetection] = Field(default_factory=list)
    # Denominators, so a rate on this page is never computed in the browser.
    reports_considered: int = 0
    techniques_emitted: int = 0
