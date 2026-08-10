"""phase 6: report share links

Revision ID: c7a1e4d90f52
Revises: 1fcaee149697
Create Date: 2026-08-10 12:10:00.000000

Also folds the free-text `classification` column onto the closed vocabulary the
API now enforces (Public / Internal / Confidential). "Restricted" was seeded by
`--demo` and sat between Confidential and nothing with no rule attached to it;
existing rows carrying it are moved up to Confidential rather than down, because
whoever chose it meant "more protected than Internal".

The downgrade cannot restore that distinction — the original value is gone once
it is folded — so it is not attempted. Losing a level nothing enforced is
cheaper than pretending the rollback is lossless.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7a1e4d90f52"
down_revision: Union[str, None] = "1fcaee149697"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_shares",
        sa.Column("share_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("prefix", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("view_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("classification_at_share", sa.String(length=50), nullable=False),
        sa.Column("override_justification", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["report_id"], ["reports.report_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("share_id"),
    )
    op.create_index(
        op.f("ix_report_shares_report_id"), "report_shares", ["report_id"], unique=False
    )
    op.create_index(
        op.f("ix_report_shares_created_by"), "report_shares", ["created_by"], unique=False
    )
    op.create_index(op.f("ix_report_shares_prefix"), "report_shares", ["prefix"], unique=True)

    op.execute(
        "UPDATE reports SET classification = 'Confidential' "
        "WHERE classification NOT IN ('Public', 'Internal', 'Confidential')"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_report_shares_prefix"), table_name="report_shares")
    op.drop_index(op.f("ix_report_shares_created_by"), table_name="report_shares")
    op.drop_index(op.f("ix_report_shares_report_id"), table_name="report_shares")
    op.drop_table("report_shares")
