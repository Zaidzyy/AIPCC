"""File integrity: hashing, and safely resolving a caller-supplied file name.

Two jobs:

1. **Seal.** When a report is generated, hash the source document. The hash
   lives on the *report*, not the document — a report is a statement about a
   file at a point in time, and re-hashing the document row later would only
   ever tell you what the file is now, which is precisely the question the FIM
   engine exists to answer differently.

2. **Serve, without letting a caller pick a path.** The FIM workflow asks for a
   document by *name*. A name from a request must never be joined onto a
   directory and opened: `../../.env` is a valid file name. So a name is
   resolved by looking up the `documents` row that has it and serving that
   row's stored path — the caller selects a database record, not a location on
   disk. The stored path is then still checked to be inside the upload
   directory, because a row written by an earlier version of this code is also
   untrusted input.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.core.config import settings

CHUNK_SIZE = 1024 * 1024


class IntegrityError(Exception):
    """The file backing a document is missing or outside the upload directory."""


def hash_file(path: str | Path) -> str:
    """SHA-256 of a file, read in chunks so a large log does not load in full."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def hash_document(document_path: str | Path) -> str | None:
    """Hash a document, or None if it cannot be read.

    Returns None rather than raising: a report whose source file has already
    been moved is still worth storing, it just cannot be sealed. The report
    keeps `integrity_state = "UNKNOWN"`, which is the truthful answer.
    """
    try:
        return hash_file(document_path)
    except OSError:
        return None


def resolve_upload_path(document_path: str | Path) -> Path:
    """Return `document_path` only if it really lives in the upload directory.

    `Path.resolve()` collapses `..` and follows symlinks *before* the check, so
    a stored path of `uploads/../../.env` fails here rather than being opened.
    """
    root = settings.upload_dir.resolve()
    candidate = Path(document_path).resolve()

    if not candidate.is_relative_to(root):
        raise IntegrityError("document path is outside the upload directory")
    if not candidate.is_file():
        raise IntegrityError("document file is missing")
    return candidate
