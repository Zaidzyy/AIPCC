"""phase 10: finding evidence and grounding counters

One evidence table for all five sections rather than five. `item_id` therefore
carries no foreign key — it points into one of five tables — and referential
integrity comes from the cascade on `report_id`, which is enough: evidence
dies with its report either way.

The two counters on `reports` are nullable and stay null for anything this app
did not generate, including every report that predates this migration. Same
rule as the Phase 9 cost columns: "not measured" is not zero, and a zero here
would read as "this report fabricated nothing", which is a claim.

**Existing documents keep working but are not retro-grounded.** Chunks ingested
before Phase 10 carry no row or line spans, so a report generated against them
gets evidence with null provenance rather than wrong provenance. Re-ingest to
populate it: `python -m app.db.seed --ingest` is idempotent per document, so
clear the Chroma volume first if you want the spans.

Revision ID: f2a91c07d3e8
Revises: e5c8a3f14b72
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a91c07d3e8"
down_revision: Union[str, None] = "e5c8a3f14b72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "finding_evidence",
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("section", sa.String(length=60), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("row_start", sa.Integer(), nullable=True),
        sa.Column("row_end", sa.Integer(), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["report_id"], ["reports.report_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("evidence_id"),
    )
    op.create_index(op.f("ix_finding_evidence_report_id"), "finding_evidence", ["report_id"])
    op.create_index(op.f("ix_finding_evidence_item_id"), "finding_evidence", ["item_id"])
    op.create_index(
        "ix_finding_evidence_report_item", "finding_evidence", ["report_id", "item_id"]
    )

    op.add_column("reports", sa.Column("ungrounded_findings", sa.Integer(), nullable=True))
    op.add_column("reports", sa.Column("invalid_citations", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "invalid_citations")
    op.drop_column("reports", "ungrounded_findings")

    op.drop_index("ix_finding_evidence_report_item", table_name="finding_evidence")
    op.drop_index(op.f("ix_finding_evidence_item_id"), table_name="finding_evidence")
    op.drop_index(op.f("ix_finding_evidence_report_id"), table_name="finding_evidence")
    op.drop_table("finding_evidence")
