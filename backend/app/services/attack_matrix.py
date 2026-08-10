"""The MITRE ATT&CK matrix, and what this system's reports put on it.

Two halves that must not be confused with each other:

* **The grid** is MITRE's. It comes from the catalogue vendored in Phase 11 —
  the same pinned download the hallucination validator reads — so the matrix
  and the validator can never disagree about what ATT&CK contains. It does not
  depend on the caller, the database, or anything this application generated.
* **The detections** are ours, and they are model output. A technique id in
  `attack_types` is a claim, not a fact, and Phase 11 exists because those
  claims are sometimes wrong.

**How a bad identifier is handled.** The requirement was to decide, so:

1. An id that does not exist, is not shaped like one, or names a technique
   ATT&CK has **retired** gets no cell. It cannot have one — there is no column
   to put it in — and inventing a placement would be the fabrication all over
   again, in our own UI. These come back in `unplaced`, with the validator's
   sentence, and the page shows them beside the matrix.
2. An id that is real and current but was given the **wrong name** by the model
   *is* placed, marked `verified: false`, and labelled with the *catalogue's*
   name. The detection is real; the model's description of it is not.

Neither is dropped. Dropping either would make the matrix look cleaner than
the output behind it — the same failure as an empty section reported as a
success, and the reason the grounding work counts ungrounded findings instead
of hiding them.

Aggregation is one query per call, and the grouping is done in Python rather
than in SQL. That is a deliberate exception to the `analytics.py` rule: the
verdict on each row is a lookup in a JSON catalogue, which Postgres cannot do,
and the result is a nested collection, which a `GROUP BY` cannot return. The
row count is bounded by findings-per-report, not by log volume.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.api.deps import is_admin
from app.db import models
from app.eval import catalog, validators
from app.schemas.attack import (
    Detection,
    DetectionSet,
    DetectionSource,
    MatrixGrid,
    MatrixTactic,
    MatrixTechnique,
    UnplacedDetection,
)

# Navigator refuses a layer whose `versions.layer` it does not know, so this
# tracks the vendored spec rather than being chosen. See `data/SOURCES.md`.
LAYER_FORMAT_VERSION = "4.5"
# The spec's own requirement is "at least 4.9.0". Claiming the newest Navigator
# release would be asserting compatibility with something never tested here.
NAVIGATOR_MIN_VERSION = "4.9.0"
ATTACK_DOMAIN = "enterprise-attack"

# A cell lists the reports behind it; a technique seen in two hundred reports
# does not need two hundred rows in a tooltip. `count` stays the true total.
MAX_SOURCES = 25

# Explicit colour for a placed-but-unverified cell. An explicit colour beats
# the gradient in Navigator, which is the point: "we could not stand behind
# this one" must not read as "this one was seen once".
UNVERIFIED_COLOR = "#b0b0b0"
GRADIENT = ["#fff0d9", "#f0a848", "#a63603"]


def attack_version() -> str:
    return catalog.source_info()["mitre_attack"]["version"]


# --- The grid -------------------------------------------------------------


def matrix_grid() -> MatrixGrid:
    """The published enterprise matrix: 14 columns, parents with their children.

    Sub-techniques are nested under their parent rather than given cells of
    their own. 679 placed techniques against 211 parents is the difference
    between something an analyst can scan and a wall of text — and it is how
    MITRE draws it too.
    """
    tactics: list[MatrixTactic] = []
    placed: set[str] = set()

    for tactic in catalog.tactics():
        members = catalog.techniques_for(tactic.shortname)
        children: dict[str, list[MatrixTechnique]] = defaultdict(list)
        for item in members:
            if item.sub_technique:
                children[item.parent_id].append(
                    MatrixTechnique(
                        technique_id=item.technique_id,
                        name=item.name,
                        sub_technique=True,
                    )
                )

        cells = [
            MatrixTechnique(
                technique_id=item.technique_id,
                name=item.name,
                sub_technique=False,
                sub_techniques=sorted(
                    children.get(item.technique_id, []),
                    key=lambda child: child.technique_id,
                ),
            )
            for item in members
            if not item.sub_technique
        ]
        cells.sort(key=lambda cell: cell.name.lower())
        placed.update(cell.technique_id for cell in cells)
        placed.update(
            child.technique_id for cell in cells for child in cell.sub_techniques
        )

        tactics.append(
            MatrixTactic(
                tactic_id=tactic.tactic_id,
                shortname=tactic.shortname,
                name=tactic.name,
                description=tactic.description,
                techniques=cells,
            )
        )

    return MatrixGrid(
        attack_version=attack_version(),
        tactics=tactics,
        technique_count=len(placed),
    )


# --- Detections -----------------------------------------------------------


@dataclass
class _Bucket:
    """One technique across however many reports named it."""

    count: int = 0
    sources: list[DetectionSource] = field(default_factory=list)

    def add(self, source: DetectionSource) -> None:
        self.count += 1
        if len(self.sources) < MAX_SOURCES:
            self.sources.append(source)


def _scope(statement: Select, user: models.Users) -> Select:
    """An analyst sees their own reports, an admin sees every report.

    The same rule as `/reports` and the dashboard. The aggregate matrix reads
    across every report a caller can see, which makes it exactly the endpoint
    where a missing scope leaks one tenant's findings into another's.
    """
    if is_admin(user):
        return statement
    return statement.where(models.Report.user_id == user.user_id)


def _rows(db: Session, user: models.Users, report_id: uuid.UUID | None):
    statement = (
        select(
            models.AttackType.attack_mitre_technique_id,
            models.AttackType.attack_mitre_technique_name,
            models.AttackType.attack_name,
            models.AttackType.risk_level,
            models.Report.report_id,
            models.Report.report_name,
            models.Report.generated_at,
        )
        .join(models.Report, models.AttackType.report_id == models.Report.report_id)
        .order_by(models.Report.generated_at.desc(), models.AttackType.id)
    )
    if report_id is not None:
        statement = statement.where(models.Report.report_id == report_id)
    return db.execute(_scope(statement, user)).all()


def _reports_in_scope(db: Session, user: models.Users, report_id: uuid.UUID | None) -> int:
    """How many reports the matrix was computed over — the denominator.

    Counted separately rather than taken from the joined rows, because a report
    that named no technique still had its log read. "3 techniques across 44
    reports" and "3 techniques across 3 reports" say different things, and the
    join can only ever produce the second.
    """
    statement = select(func.count()).select_from(models.Report)
    if report_id is not None:
        statement = statement.where(models.Report.report_id == report_id)
    return db.execute(_scope(statement, user)).scalar_one()


def detections(
    db: Session,
    user: models.Users,
    *,
    report_id: uuid.UUID | None = None,
) -> DetectionSet:
    """Every technique the caller's reports named, sorted into placed and not."""
    placed: dict[str, _Bucket] = defaultdict(_Bucket)
    unplaced: dict[tuple[str, str], _Bucket] = defaultdict(_Bucket)
    # Recorded per key so an unplaced entry keeps the validator's own wording.
    verdicts: dict[str, tuple[bool, str | None]] = {}
    details: dict[tuple[str, str], str] = {}
    emitted = 0

    for row in _rows(db, user, report_id):
        technique_id = (row.attack_mitre_technique_id or "").strip()
        if not technique_id:
            # Null is the instructed answer when the model cannot identify a
            # technique, and obeying the instruction is not a detection.
            continue
        emitted += 1

        source = DetectionSource(
            report_id=row.report_id,
            report_name=row.report_name,
            generated_at=row.generated_at,
            attack_name=row.attack_name,
            risk_level=row.risk_level,
        )

        issues = validators.check_technique(row)
        blocking = next(
            (issue for issue in issues if issue.kind in _CANNOT_PLACE), None
        )
        known = catalog.technique(technique_id)
        if blocking is None and known is not None and not known.tactics:
            # Real, current, and MITRE places it in no tactic. Rare, but a cell
            # has to belong to a column; there is nowhere to draw this.
            blocking = validators.Issue(
                kind="mitre_unplaced",
                section="attack_types",
                item_index=0,
                value=technique_id,
                detail=f"{technique_id} is not assigned to any ATT&CK tactic",
            )

        if blocking is not None:
            key = (blocking.value, blocking.kind)
            unplaced[key].add(source)
            details[key] = blocking.detail
            continue

        canonical = known.technique_id  # normalised case, from the catalogue
        placed[canonical].add(source)
        mismatch = next(
            (issue for issue in issues if issue.kind == "mitre_name_mismatch"), None
        )
        if mismatch is not None:
            verdicts[canonical] = (False, mismatch.detail)
        else:
            verdicts.setdefault(canonical, (True, None))

    return DetectionSet(
        attack_version=attack_version(),
        scope="report" if report_id is not None else "all",
        report_id=report_id,
        detections=_as_detections(placed, verdicts),
        unplaced=[
            UnplacedDetection(
                value=value,
                reason=kind,
                detail=details[(value, kind)],
                count=bucket.count,
                sources=bucket.sources,
            )
            for (value, kind), bucket in sorted(
                unplaced.items(), key=lambda item: (-item[1].count, item[0])
            )
        ],
        reports_considered=_reports_in_scope(db, user, report_id),
        techniques_emitted=emitted,
    )


