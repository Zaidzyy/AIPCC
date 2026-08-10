"""Checks applied to one generated report.

Each validator answers a question about the model's output that can be settled
without asking the model anything:

* **MITRE** — does the technique id exist, and does the name the model gave it
  match the official one? The second half is the interesting one. `T1022`
  labelled "Remote Code Execution via Web Application" is a *real id with the
  wrong name*, which no format check catches and which reads perfectly
  plausibly to anyone who does not have the catalogue open.
* **CWE** — does the weakness exist in the vendored catalogue?
* **CVE** — is it well formed? Existence is deliberately *not* checked: the CVE
  list is unbounded and grows daily, so verifying it needs a network call, and
  a quality gate that needs the internet fails on a bad day and is deleted on
  the next. The harness says which of the two it checked rather than implying
  the stronger one.
* **Citations** — does every cited chunk resolve? That check lives in
  `services/grounding.py` and runs during generation; this module reads its
  counters so one report carries every number.

A finding can fail several checks, and each failure is recorded separately with
enough context to be read by a person. `Issue.detail` is written to be pasted
into a bug report, not decoded.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from app.eval import catalog
from app.schemas.report import ReportSections

# CVE-YYYY-NNNN, four to seven digits in the sequence part.
CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,7}$")
# T1234 or T1234.001.
TECHNIQUE_PATTERN = re.compile(r"^T\d{4}(\.\d{3})?$")
CWE_PATTERN = re.compile(r"^CWE-\d+$")


@dataclass(frozen=True)
class Issue:
    """One thing wrong with one finding."""

    kind: str
    section: str
    item_index: int
    value: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - for human output
        return f"{self.section}[{self.item_index}] {self.kind}: {self.detail}"


@dataclass
class ValidationResult:
    issues: list[Issue] = field(default_factory=list)
    # Denominators. A rate needs both halves, and reporting "3 bad techniques"
    # without "out of how many" is the kind of number that means nothing.
    techniques_emitted: int = 0
    cves_emitted: int = 0
    cwes_emitted: int = 0

    @property
    def identifiers_emitted(self) -> int:
        return self.techniques_emitted + self.cves_emitted + self.cwes_emitted

    @property
    def invalid_identifiers(self) -> int:
        return sum(1 for issue in self.issues if issue.kind != "mitre_retired")

    def by_kind(self) -> dict[str, int]:
        return dict(Counter(issue.kind for issue in self.issues))


def validate_sections(sections: ReportSections) -> ValidationResult:
    """Run every identifier check over a whole report."""
    result = ValidationResult()

    for index, attack in enumerate(sections.attack_types):
        _check_technique(result, index, attack)

    for index, vulnerability in enumerate(sections.vulnerabilities):
        _check_cve(result, index, vulnerability)
        _check_cwe(result, index, vulnerability)

    return result


def _check_technique(result: ValidationResult, index: int, attack) -> None:
    technique_id = (attack.attack_mitre_technique_id or "").strip()
    if not technique_id:
        # Null is the instructed answer when the model cannot identify one, and
        # obeying the instruction is not an error.
        return

    result.techniques_emitted += 1
    section = "attack_types"

    if not TECHNIQUE_PATTERN.match(technique_id.upper()):
        result.issues.append(
            Issue(
                kind="mitre_malformed",
                section=section,
                item_index=index,
                value=technique_id,
                detail=f"{technique_id!r} is not shaped like a technique id (T1234 or T1234.001)",
            )
        )
        return

    known = catalog.technique(technique_id)
    if known is None:
        result.issues.append(
            Issue(
                kind="mitre_unknown",
                section=section,
                item_index=index,
                value=technique_id,
                detail=(
                    f"{technique_id} does not exist in ATT&CK Enterprise "
                    f"({catalog.technique_count()} techniques)"
                ),
            )
        )
        return

    claimed = (attack.attack_mitre_technique_name or "").strip()
    if claimed and not _names_match(claimed, known.name):
        # The interesting failure: a real id with an invented name. No format
        # check catches it and it reads perfectly plausibly.
        result.issues.append(
            Issue(
                kind="mitre_name_mismatch",
                section=section,
                item_index=index,
                value=technique_id,
                detail=f"{technique_id} is {known.name!r}, not {claimed!r}",
            )
        )

    if known.retired:
        # Recorded, but excluded from `invalid_identifiers`: the model did not
        # invent this, ATT&CK retired it.
        result.issues.append(
            Issue(
                kind="mitre_retired",
                section=section,
                item_index=index,
                value=technique_id,
                detail=f"{technique_id} ({known.name}) is deprecated or revoked in ATT&CK",
            )
        )


def _check_cve(result: ValidationResult, index: int, vulnerability) -> None:
    cve_id = (vulnerability.cve_id or "").strip()
    if not cve_id:
        return

    result.cves_emitted += 1
    if not CVE_PATTERN.match(cve_id.upper()):
        result.issues.append(
            Issue(
                kind="cve_malformed",
                section="vulnerabilities",
                item_index=index,
                value=cve_id,
                detail=f"{cve_id!r} is not shaped like CVE-YYYY-NNNN",
            )
        )


def _check_cwe(result: ValidationResult, index: int, vulnerability) -> None:
    cwe_id = (vulnerability.cwe_id or "").strip()
    if not cwe_id:
        return

    result.cwes_emitted += 1
    section = "vulnerabilities"

    if not CWE_PATTERN.match(cwe_id.upper()):
        result.issues.append(
            Issue(
                kind="cwe_malformed",
                section=section,
                item_index=index,
                value=cwe_id,
                detail=f"{cwe_id!r} is not shaped like CWE-NNN",
            )
        )
        return

    if catalog.weakness(cwe_id) is None:
        result.issues.append(
            Issue(
                kind="cwe_unknown",
                section=section,
                item_index=index,
                value=cwe_id,
                detail=(
                    f"{cwe_id} does not exist in the CWE catalogue "
                    f"({catalog.weakness_count()} weaknesses)"
                ),
            )
        )


_PUNCTUATION = re.compile(r"[^a-z0-9 ]+")


def _names_match(claimed: str, official: str) -> bool:
    """Compare a claimed technique name with the official one, leniently.

    Case, punctuation and whitespace are ignored, because "Brute-Force" and
    "Brute Force" are the same answer typed differently and failing on that
    would drown the real mismatches in noise.

    A claimed name that *contains* the official one also passes — models write
    "Brute Force (Password Guessing)" — but the reverse does not: "Brute" is
    not an acceptable rendering of "Brute Force Attack", because a substring of
    a technique name is how a wrong-but-adjacent technique gets accepted.
    """
    left = _PUNCTUATION.sub(" ", claimed.casefold()).split()
    right = _PUNCTUATION.sub(" ", official.casefold()).split()
    if not right:
        return True
    if left == right:
        return True
    # The official name appearing as a contiguous run inside the claim.
    return any(
        left[start : start + len(right)] == right
        for start in range(0, max(0, len(left) - len(right) + 1))
    )
