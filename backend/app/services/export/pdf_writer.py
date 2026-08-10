"""PDF rendering, via ReportLab's platypus.

Drawn directly rather than through an HTML engine. WeasyPrint would let the
export reuse the app's CSS, but it needs GTK on the host — which would mean a
reviewer cloning this repo discovers the dependency when the export 500s, not
when the container builds. ReportLab is a pure-Python wheel everywhere.

**The palette is the print inverse of the app's, not a copy of it.** The UI is
graphite-on-near-black; those hues are chosen to glow on a dark screen and go
muddy on white paper. The rule they encode is what carries over: chroma appears
only where it means something — a severity, or a handling caveat — and
everything else is ink and rule.
"""

from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    CondPageBreak,
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.export.layout import SEVERITY_LABELS, Layout, Section

PAGE_SIZE = A4
MARGIN_X = 19 * mm
MARGIN_TOP = 24 * mm
MARGIN_BOTTOM = 20 * mm
CONTENT_WIDTH = PAGE_SIZE[0] - 2 * MARGIN_X

INK = colors.HexColor("#15181e")
DIM = colors.HexColor("#59616f")
FAINT = colors.HexColor("#828b99")
LINE = colors.HexColor("#d3d9e1")
BAND = colors.HexColor("#f3f5f8")

SEVERITY_COLORS = {
    "critical": colors.HexColor("#b01f36"),
    "high": colors.HexColor("#a1520d"),
    "medium": colors.HexColor("#836405"),
    "low": colors.HexColor("#0f6c7b"),
    "unknown": FAINT,
}

# Classification is a *state* — who this may be shown to — so it is allowed
# colour under the same rule severity is. Confidential is the only level with a
# consequence attached, so it is the only one that gets a hue.
CLASSIFICATION_COLORS = {
    "Confidential": colors.HexColor("#b01f36"),
    "Internal": INK,
    "Public": DIM,
}

BODY = "Helvetica"
BOLD = "Helvetica-Bold"
MONO = "Courier"


def _hex(colour: colors.Color) -> str:
    """`#rrggbb`, for the inline `<font color=...>` markup in a Paragraph."""
    return f"#{colour.hexval()[2:]}"


def _style(name: str, **kwargs) -> ParagraphStyle:
    base = {"fontName": BODY, "fontSize": 9.2, "leading": 13, "textColor": INK}
    return ParagraphStyle(name, **{**base, **kwargs})


TITLE = _style("title", fontName=BOLD, fontSize=20, leading=24, spaceAfter=2)
PROVENANCE = _style("provenance", fontSize=9, textColor=DIM, spaceAfter=2)
SECTION_TITLE = _style(
    "section", fontName=BOLD, fontSize=12.5, leading=15, spaceBefore=2, spaceAfter=1
)
SECTION_CAPTION = _style("caption", fontSize=8.6, textColor=DIM, spaceAfter=1)
EMPTY_NOTE = _style("empty", fontSize=9, textColor=FAINT, spaceBefore=4)
FINDING_HEADING = _style(
    "finding", fontName=BOLD, fontSize=10.4, leading=13.5, spaceBefore=9, keepWithNext=True
)
FINDING_SUBTITLE = _style(
    "subtitle", fontName=MONO, fontSize=8.2, textColor=DIM, spaceAfter=3, keepWithNext=True
)
FIELD_LABEL = _style(
    "label", fontName=BOLD, fontSize=7.4, textColor=FAINT, spaceBefore=4, keepWithNext=True
)
FIELD_VALUE = _style("value", fontSize=9.2, leading=13.2)
META_LABEL = _style("metaLabel", fontName=BOLD, fontSize=8, textColor=DIM)
META_VALUE = _style("metaValue", fontSize=8.8, leading=12)
META_MONO = _style("metaMono", fontName=MONO, fontSize=7.6, leading=11)
TALLY_TITLE = _style("tallyTitle", fontName=BOLD, fontSize=8, textColor=DIM, spaceAfter=4)
CELL = _style("cell", fontSize=8.1, leading=11)
CELL_HEAD = _style("cellHead", fontName=BOLD, fontSize=7.3, leading=10, textColor=DIM)


def render(layout: Layout) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=layout.title,
        author="AIPCC",
        subject=f"{layout.classification} security report",
    )
    doc.build(_story(layout), canvasmaker=_furniture(layout.classification))
    return buffer.getvalue()


# --- Story ----------------------------------------------------------------


def _story(layout: Layout) -> list:
    story: list = [
        Paragraph(escape(layout.title), TITLE),
    ]
    if layout.provenance:
        story.append(Paragraph(escape(layout.provenance), PROVENANCE))
    story += [
        Spacer(1, 7),
        HRFlowable(width="100%", thickness=1.1, color=INK, spaceAfter=11),
        _meta_table(layout),
        Spacer(1, 13),
        _summary_table(layout),
    ]

    # The summary keeps page one to itself. It is the page that gets forwarded,
    # printed and pinned up, and a findings section starting halfway down it
    # makes it read as the top of a long document rather than as a standalone
    # answer to "what is this and how bad is it".
    for index, section in enumerate(layout.sections):
        story.append(PageBreak() if index == 0 else Spacer(1, 16))
        story.extend(_section(section))

    return story


