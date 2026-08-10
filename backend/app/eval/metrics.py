"""The numbers, and exactly what each one is a ratio of.

Every rate here carries its denominator into the output, because a
hallucination rate with no denominator is unreadable: 0.0 over zero emitted
identifiers is not a good score, it is a model that declined to answer, and the
two must not print the same way.

Where a denominator is zero the rate is `None`, not `0.0` — the same rule this
project applies to unpriced LLM calls and unverified file integrity. "Nothing
to measure" is not "measured, and perfect".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.eval.harness import GoldenLabel
from app.eval.validators import ValidationResult
from app.schemas.report import ReportGenerationResult


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


@dataclass
class MatchResult:
    """Which golden labels were found, and how.

    **Two recalls, because one number could not honestly carry both meanings.**

    `matched` is coverage: the label appears somewhere in the report. `distinct`
    is coverage under a one-label-per-finding assignment. They differ when the
    model bundles — and on the first live run they differed a lot: three attack
    findings covered seven labels, because one of them was a campaign narrative
    whose description mentioned PowerShell, SMB, the beacon and the log clearing
    in passing.

    Neither is the "real" answer. Bundling a campaign into one narrative finding
    is defensible analysis, not an error; but scoring it as seven separate
    findings recalled would be flattering, and reporting only the strict number
    would penalise a good summary. So both are reported, and the gap between
    them is itself the interesting figure.
    """

    matched: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    distinct: list[str] = field(default_factory=list)
    # Findings not credited with any label under the distinct assignment. Not
    # automatically wrong — a model can spot something real the labeller did
    # not write down — so only the `must_not_report` list counts as an outright
    # false positive.
    unmatched_findings: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)


@dataclass
class Metrics:
    # --- Identifier correctness ---
    identifiers_emitted: int = 0
    invalid_identifiers: int = 0
    hallucination_rate: float | None = None
    issues_by_kind: dict[str, int] = field(default_factory=dict)

    # --- Grounding ---
    findings_total: int = 0
    findings_grounded: int = 0
    grounding_rate: float | None = None
    invalid_citations: int = 0
    citation_error_rate: float | None = None

    # --- Against the golden labels ---
    expected_total: int = 0
    matched_total: int = 0
    recall: float | None = None
    # Under a one-label-per-finding assignment. See `MatchResult`.
    distinct_total: int = 0
    distinct_recall: float | None = None
    precision: float | None = None
    false_positives: int = 0
    mitre_expected: int = 0
    mitre_agreed: int = 0
    mitre_agreement: float | None = None

    # --- Pipeline health ---
    sections_total: int = 0
    sections_succeeded: int = 0
    section_success_rate: float | None = None
    llm_calls: int = 0
    retries: int = 0
    retry_rate: float | None = None

    # --- Cost and latency ---
    total_tokens: int | None = None
    cost_usd: float | None = None
    generation_ms: float | None = None
    p95_call_ms: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _text_of(item) -> str:
    """Every string a finding carries, lower-cased, for label matching."""
    return " ".join(
        str(value) for value in item.storage_dump().values() if isinstance(value, str)
    ).casefold()


def match_labels(labels: list[GoldenLabel], items: list) -> MatchResult:
    """Match golden labels against findings, two ways. See `MatchResult`."""
    result = MatchResult()
    texts = [_text_of(item) for item in items]

    # Coverage: does the label appear anywhere at all.
    hits: dict[str, list[int]] = {}
    for label in labels:
        needles = [needle.casefold() for needle in label.match_any]
        found = [
            (index, sum(1 for needle in needles if needle in text))
            for index, text in enumerate(texts)
            if any(needle in text for needle in needles)
        ]
        hits[label.id] = [index for index, _ in found]
        (result.matched if found else result.missed).append(label.id)

    # Distinct: each finding may satisfy at most one label. Labels with the
    # fewest candidates are assigned first, so a label with exactly one
    # possible finding is not starved by a label that had alternatives.
    claimed: dict[int, str] = {}
    for label_id in sorted(hits, key=lambda key: len(hits[key])):
        for index in hits[label_id]:
            if index not in claimed:
                claimed[index] = label_id
                result.distinct.append(label_id)
                break

    result.unmatched_findings = [
        (items[index].storage_dump().get("attack_name")
         or items[index].storage_dump().get("anomaly_name")
         or f"item {index}")
        for index in range(len(items))
        if index not in claimed
    ]
    return result


def find_false_positives(items: list, forbidden: list[GoldenLabel]) -> list[str]:
    """Findings that report activity the golden set says is ordinary.

    Separate from "unmatched" on purpose. A model naming something the labeller
    did not think of may be right; a model calling `rlee` reading a PDF an
    attack is wrong, and a report that flags routine activity is one an analyst
    stops reading.
    """
    hits: list[str] = []
    for item in items:
        text = _text_of(item)
        for label in forbidden:
            if any(needle.casefold() in text for needle in label.match_any):
                hits.append(label.id)
                break
    return hits


def compute(
    result: ReportGenerationResult,
    validation: ValidationResult,
    *,
    expected_attacks: list[GoldenLabel],
    expected_anomalies: list[GoldenLabel],
    forbidden: list[GoldenLabel],
    sections_total: int,
) -> tuple[Metrics, MatchResult, MatchResult]:
    sections = result.sections

    attacks = match_labels(expected_attacks, list(sections.attack_types))
    anomalies = match_labels(expected_anomalies, list(sections.anomalies))

    findings = [
        item
        for name in ("attack_types", "general_risk_assessment", "vulnerabilities",
                     "anomalies", "timeline")
        for item in getattr(sections, name)
    ]
    grounded = len(findings) - result.ungrounded_findings

    false_positives = find_false_positives(list(sections.attack_types), forbidden)
    attacks.false_positives = false_positives

    expected_total = len(expected_attacks) + len(expected_anomalies)
    matched_total = len(attacks.matched) + len(anomalies.matched)
    distinct_total = len(attacks.distinct) + len(anomalies.distinct)
    # Precision is measured against the *attack* section only, and against the
    # findings that claim to be attacks: counting a timeline entry as a false
    # positive would penalise the model for doing what it was asked.
    reported_attacks = len(sections.attack_types)

    mitre_expected = 0
    mitre_agreed = 0
    for label in expected_attacks:
        if not label.mitre:
            continue
        mitre_expected += 1
        needles = [needle.casefold() for needle in label.match_any]
        for item in sections.attack_types:
            if any(needle in _text_of(item) for needle in needles):
                if (item.attack_mitre_technique_id or "").strip().upper() == label.mitre.upper():
                    mitre_agreed += 1
                break

    latencies = sorted(record.latency_ms for record in result.usage)
    tokens = [r.total_tokens for r in result.usage if r.total_tokens is not None]
    costs = [r.cost_usd for r in result.usage if r.cost_usd is not None]
    retries = sum(1 for r in result.usage if r.attempt > 1)

    metrics = Metrics(
        identifiers_emitted=validation.identifiers_emitted,
        invalid_identifiers=validation.invalid_identifiers,
        hallucination_rate=_rate(validation.invalid_identifiers, validation.identifiers_emitted),
        issues_by_kind=validation.by_kind(),
        findings_total=len(findings),
        findings_grounded=grounded,
        grounding_rate=_rate(grounded, len(findings)),
        invalid_citations=result.invalid_citations,
        citation_error_rate=_rate(
            result.invalid_citations, result.invalid_citations + len(result.evidence)
        ),
        expected_total=expected_total,
        matched_total=matched_total,
        recall=_rate(matched_total, expected_total),
        distinct_total=distinct_total,
        distinct_recall=_rate(distinct_total, expected_total),
        precision=_rate(reported_attacks - len(false_positives), reported_attacks),
        false_positives=len(false_positives),
        mitre_expected=mitre_expected,
        mitre_agreed=mitre_agreed,
        mitre_agreement=_rate(mitre_agreed, mitre_expected),
        sections_total=sections_total,
        sections_succeeded=sections_total - len(result.errors),
        section_success_rate=_rate(sections_total - len(result.errors), sections_total),
        llm_calls=len(result.usage),
        retries=retries,
        retry_rate=_rate(retries, len(result.usage)),
        total_tokens=sum(tokens) if tokens else None,
        cost_usd=round(sum(costs), 6) if costs else None,
        generation_ms=result.generation_ms,
        p95_call_ms=_percentile(latencies, 0.95),
    )
    return metrics, attacks, anomalies


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    # Nearest-rank. With five samples an interpolated p95 invents a number
    # between two real measurements; the rank is a measurement that happened.
    index = min(len(values) - 1, max(0, round(fraction * len(values)) - 1))
    return round(values[index], 2)
