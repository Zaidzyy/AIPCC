"""Access to the vendored MITRE ATT&CK and CWE catalogues.

Loaded once, lazily, from the JSON in `data/`. See `data/SOURCES.md` for where
those files came from, which versions they are pinned to, and their licences —
and `vendor.py` for how to regenerate them.

Nothing in this module reaches the network. A quality gate that needs an
internet connection is a quality gate that fails on a bad day and gets deleted
on the next one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
ATTACK_FILE = DATA_DIR / "mitre_attack_enterprise.json"
CWE_FILE = DATA_DIR / "cwe.json"


@dataclass(frozen=True)
class Technique:
    technique_id: str
    name: str
    deprecated: bool = False
    revoked: bool = False
    sub_technique: bool = False

    @property
    def retired(self) -> bool:
        """Real once, not current.

        Kept distinct from "does not exist": a model naming a retired technique
        has not fabricated an identifier, and counting it as a hallucination
        would make the rate climb with the calendar rather than with anything
        the model did.
        """
        return self.deprecated or self.revoked


@dataclass(frozen=True)
class Weakness:
    cwe_id: str
    name: str
    status: str = ""
    abstraction: str = ""


@lru_cache(maxsize=1)
def _attack() -> dict[str, Technique]:
    payload = json.loads(ATTACK_FILE.read_text(encoding="utf-8"))
    return {
        key: Technique(technique_id=key, **value)
        for key, value in payload["techniques"].items()
    }


@lru_cache(maxsize=1)
def _cwe() -> dict[str, Weakness]:
    payload = json.loads(CWE_FILE.read_text(encoding="utf-8"))
    return {
        key: Weakness(cwe_id=key, **value) for key, value in payload["weaknesses"].items()
    }


@lru_cache(maxsize=1)
def source_info() -> dict[str, dict]:
    """The provenance block from each file, for the eval report's header.

    Emitted with every run so a set of numbers can never be read without the
    catalogue versions they were computed against.
    """
    return {
        "mitre_attack": json.loads(ATTACK_FILE.read_text(encoding="utf-8"))["_source"],
        "cwe": json.loads(CWE_FILE.read_text(encoding="utf-8"))["_source"],
    }


def technique(technique_id: str) -> Technique | None:
    return _attack().get(_normalize(technique_id))


def weakness(cwe_id: str) -> Weakness | None:
    return _cwe().get(_normalize(cwe_id))


def technique_count() -> int:
    return len(_attack())


def weakness_count() -> int:
    return len(_cwe())


def _normalize(identifier: str) -> str:
    """Upper-case and trim, and nothing else.

    Deliberately *not* forgiving beyond whitespace and case: "t1110 " is the
    same identifier typed sloppily, but "T1110 (Brute Force)" is a different
    string and normalising it away would hide a real formatting failure that
    would break any downstream tool consuming these ids.
    """
    return (identifier or "").strip().upper()