def _meta_table(layout: Layout) -> Table:
    rows = [
        [
            Paragraph(escape(label), META_LABEL),
            Paragraph(escape(value), META_MONO if _is_identifier(label) else META_VALUE),
        ]
        for label, value in layout.meta
    ]
    table = Table(rows, colWidths=[34 * mm, CONTENT_WIDTH - 34 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _is_identifier(label: str) -> bool:
    return label in {"Reference", "Sealed SHA-256"}


def _summary_table(layout: Layout) -> Table:
    """Severity tally beside section totals.

    Deliberately the first thing after the metadata: the question anyone opening
    a security report asks first is "how bad", and the second is "how much".
    """
    tally_rows = [[Paragraph("Findings by severity", TALLY_TITLE), ""]]
    for label, count in layout.tally:
        key = next(k for k, v in SEVERITY_LABELS.items() if v == label)
        colour = SEVERITY_COLORS[key]
        tally_rows.append(
            [
                Paragraph(
                    f'<font color="{_hex(colour)}">{escape(label)}</font>',
                    _style("t", fontName=BOLD, fontSize=8.6),
                ),
                Paragraph(str(count), _style("tv", fontSize=8.6, alignment=2)),
            ]
        )

    total_rows = [[Paragraph("Contents", TALLY_TITLE), ""]]
    total_rows += [
        [
            Paragraph(escape(label), _style("c", fontSize=8.6, textColor=DIM)),
            Paragraph(str(count), _style("cv", fontSize=8.6, alignment=2)),
        ]
        for label, count in layout.totals
    ]

    # Pad the shorter column so both panels end level.
    while len(tally_rows) < len(total_rows):
        tally_rows.append(["", ""])
    while len(total_rows) < len(tally_rows):
        total_rows.append(["", ""])

    panel_style = TableStyle(
        [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("SPAN", (0, 0), (1, 0)),
        ]
    )
    width = (CONTENT_WIDTH - 14 * mm) / 2
    left = Table(tally_rows, colWidths=[width - 16 * mm, 16 * mm])
    right = Table(total_rows, colWidths=[width - 16 * mm, 16 * mm])
    left.setStyle(panel_style)
    right.setStyle(panel_style)

    outer = Table([[left, right]], colWidths=[width + 7 * mm, width + 7 * mm], hAlign="LEFT")
    outer.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, -1), BAND),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return outer


def _section(section: Section) -> list:
    story: list = [
        # A section heading stranded at the foot of a page with its content
        # overleaf reads as a document that ran out of room, not as a section.
        # `KeepTogether` alone cannot fix it — the heading and its first row are
        # separate flowables — so refuse to start a section in the last 30mm.
        CondPageBreak(30 * mm),
        KeepTogether(
            [
                Paragraph(escape(section.title), SECTION_TITLE),
                Paragraph(escape(section.caption), SECTION_CAPTION),
                HRFlowable(width="100%", thickness=0.7, color=LINE, spaceBefore=4, spaceAfter=2),
            ]
        ),
    ]

    if section.count == 0:
        story.append(Paragraph(escape(section.empty_note), EMPTY_NOTE))
        return story

    if section.is_table:
        story.append(Spacer(1, 5))
        story.append(_table(section))
        return story

    for finding in section.findings:
        heading = escape(finding.heading)
        if finding.severity:
            colour = SEVERITY_COLORS[finding.severity]
            label = SEVERITY_LABELS[finding.severity].upper()
            heading += f'&nbsp;&nbsp;<font size="7.4" color="{_hex(colour)}">{label}</font>'
        story.append(Paragraph(heading, FINDING_HEADING))
        if finding.subtitle:
            story.append(Paragraph(escape(finding.subtitle), FINDING_SUBTITLE))
        for label, value in finding.fields:
            story.append(Paragraph(escape(label.upper()), FIELD_LABEL))
            story.append(Paragraph(escape(value), FIELD_VALUE))

    return story


def _table(section: Section) -> Table:
    weights = section.weights or tuple(1.0 for _ in section.columns)
    total = sum(weights)
    widths = [CONTENT_WIDTH * weight / total for weight in weights]

    data = [[Paragraph(escape(column.upper()), CELL_HEAD) for column in section.columns]]
    data += [[Paragraph(escape(cell), CELL) for cell in row] for row in section.rows]

    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), BAND),
                ("LINEBELOW", (0, 0), (-1, 0), 0.7, LINE),
                # A hairline between rows rather than banding: banded fill is a
                # second visual system competing with the one hue that means
                # something on this page.
                ("LINEBELOW", (0, 1), (-1, -2), 0.35, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


# --- Page furniture -------------------------------------------------------


def _furniture(classification: str):
    """Build the canvas class that stamps every page.

    Two passes: pages are replayed at save time so the footer can say "3 of 11".
    A page count is the one piece of furniture that cannot be drawn while the
    page is being laid out, and "Page 3" alone does not tell a reader holding a
    printout whether they have all of it.
    """
    colour = CLASSIFICATION_COLORS.get(classification, INK)
    caveat = classification.upper()

    class NumberedCanvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self) -> None:
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self._stamp(total)
                super().showPage()
            super().save()

        def _stamp(self, total: int) -> None:
            width, height = PAGE_SIZE

            self.setFont(BOLD, 7.2)
            self.setFillColor(colour)
            self.drawCentredString(width / 2, height - 13 * mm, caveat)

            self.setStrokeColor(LINE)
            self.setLineWidth(0.5)
            self.line(MARGIN_X, height - 16 * mm, width - MARGIN_X, height - 16 * mm)
            self.line(MARGIN_X, 13.5 * mm, width - MARGIN_X, 13.5 * mm)

            self.setFont(BODY, 7)
            self.setFillColor(FAINT)
            self.drawString(MARGIN_X, 10 * mm, "AIPCC — AI-Powered Cybersecurity Co-Pilot")
            self.setFillColor(colour)
            self.setFont(BOLD, 7)
            self.drawCentredString(width / 2, 10 * mm, caveat)
            self.setFont(BODY, 7)
            self.setFillColor(FAINT)
            self.drawRightString(
                width - MARGIN_X, 10 * mm, f"Page {self._pageNumber} of {total}"
            )

    return NumberedCanvas
