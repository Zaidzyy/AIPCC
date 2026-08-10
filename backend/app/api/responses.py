"""Response helpers shared by more than one router."""

from __future__ import annotations

from fastapi import Response

from app.services.export import ExportedFile


def as_download(exported: ExportedFile) -> Response:
    """Return a generated file as an attachment.

    The filename is built by `layout._filename_stem`, which slugs it down to
    ASCII alphanumerics and dashes — so it needs no RFC 5987 escaping, and
    cannot smuggle a quote or a newline into the header.
    """
    return Response(
        content=exported.content,
        media_type=exported.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{exported.filename}"',
            # The browser reads the size from here; without it a download shows
            # no progress at all for a report with several hundred findings.
            "Content-Length": str(len(exported.content)),
        },
    )
