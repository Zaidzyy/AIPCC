"""phase 9: per-call LLM usage and denormalised report totals

`llm_usage` is a row per LLM *call*, not per section — which is what makes the
retry rate measurable, since a section that needed its repair prompt writes two
rows and the first one is the interesting one.

The three columns added to `reports` are a rollup of that table, kept so the
report list can show a cost without a GROUP BY per row. They are nullable and
left null rather than zeroed for reports that predate this migration or that
arrived from n8n, because "not measured" and "cost nothing" are different
facts and this project does not conflate them anywhere else either.

Revision ID: e5c8a3f14b72
Revises: d4b7f2a19c30
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5c8a3f14b72"
down_revision: Union[str, None] = "d4b7f2a19c30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("usage_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("section", sa.String(length=60), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["report_id"], ["reports.report_id"], ondelete="CASCADE"),
        # SET NULL, not CASCADE: deleting a user should not erase what their
        # reports cost to produce. The spend happened.
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("usage_id"),
    )
    op.create_index(op.f("ix_llm_usage_report_id"), "llm_usage", ["report_id"])
    op.create_index(op.f("ix_llm_usage_user_id"), "llm_usage", ["user_id"])
    op.create_index(op.f("ix_llm_usage_section"), "llm_usage", ["section"])
    op.create_index(op.f("ix_llm_usage_correlation_id"), "llm_usage", ["correlation_id"])
    op.create_index("ix_llm_usage_user_created", "llm_usage", ["user_id", "created_at"])

    op.add_column("reports", sa.Column("total_tokens", sa.Integer(), nullable=True))
    op.add_column("reports", sa.Column("total_cost_usd", sa.Float(), nullable=True))
    op.add_column("reports", sa.Column("generation_ms", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "generation_ms")
    op.drop_column("reports", "total_cost_usd")
    op.drop_column("reports", "total_tokens")

    op.drop_index("ix_llm_usage_user_created", table_name="llm_usage")
    op.drop_index(op.f("ix_llm_usage_correlation_id"), table_name="llm_usage")
    op.drop_index(op.f("ix_llm_usage_section"), table_name="llm_usage")
    op.drop_index(op.f("ix_llm_usage_user_id"), table_name="llm_usage")
    op.drop_index(op.f("ix_llm_usage_report_id"), table_name="llm_usage")
    op.drop_table("llm_usage")
