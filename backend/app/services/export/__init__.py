"""Report export.

One entry point, two formats. `render` takes the format-independent `Layout`
built by `layout.build_layout` and hands it to whichever writer was asked for,
so PDF and DOCX cannot drift apart in content — only in typography.

The renderer modules are named `pdf_writer` / `docx_writer` rather than `pdf` /
`docx` because `docx.py` inside a package that imports the third-party `docx`
is a module name that reads as a shadowing bug even when it is not one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.export import docx_writer, pdf_writer
from app.services.export.layout import (
    ExportSource,
    build_layout,
    source_from_detail,
    source_from_shared,
)

ExportFormat = Literal["pdf", "docx"]

MEDIA_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@dataclass(frozen=True)
class ExportedFile:
    content: bytes
    media_type: str
    filename: str


def render(source: ExportSource, export_format: ExportFormat) -> ExportedFile:
    """Build one report as one file."""
    layout = build_layout(source)
    content = (
        pdf_writer.render(layout)
        if export_format == "pdf"
        else docx_writer.render(layout)
    )
    return ExportedFile(
        content=content,
        media_type=MEDIA_TYPES[export_format],
        filename=f"{layout.filename_stem}.{export_format}",
    )


__all__ = [
    "ExportFormat",
    "ExportSource",
    "ExportedFile",
    "MEDIA_TYPES",
    "render",
    "source_from_detail",
    "source_from_shared",
]