# Kinds that leave a finding with nowhere to sit on the matrix. `mitre_retired`
# is here because MITRE does not draw deprecated techniques on the published
# matrix — the id was real, which is why it is reported rather than counted as
# a hallucination, but there is no cell for it.
_CANNOT_PLACE = {"mitre_malformed", "mitre_unknown", "mitre_retired"}


def _as_detections(
    placed: dict[str, _Bucket],
    verdicts: dict[str, tuple[bool, str | None]],
) -> list[Detection]:
    result = []
    for technique_id, bucket in placed.items():
        known = catalog.technique(technique_id)
        assert known is not None  # only resolvable ids reach this dict
        verified, issue = verdicts[technique_id]
        result.append(
            Detection(
                technique_id=technique_id,
                name=known.name,
                tactics=list(known.tactics),
                sub_technique=known.sub_technique,
                parent_id=known.parent_id,
                count=bucket.count,
                verified=verified,
                issue=issue,
                sources=bucket.sources,
            )
        )
    result.sort(key=lambda item: (-item.count, item.technique_id))
    return result


# --- Navigator layer ------------------------------------------------------


def navigator_layer(found: DetectionSet, *, name: str) -> dict:
    """Render a detection set as an ATT&CK Navigator layer file.

    The format is MITRE's, vendored from their published spec rather than
    approximated — see `eval/vendor.py`. Two decisions worth stating:

    * **`tactic` is deliberately omitted from every entry.** A finding says a
      technique was observed; it does not say under which tactic. Navigator
      reads a missing `tactic` as "annotate this technique under every column
      it appears in", which is precisely what is known. Pinning each detection
      to one column would put a guess in a file an analyst will read as data.
    * **Unplaced identifiers are not in `techniques`** — they have no cell, and
      a layer is a set of cells — but their count and values go in the layer
      description and metadata, so the file cannot be read as a clean run.
    """
    top = max((item.count for item in found.detections), default=0)
    unplaced_note = (
        "; ".join(f"{item.value} ({item.reason}, ×{item.count})" for item in found.unplaced)
        or "none"
    )

    techniques = []
    for item in found.detections:
        entry: dict = {
            "techniqueID": item.technique_id,
            "score": item.count,
            "enabled": True,
            "comment": _comment(item),
            "metadata": [
                {"name": "Detections", "value": str(item.count)},
                {"name": "Verified", "value": "yes" if item.verified else "no"},
                *(
                    [{"name": "Reports", "value": _report_names(item)}]
                    if item.sources
                    else []
                ),
            ],
        }
        if not item.verified:
            entry["color"] = UNVERIFIED_COLOR
        techniques.append(entry)

    return {
        "name": name,
        "versions": {
            # Navigator wants the major version, not the point release.
            "attack": found.attack_version.split(".")[0],
            "navigator": NAVIGATOR_MIN_VERSION,
            "layer": LAYER_FORMAT_VERSION,
        },
        "domain": ATTACK_DOMAIN,
        "description": (
            f"AIPCC detections across {found.reports_considered} report(s). "
            f"{len(found.detections)} technique(s) placed from "
            f"{found.techniques_emitted} emitted identifier(s). "
            f"Unplaced: {unplaced_note}."
        ),
        # Descending by score: the technique seen most often reads first.
        "sorting": 3,
        "layout": {
            "layout": "side",
            "showID": True,
            "showName": True,
            "showAggregateScores": False,
            "countUnscored": False,
            "aggregateFunction": "average",
            # Open a sub-technique only where there is an annotation on it —
            # which is exactly the set this file annotates.
            "expandedSubtechniques": "annotated",
        },
        "hideDisabled": False,
        "techniques": techniques,
        "gradient": {
            "colors": GRADIENT,
            "minValue": 0,
            # maxValue must be strictly greater than minValue, and a layer with
            # a single detection would otherwise emit 0..0 and fail to load.
            "maxValue": max(top, 1),
        },
        "legendItems": [
            {"label": "Verified against ATT&CK", "color": GRADIENT[-1]},
            {"label": "Name did not match ATT&CK", "color": UNVERIFIED_COLOR},
        ],
        "metadata": [
            {"name": "Generated by", "value": "AIPCC"},
            {"name": "ATT&CK version", "value": found.attack_version},
            {"name": "Reports", "value": str(found.reports_considered)},
            {"name": "Unplaced identifiers", "value": str(len(found.unplaced))},
        ],
        "showTacticRowBackground": False,
        "tacticRowBackground": "#dddddd",
        "selectTechniquesAcrossTactics": True,
        "selectSubtechniquesWithParent": False,
        "selectVisibleTechniques": False,
    }


def _comment(item: Detection) -> str:
    lines = [f"Observed in {item.count} AIPCC report(s)."]
    if not item.verified and item.issue:
        lines.append(f"UNVERIFIED — {item.issue}")
    named = sorted({source.attack_name for source in item.sources if source.attack_name})
    if named:
        lines.append("Findings: " + ", ".join(named))
    return " ".join(lines)


def _report_names(item: Detection) -> str:
    return ", ".join(dict.fromkeys(source.report_name for source in item.sources))
