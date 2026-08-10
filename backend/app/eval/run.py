"""The evaluation runner.

    python -m app.eval.run                  # replay the recorded fixtures
    python -m app.eval.run --live           # call the configured provider
    python -m app.eval.run --live --record  # ...and save the responses as fixtures
    python -m app.eval.run --gate           # replay, and exit non-zero on regression

Produces machine-readable JSON at `app/eval/results/latest.json` and a human
summary on stdout. Both carry the mode, the catalogue versions and every
denominator, so a set of numbers can never be read without knowing what they
were measured against.

The gate replays. See `replay.py` for why, and for exactly what that does and
does not prove.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.eval import catalog, harness
from app.eval import metrics as metrics_module
from app.eval.replay import RecordingProvider, ReplayProvider
from app.eval.validators import validate_sections
from app.services.llm import LLMProvider, get_llm_provider
from app.services.report import SECTION_SPECS, generate_report

RESULTS_DIR = Path(__file__).parent / "results"
LATEST = RESULTS_DIR / "latest.json"


def _provider(
    live: bool, record: bool, interval: float
) -> tuple[LLMProvider, RecordingProvider | None]:
    if not live:
        return ReplayProvider(), None
    real = get_llm_provider()
    if record:
        recorder = RecordingProvider(real, min_interval_seconds=interval)
        return recorder, recorder
    return real, None


async def evaluate(*, live: bool, record: bool, interval: float = 20.0) -> dict:
    provider, recorder = _provider(live, record, interval)

    result = await generate_report(
        harness.GOLDEN_DOCUMENT_ID,
        provider=provider,
        retriever=harness.golden_retriever,
    )
    validation = validate_sections(result.sections)

    computed, attacks, anomalies = metrics_module.compute(
        result,
        validation,
        expected_attacks=harness.expected_attacks(),
        expected_anomalies=harness.expected_anomalies(),
        forbidden=harness.must_not_report(),
        sections_total=len(SECTION_SPECS),
    )

    if recorder is not None:
        path = recorder.save()
        print(f"recorded {len(recorder.interactions)} interactions -> {path}")

    return {
        "run": {
            # The single most important field in this file. A replayed number
            # describes the fixtures; only a live number describes a model.
            "mode": "live" if live else "replay",
            "provider": f"{provider.name}:{provider.model}",
            "recorded_from": getattr(provider, "recorded_from", None),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "golden_log": harness.GOLDEN_LOG.name,
            "golden_chunks": len(harness.golden_chunks()),
            "thresholds": {
                "max_hallucination_rate": settings.eval_max_hallucination_rate,
                "min_grounding_rate": settings.eval_min_grounding_rate,
                "min_section_success_rate": settings.eval_min_section_success_rate,
                "min_detected_issues": settings.eval_min_detected_issues,
            },
        },
        # Emitted with every run so numbers can never be read without the
        # catalogue versions they were computed against.
        "catalogues": catalog.source_info(),
        "metrics": computed.as_dict(),
        "attacks": asdict(attacks),
        "anomalies": asdict(anomalies),
        "identifier_issues": [
            {
                "kind": issue.kind,
                "section": issue.section,
                "item": issue.item_index,
                "value": issue.value,
                "detail": issue.detail,
            }
            for issue in validation.issues
        ],
        "section_errors": [
            {"section": e.section, "stage": e.stage, "detail": e.detail} for e in result.errors
        ],
    }


def check_gate(payload: dict) -> list[str]:
    """Thresholds from config. Returns the list of breaches, empty if clean."""
    m = payload["metrics"]
    breaches: list[str] = []

    hallucination = m["hallucination_rate"]
    if hallucination is not None and hallucination > settings.eval_max_hallucination_rate:
        breaches.append(
            f"hallucination rate {hallucination:.1%} exceeds "
            f"{settings.eval_max_hallucination_rate:.1%} "
            f"({m['invalid_identifiers']}/{m['identifiers_emitted']} identifiers)"
        )

    grounding = m["grounding_rate"]
    if grounding is not None and grounding < settings.eval_min_grounding_rate:
        breaches.append(
            f"grounding rate {grounding:.1%} is below "
            f"{settings.eval_min_grounding_rate:.1%} "
            f"({m['findings_grounded']}/{m['findings_total']} findings)"
        )

    sections = m["section_success_rate"]
    if sections is not None and sections < settings.eval_min_section_success_rate:
        breaches.append(
            f"section success rate {sections:.1%} is below "
            f"{settings.eval_min_section_success_rate:.1%}"
        )

    detected = sum(m.get("issues_by_kind", {}).values())
    if detected < settings.eval_min_detected_issues:
        breaches.append(
            f"the validators detected {detected} identifier issues, below the "
            f"{settings.eval_min_detected_issues} the committed fixture is known to "
            "contain — a validator has stopped catching something"
        )

    # A run that emitted no identifiers at all scores a `None` hallucination
    # rate, which passes every threshold above by having nothing to be wrong
    # about. Refusing to answer is not a passing grade.
    if m["identifiers_emitted"] == 0:
        breaches.append("no identifiers were emitted at all — nothing was measured")
    if m["findings_total"] == 0:
        breaches.append("no findings were produced at all — nothing was measured")

    return breaches


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _num(value) -> str:
    return "—" if value is None else str(value)


def _money(value: float | None) -> str:
    return "—" if value is None else f"${value:.5f}"


def _ms(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f} ms"


def summarize(payload: dict) -> str:
    m = payload["metrics"]
    run = payload["run"]
    attack_catalogue = payload["catalogues"]["mitre_attack"]
    cwe_catalogue = payload["catalogues"]["cwe"]

    lines = [
        "",
        "AIPCC evaluation",
        "=" * 64,
        f"  mode          {run['mode']}"
        + (f"  (fixtures recorded from {run['recorded_from']})" if run["recorded_from"] else ""),
        f"  provider      {run['provider']}",
        f"  golden log    {run['golden_log']} ({run['golden_chunks']} chunks)",
        f"  catalogues    ATT&CK v{attack_catalogue['version']}, CWE v{cwe_catalogue['version']}",
        "",
        "  Correctness of identifiers",
        f"    hallucination rate     {_pct(m['hallucination_rate'])}"
        f"   ({m['invalid_identifiers']}/{m['identifiers_emitted']} emitted)",
    ]
    for kind, count in sorted(m["issues_by_kind"].items()):
        lines.append(f"      {kind:<22} {count}")

    lines += [
        "",
        "  Grounding",
        f"    grounding rate         {_pct(m['grounding_rate'])}"
        f"   ({m['findings_grounded']}/{m['findings_total']} findings cite real content)",
        f"    fabricated citations   {m['invalid_citations']}"
        f"   ({_pct(m['citation_error_rate'])} of citations made)",
        "",
        "  Against the golden labels",
        f"    recall (coverage)      {_pct(m['recall'])}"
        f"   ({m['matched_total']}/{m['expected_total']} labels appear in the report)",
        f"    recall (distinct)      {_pct(m['distinct_recall'])}"
        f"   ({m['distinct_total']}/{m['expected_total']} have a finding of their own)",
        f"    precision              {_pct(m['precision'])}"
        f"   ({m['false_positives']} reported benign activity as an attack)",
        f"    MITRE agreement        {_pct(m['mitre_agreement'])}"
        f"   ({m['mitre_agreed']}/{m['mitre_expected']} matched the labeller's technique)",
        "",
        "  Pipeline",
        f"    section success        {_pct(m['section_success_rate'])}"
        f"   ({m['sections_succeeded']}/{m['sections_total']})",
        f"    retry rate             {_pct(m['retry_rate'])}"
        f"   ({m['retries']}/{m['llm_calls']} calls)",
        f"    tokens                 {_num(m['total_tokens'])}",
        f"    cost                   {_money(m['cost_usd'])}",
        f"    generation             {_ms(m['generation_ms'])}"
        f"   (p95 call {_ms(m['p95_call_ms'])})",
    ]

    missed = payload["attacks"]["missed"] + payload["anomalies"]["missed"]
    if missed:
        lines += ["", "  Missed: " + ", ".join(missed)]
    if payload["attacks"]["false_positives"]:
        lines += ["  Reported as attacks but labelled benign: "
                  + ", ".join(payload["attacks"]["false_positives"])]
    if payload["identifier_issues"]:
        lines += ["", "  Identifier issues:"]
        lines += [f"    - {issue['detail']}" for issue in payload["identifier_issues"]]
    if payload["section_errors"]:
        lines += ["", "  Section failures:"]
        lines += [
            f"    - {e['section']} ({e['stage']}): {e['detail']}"
            for e in payload["section_errors"]
        ]

    if run["mode"] == "replay":
        lines += [
            "",
            "  NOTE: replayed. These numbers describe the recorded fixtures and the",
            "  harness that scores them — not the current model. Run --live to",
            "  measure a model.",
        ]
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="call the configured provider")
    parser.add_argument("--record", action="store_true", help="save responses as fixtures")
    parser.add_argument("--gate", action="store_true", help="exit non-zero on a threshold breach")
    parser.add_argument("--json", action="store_true", help="print JSON only")
    parser.add_argument(
        "--record-interval",
        type=float,
        default=20.0,
        help=(
            "seconds between recorded calls. Free provider tiers limit input "
            "tokens per minute, and five full-log prompts at once trips them; "
            "raise this if recording returns RESOURCE_EXHAUSTED."
        ),
    )
    parser.add_argument("--out", type=Path, default=LATEST)
    args = parser.parse_args(argv)

    if args.record and not args.live:
        parser.error("--record requires --live: there is nothing to record from a replay")

    payload = asyncio.run(
        evaluate(live=args.live, record=args.record, interval=args.record_interval)
    )
    breaches = check_gate(payload)
    payload["gate"] = {"passed": not breaches, "breaches": breaches}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=1))
    else:
        print(summarize(payload))
        print(f"  written to {args.out}\n")

    if breaches:
        print("GATE FAILED:", file=sys.stderr)
        for breach in breaches:
            print(f"  - {breach}", file=sys.stderr)
        if args.gate:
            return 1
        print("  (--gate not set, so this run does not fail the build)", file=sys.stderr)
    elif args.gate:
        print("gate passed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
