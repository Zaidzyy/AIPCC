"""Vendor the official MITRE ATT&CK and CWE catalogues.

    python -m app.eval.vendor

**The whole evaluation harness is only credible because these are real.** A
hand-typed approximation of the ATT&CK technique list would make every
hallucination number this project reports a fiction — worse than reporting
nothing. So the two catalogues are downloaded from their publishers, pinned to
a version, checksummed, and attributed in `data/SOURCES.md`.

What is committed is a **derivation**, not the raw download: the ATT&CK STIX
bundle is ~45 MB of graph data and the CWE catalogue is a large XML document,
of which this project needs exactly two fields each — an identifier and its
official name. This script is committed alongside the output so the derivation
is reproducible and auditable: re-run it and the files should come back
byte-identical for the same pinned version.

Deprecated and revoked entries are kept, and marked. A model emitting a
technique that ATT&CK has since retired has not hallucinated it — the id was
real — and scoring that as a fabrication would inflate the hallucination rate
with the passage of time rather than with anything the model did.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

DATA_DIR = Path(__file__).parent / "data"

# Pinned. `master` would make the committed data unreproducible, and a silent
# upstream change to a technique name would silently change this project's
# reported hallucination rate.
ATTACK_VERSION = "17.1"
ATTACK_URL = (
    "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/"
    f"enterprise-attack/enterprise-attack-{ATTACK_VERSION}.json"
)
ATTACK_LICENCE = (
    "MITRE ATT&CK® is © The MITRE Corporation. Used under the ATT&CK Terms of "
    "Use: https://attack.mitre.org/resources/legal-and-branding/terms-of-use/"
)

CWE_URL = "https://cwe.mitre.org/data/xml/cwec_latest.xml.zip"
CWE_LICENCE = (
    "CWE™ is © The MITRE Corporation. Used under the CWE Terms of Use: "
    "https://cwe.mitre.org/about/termsofuse.html"
)

# The ATT&CK Navigator layer file format. Vendored for the same reason as the
# catalogues: Phase 12 exports a layer an analyst loads into MITRE's own tool,
# and a hand-written approximation of the format is how you ship a file that
# looks right and does not open. MITRE publishes the format as a markdown
# property table rather than as a JSON Schema, so what is committed here is a
# schema *derived from that table* by `navigator_schema()` below.
NAVIGATOR_LAYER_VERSION = "4.5"
NAVIGATOR_SPEC_URL = (
    "https://raw.githubusercontent.com/mitre-attack/attack-navigator/master/"
    f"layers/spec/v{NAVIGATOR_LAYER_VERSION}/layerformat.md"
)
NAVIGATOR_LICENCE = (
    "The ATT&CK Navigator is © The MITRE Corporation, released under the "
    "Apache License 2.0: https://github.com/mitre-attack/attack-navigator"
)

USER_AGENT = "aipcc-eval-vendor/1.0 (+https://github.com/)"


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def _external_id(obj: dict) -> str | None:
    """The ATT&CK id (T1059, TA0002, …) carried on a STIX object."""
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == "mitre-attack" and ref.get("external_id"):
            return ref["external_id"]
    return None


def vendor_attack() -> dict:
    """Project the ATT&CK STIX bundle down to techniques, tactics and the grid.

    Phase 11 needed only {technique id: name} to tell a real identifier from an
    invented one. Phase 12 draws the matrix, which needs two more things from
    the same bundle: the **tactics** — the matrix's columns — and which column
    each technique belongs in. Both come from the same pinned download, so the
    matrix cannot disagree with the validator about what ATT&CK contains.

    Column order is taken from the bundle's own `x-mitre-matrix` object rather
    than sorted by id. The published matrix runs Reconnaissance → Impact, which
    is the order every analyst reads it in; sorting by TA-number happens to
    agree today and would silently stop agreeing the moment MITRE inserts one.
    """
    raw = fetch(ATTACK_URL)
    digest = hashlib.sha256(raw).hexdigest()
    bundle = json.loads(raw)
    objects = bundle.get("objects", [])

    # STIX id -> tactic record, so the matrix's ordered `tactic_refs` resolve.
    tactics_by_stix: dict[str, dict] = {}
    for obj in objects:
        if obj.get("type") != "x-mitre-tactic":
            continue
        tactic_id = _external_id(obj)
        shortname = obj.get("x_mitre_shortname")
        if not tactic_id or not shortname:
            continue
        tactics_by_stix[obj["id"]] = {
            "tactic_id": tactic_id,
            # The shortname is what a Navigator layer's `tactic` field carries
            # and what a technique's kill_chain_phases name it by. It is the
            # join key everywhere downstream, not a display string.
            "shortname": shortname,
            "name": obj.get("name", ""),
            "description": (obj.get("description") or "").split("\n")[0],
        }

    matrix = next((obj for obj in objects if obj.get("type") == "x-mitre-matrix"), None)
    ordered_refs = (matrix or {}).get("tactic_refs", [])
    tactics = [tactics_by_stix[ref] for ref in ordered_refs if ref in tactics_by_stix]
    if not tactics:
        raise RuntimeError(
            "no x-mitre-matrix tactic_refs resolved — the bundle layout changed"
        )
    # Anything the matrix object did not list would be a column nobody could
    # place; failing loudly beats emitting a grid that quietly drops a tactic.
    missing = set(tactics_by_stix) - set(ordered_refs)
    if missing:
        raise RuntimeError(f"{len(missing)} tactics are absent from the matrix object")

    known_shortnames = {tactic["shortname"] for tactic in tactics}

    techniques: dict[str, dict] = {}
    for obj in objects:
        if obj.get("type") != "attack-pattern":
            continue
        technique_id = _external_id(obj)
        if not technique_id:
            continue
        phases = [
            phase["phase_name"]
            for phase in obj.get("kill_chain_phases", [])
            if phase.get("kill_chain_name") == "mitre-attack"
            and phase.get("phase_name") in known_shortnames
        ]
        techniques[technique_id] = {
            "name": obj.get("name", ""),
            # Kept and marked rather than dropped — see the module docstring.
            "deprecated": bool(obj.get("x_mitre_deprecated", False)),
            "revoked": bool(obj.get("revoked", False)),
            "sub_technique": bool(obj.get("x_mitre_is_subtechnique", False)),
            # Order preserved from the bundle: a technique listed under
            # Execution then Persistence renders in that order in the matrix.
            "tactics": phases,
        }

    return {
        "_source": {
            "catalogue": "MITRE ATT&CK Enterprise",
            "version": ATTACK_VERSION,
            "url": ATTACK_URL,
            "sha256": digest,
            "retrieved": datetime.now(timezone.utc).date().isoformat(),
            "licence": ATTACK_LICENCE,
            "derivation": (
                "attack-pattern objects, projected to their mitre-attack "
                "external_id, name and kill-chain phases; x-mitre-tactic "
                "objects ordered by the x-mitre-matrix object's tactic_refs. "
                "Generated by app/eval/vendor.py."
            ),
        },
        "tactics": tactics,
        "techniques": dict(sorted(techniques.items())),
    }


def vendor_cwe() -> dict:
    """Project the CWE catalogue down to {CWE-N: name}."""
    raw = fetch(CWE_URL)
    digest = hashlib.sha256(raw).hexdigest()

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith(".xml"))
        document = archive.read(name)

    root = ElementTree.fromstring(document)
    version = root.attrib.get("Version", "unknown")

    weaknesses: dict[str, dict] = {}
    # The catalogue namespaces every element; matching on the local name keeps
    # this working across the schema revisions CWE occasionally publishes.
    for element in root.iter():
        if not element.tag.endswith("}Weakness") and element.tag != "Weakness":
            continue
        cwe_id = element.attrib.get("ID")
        if not cwe_id:
            continue
        weaknesses[f"CWE-{cwe_id}"] = {
            "name": element.attrib.get("Name", ""),
            "status": element.attrib.get("Status", ""),
            "abstraction": element.attrib.get("Abstraction", ""),
        }

    return {
        "_source": {
            "catalogue": "MITRE CWE",
            "version": version,
            "url": CWE_URL,
            "sha256": digest,
            "retrieved": datetime.now(timezone.utc).date().isoformat(),
            "licence": CWE_LICENCE,
            "derivation": (
                "Weakness elements, projected to CWE-<ID>, Name, Status and "
                "Abstraction. Generated by app/eval/vendor.py."
            ),
        },
        "weaknesses": dict(
            sorted(weaknesses.items(), key=lambda item: int(item[0].split("-")[1]))
        ),
    }


# The section headings of layerformat.md, mapped to the `$defs` name each one
# describes. "Property Table" is the layer itself.
_NAVIGATOR_SECTIONS = {
    "Property Table": None,
    "Filter Object Properties": "Filter",
    "Version Object Properties": "Version",
    "Technique Object properties": "Technique",
    "Gradient Object properties": "Gradient",
    "LegendItem Object properties": "LegendItem",
    "Metadata Object properties": "Metadata",
    "Link Object properties": "Link",
    "Divider Object properties": "Divider",
    "Layout Object properties": "Layout",
}

def _table_cells(line: str) -> list[str] | None:
    """Split one markdown table row into its cells.

    The trailing pipe is optional because the published spec omits it on two
    rows — including the Divider table's only row, so a regex anchored on it
    drops a whole object type from the schema and the failure is a missing
    `$defs` entry rather than a parse error.
    """
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    body = stripped[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in body.split("|")]


def _navigator_type(declared: str) -> dict:
    """Translate one cell of the spec's Type column into JSON Schema.

    Deliberately exhaustive: an unrecognised type string raises rather than
    falling back to `{}`. A permissive default would let a future revision of
    the format silently degrade the schema into one that validates anything,
    and the whole point of deriving it is that it says no.
    """
    text = declared.strip()
    lowered = text.lower()

    scalars = {"string": "string", "number": "number", "boolean": "boolean"}
    if lowered in scalars:
        return {"type": scalars[lowered]}
    if lowered == "array of string":
        return {"type": "array", "items": {"type": "string"}}

    # "Array of Metadata objects and Divider objects"
    match = re.fullmatch(r"array of (\w+) objects and (\w+) objects", lowered)
    if match:
        left, right = (part.capitalize() for part in match.groups())
        left = "LegendItem" if left == "Legenditem" else left
        return {
            "type": "array",
            "items": {"anyOf": [{"$ref": f"#/$defs/{left}"}, {"$ref": f"#/$defs/{right}"}]},
        }

    # "Array of Technique objects" / "Array of LegendItem objects"
    match = re.fullmatch(r"array of (\S+) objects", text, flags=re.IGNORECASE)
    if match:
        return {"type": "array", "items": {"$ref": f"#/$defs/{match.group(1)}"}}

    # "Version object" / "Filter object" / "Layout object"
    match = re.fullmatch(r"(\S+) object", text, flags=re.IGNORECASE)
    if match:
        return {"$ref": f"#/$defs/{match.group(1)}"}

    raise RuntimeError(f"unrecognised type in the Navigator spec: {declared!r}")


def _parse_navigator_tables(document: str) -> dict[str, dict]:
    """Read every `## … properties` table in layerformat.md into an object schema."""
    parsed: dict[str, dict] = {}
    heading: str | None = None

    for line in document.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            continue
        if heading not in _NAVIGATOR_SECTIONS:
            continue
        cells = _table_cells(line)
        if cells is None:
            continue
        if len(cells) < 3 or not cells[0] or set(cells[0]) <= {":", "-"}:
            continue
        # The header row is recognised by its *other* columns, not by its
        # first: "Name" is both the header and a real layer property, and
        # filtering on the first cell silently drops the layer's own name.
        if cells[1].lower() == "type" and cells[2].lower().startswith("required"):
            continue

        target = parsed.setdefault(heading, {"properties": {}, "required": []})
        target["properties"][cells[0]] = _navigator_type(cells[1])
        if cells[2].strip().lower().startswith("yes"):
            target["required"].append(cells[0])

    missing = set(_NAVIGATOR_SECTIONS) - set(parsed)
    if missing:
        raise RuntimeError(f"layerformat.md is missing sections: {sorted(missing)}")
    return parsed


def vendor_navigator_schema() -> dict:
    """Derive a JSON Schema for the Navigator layer file from MITRE's spec.

    MITRE documents the format as markdown property tables and publishes no
    machine-readable schema, so this parses the tables the format is *defined*
    by. Same discipline as the two catalogues: downloaded, checksummed,
    attributed, and regenerated by a committed script rather than typed out.

    `additionalProperties` is false throughout, which the prose does not say in
    so many words — but the tables enumerate the format exhaustively, so a key
    that is not in them is not part of it. That strictness is the reason to
    have the schema at all: it is what turns `techniqueId` into a failing test
    instead of a field the Navigator ignores.
    """
    raw = fetch(NAVIGATOR_SPEC_URL)
    digest = hashlib.sha256(raw).hexdigest()
    document = raw.decode("utf-8")
    tables = _parse_navigator_tables(document)

    def as_object(entry: dict) -> dict:
        schema = {
            "type": "object",
            "properties": entry["properties"],
            "additionalProperties": False,
        }
        if entry["required"]:
            schema["required"] = entry["required"]
        return schema

    root = as_object(tables["Property Table"])
    root.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": f"ATT&CK Navigator layer, format version {NAVIGATOR_LAYER_VERSION}",
            "$defs": {
                name: as_object(tables[heading])
                for heading, name in _NAVIGATOR_SECTIONS.items()
                if name is not None
            },
            "_source": {
                "catalogue": "MITRE ATT&CK Navigator layer file format",
                "version": NAVIGATOR_LAYER_VERSION,
                "url": NAVIGATOR_SPEC_URL,
                "sha256": digest,
                "retrieved": datetime.now(timezone.utc).date().isoformat(),
                "licence": NAVIGATOR_LICENCE,
                "derivation": (
                    "The property tables of layerformat.md, translated to JSON "
                    "Schema 2020-12 with additionalProperties disallowed. "
                    "Generated by app/eval/vendor.py."
                ),
            },
        }
    )
    return root


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sorted keys and a trailing newline, so re-running produces a byte-identical
    # file and a diff means the upstream catalogue actually changed.
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def write_sources(attack: dict, cwe: dict, navigator: dict) -> None:
    lines = [
        "# Vendored reference data",
        "",
        "Both files in this directory are **derived from the publishers' own",
        "releases** by `app/eval/vendor.py`, which is committed beside them so the",
        "derivation is reproducible. Nothing here is hand-written: an approximate",
        "technique list would make every hallucination rate this project reports a",
        "fiction, which is worse than reporting none.",
        "",
        "Regenerate with `python -m app.eval.vendor`.",
        "",
    ]
    for payload, filename, contents in (
        (
            attack,
            "mitre_attack_enterprise.json",
            f"{len(attack['techniques'])} techniques, {len(attack['tactics'])} tactics",
        ),
        (cwe, "cwe.json", f"{len(cwe['weaknesses'])} weaknesses"),
        (
            navigator,
            "navigator_layer_schema.json",
            f"{len(navigator['properties'])} layer properties, "
            f"{len(navigator['$defs'])} nested object types",
        ),
    ):
        source = payload["_source"]
        lines += [
            f"## {filename}",
            "",
            f"- **Catalogue**: {source['catalogue']}",
            f"- **Version**: {source['version']}",
            f"- **Contents**: {contents}",
            f"- **Source**: {source['url']}",
            f"- **SHA-256 of the download**: `{source['sha256']}`",
            f"- **Retrieved**: {source['retrieved']}",
            f"- **Derivation**: {source['derivation']}",
            f"- **Licence / attribution**: {source['licence']}",
            "",
        ]
    lines += [
        "Deprecated and revoked entries are retained and flagged rather than",
        "removed. A model naming a technique ATT&CK has since retired did not",
        "invent it, and scoring that as a fabrication would make the hallucination",
        "rate drift upward with the calendar instead of with model behaviour.",
        "",
    ]
    (DATA_DIR / "SOURCES.md").write_text("\n".join(lines), encoding="utf-8")


def _reuse(filename: str) -> dict:
    """Read a catalogue already on disk instead of re-downloading it.

    Only `--only` uses this, and only so that SOURCES.md can still be written
    in full. It matters because the CWE download is `cwec_latest.xml.zip` — an
    unpinned URL — so re-fetching it to refresh an unrelated file would bump
    the committed catalogue version as a side effect of an ATT&CK change.
    """
    return json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=["attack", "cwe", "navigator"],
        action="append",
        help="Refresh only these files. Repeatable. Default: all three.",
    )
    args = parser.parse_args(argv)
    wanted = set(args.only or ["attack", "cwe", "navigator"])

    if "attack" in wanted:
        print(f"fetching ATT&CK Enterprise v{ATTACK_VERSION} …")
        attack = vendor_attack()
        write(DATA_DIR / "mitre_attack_enterprise.json", attack)
        print(f"  {len(attack['techniques'])} techniques, {len(attack['tactics'])} tactics")
    else:
        attack = _reuse("mitre_attack_enterprise.json")

    if "cwe" in wanted:
        print("fetching CWE …")
        cwe = vendor_cwe()
        write(DATA_DIR / "cwe.json", cwe)
        print(f"  {len(cwe['weaknesses'])} weaknesses (catalogue v{cwe['_source']['version']})")
    else:
        cwe = _reuse("cwe.json")

    if "navigator" in wanted:
        print(f"fetching Navigator layer format v{NAVIGATOR_LAYER_VERSION} …")
        navigator = vendor_navigator_schema()
        write(DATA_DIR / "navigator_layer_schema.json", navigator)
        print(f"  {len(navigator['properties'])} layer properties")
    else:
        navigator = _reuse("navigator_layer_schema.json")

    write_sources(attack, cwe, navigator)
    print(f"wrote {DATA_DIR / 'SOURCES.md'}")


# A CVE id has no catalogue to check against offline — the list is unbounded and
# grows daily — so `validators.py` checks its *format* and says so, rather than
# pretending to verify existence. Kept here as a note next to the two
# catalogues that can be verified.
CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,7}$")


if __name__ == "__main__":
    main()
