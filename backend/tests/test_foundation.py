"""Phase 0 guard rails.

These assert the structural promises of the foundation, not features. They run
without Postgres, without Chroma and without the embedding model — which is
itself the point: the RAG loaders were decoupled from the ORM during the port.
"""

import io
import re
import tokenize
from pathlib import Path

import pandas as pd

from app.db import models

BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_DIR / "app"

# Comments and string literals are masked before scanning. Without this the
# checks below fire on their own documentation — several modules name the
# forbidden constructs in docstrings precisely to explain why they are absent.
_MASKED_TOKENS = {tokenize.COMMENT, tokenize.STRING} | {
    getattr(tokenize, name)
    for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
    if hasattr(tokenize, name)
}


def _executable_lines(source: str) -> dict[int, str]:
    """Return {line number: source line} with comments and strings blanked out."""
    grid = {i: list(line) for i, line in enumerate(source.splitlines(), start=1)}
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type not in _MASKED_TOKENS:
                continue
            (start_row, start_col), (end_row, end_col) = token.start, token.end
            for row in range(start_row, end_row + 1):
                chars = grid.get(row)
                if chars is None:
                    continue
                begin = start_col if row == start_row else 0
                finish = end_col if row == end_row else len(chars)
                for col in range(begin, min(finish, len(chars))):
                    chars[col] = " "
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Unparseable file — fall back to scanning it verbatim rather than
        # silently passing the check.
        return dict(enumerate(source.splitlines(), start=1))
    return {row: "".join(chars) for row, chars in grid.items()}


def _scan_app(pattern: str) -> list[str]:
    """Return "path:line: text" for every match of `pattern` in app/ code.

    Walks the source tree rather than shelling out to `git grep`, so the checks
    hold for uncommitted work and never reach into .venv.
    """
    regex = re.compile(pattern)
    hits: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for number, line in _executable_lines(source).items():
            if regex.search(line):
                rel = path.relative_to(BACKEND_DIR).as_posix()
                hits.append(f"{rel}:{number}: {line.strip()}")
    return hits


class TestAppBoots:
    def test_health_endpoint(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestHardRules:
    def test_no_schema_creation_in_app_code(self):
        """CLAUDE.md hard rule #1. The prototype wiped its DB on every boot."""
        hits = _scan_app(r"\b(drop_all|create_all)\b")
        assert hits == [], "schema create/drop in app/:\n" + "\n".join(hits)

    def test_no_circular_import_from_main(self):
        """PORTING.md: `from backend.main import *` must not come across."""
        hits = _scan_app(r"from backend\.main import")
        assert hits == [], "circular import:\n" + "\n".join(hits)

    def test_env_is_read_only_in_config(self):
        """CLAUDE.md convention: no bare os.getenv outside core/config.py."""
        hits = [h for h in _scan_app(r"os\.getenv|os\.environ") if "app/core/config.py" not in h]
        assert hits == [], "env read outside config.py:\n" + "\n".join(hits)

    def test_no_module_level_current_user(self):
        """CLAUDE.md hard rule #2.

        The prototype assigned a module-global `current_user` inside a route
        handler, so six other routes raised NameError until that one endpoint
        had been called. The caller must come from `get_current_user`.
        """
        hits = [
            h
            for h in _scan_app(r"^\s*current_user\s*=")
            # A local binding from the dependency is fine; a global is not.
            if "Depends" not in h
        ]
        assert hits == [], "current_user assigned directly:\n" + "\n".join(hits)

    def test_password_hash_always_comes_from_hash_password(self):
        """CLAUDE.md hard rule #3.

        The prototype wrote `password_hash = new_user.password`. Rather than
        pattern-matching that one shape, require the inverse: every value
        assigned to `password_hash` must have passed through `hash_password()`.
        """
        assignments = _scan_app(r"password_hash\s*=")
        offenders = [
            line
            for line in assignments
            # The column definition itself is a declaration, not an assignment.
            if "mapped_column" not in line and "hash_password(" not in line
        ]
        assert offenders == [], (
            "password_hash assigned without hashing:\n" + "\n".join(offenders)
        )


class TestModels:
    def test_all_expected_tables_registered(self):
        expected = {
            "users",
            "documents",
            "reports",
            "attack_types",
            "risk_assessments",
            "vulnerabilities",
            "anomalies",
            "timeline_events",
            "chats",
            "messages",
        }
        assert expected <= set(models.Base.metadata.tables)

    def test_primary_keys_are_uuid(self):
        """No parsed sequential ids ("UR-1001") anywhere."""
        for table in models.Base.metadata.tables.values():
            for column in table.primary_key.columns:
                assert column.type.python_type.__name__ == "UUID", (
                    f"{table.name}.{column.name} is {column.type}, expected UUID"
                )


class TestRagLoaders:
    """The loaders are importable and usable with no database and no Chroma."""

    def test_load_csv_and_chunk(self, sample_csv):
        from app.services.rag.chunk import chunk_logs
        from app.services.rag.ingest import extract_metadata, load_file

        loaded = load_file(sample_csv, ".csv")
        assert isinstance(loaded, pd.DataFrame)
        assert len(loaded) > 0

        metadata = extract_metadata(loaded, ".csv", "doc-123", sample_csv)
        assert metadata["document_id"] == "doc-123"
        assert metadata["data_type"] == "structured"
        assert metadata["row_count"] == len(loaded)

        chunks = chunk_logs(metadata, loaded, ".csv")
        assert len(chunks) > 1
        assert chunks[0]["metadata"]["chunk_id"] == 0
        assert chunks[0]["metadata"]["document_id"] == "doc-123"

    def test_metadata_is_chroma_safe(self, sample_csv):
        """Chroma rejects None and non-primitive metadata values."""
        from app.services.rag.ingest import extract_metadata, load_file

        loaded = load_file(sample_csv, ".csv")
        metadata = extract_metadata(loaded, ".csv", "doc-123", sample_csv)
        for key, value in metadata.items():
            assert value is not None, f"{key} is None"
            assert isinstance(value, (str, int, float, bool)), f"{key} is {type(value)}"

    def test_txt_loader(self, tmp_path):
        from app.services.rag.ingest import extract_metadata, load_file

        log = tmp_path / "auth.log"
        log.write_text("line one\nline two\nline three\n", encoding="utf-8")

        loaded = load_file(log, ".log")
        assert isinstance(loaded, str)

        metadata = extract_metadata(loaded, ".log", "doc-456", log)
        assert metadata["data_type"] == "text"
        assert metadata["row_count"] == 4  # trailing newline yields a final empty line

    def test_unsupported_extension_raises(self, tmp_path):
        import pytest

        from app.services.rag.ingest import load_file

        target = tmp_path / "report.pdf"
        target.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported extension"):
            load_file(target, ".pdf")
