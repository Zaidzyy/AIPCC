"""phase 8: append-only audit log and auth attempt rate-limit state

Two tables and one trigger.

The trigger is the point of the migration. "Append-only" enforced only by the
absence of an endpoint is a convention, and conventions are one well-meaning
pull request away from being gone. `audit_log_append_only()` raises on UPDATE
and on DELETE, so the guarantee holds against the ORM, against psql, and
against a future route nobody has written yet.

TRUNCATE is deliberately not covered by the row-level trigger — a statement
trigger is added for it separately, because TRUNCATE never fires FOR EACH ROW.
DROP TABLE is not defended against and cannot be: the downgrade below needs it,
and anyone with DDL rights on the database is already past every control here.

Revision ID: d4b7f2a19c30
Revises: c7a1e4d90f52
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4b7f2a19c30"
down_revision: Union[str, None] = "c7a1e4d90f52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'audit_log is append-only; % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        "auth_attempts",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("identifier", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("successful", sa.Boolean(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("attempt_id"),
    )
    op.create_index(
        "ix_auth_attempts_window",
        "auth_attempts",
        ["scope", "identifier", "action", "at"],
    )
    op.create_index("ix_auth_attempts_at", "auth_attempts", ["at"])

    op.create_table(
        "audit_log",
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        # No ForeignKey, on purpose. Deleting a user must not delete the record
        # of what that user did — see `db/models.AuditLog`.
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_label", sa.String(length=255), nullable=True),
        sa.Column("target_type", sa.String(length=60), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index(op.f("ix_audit_log_at"), "audit_log", ["at"])
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"])
    op.create_index(op.f("ix_audit_log_actor_id"), "audit_log", ["actor_id"])
    op.create_index(op.f("ix_audit_log_correlation_id"), "audit_log", ["correlation_id"])
    op.create_index("ix_audit_log_actor_at", "audit_log", ["actor_id", "at"])
    op.create_index("ix_audit_log_action_at", "audit_log", ["action", "at"])

    op.execute(APPEND_ONLY_FUNCTION)
    op.execute(
        "CREATE TRIGGER audit_log_no_mutation "
        "BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();"
    )
    # TRUNCATE never fires a row-level trigger, so it needs its own statement
    # one. Without this, "append-only" is one `TRUNCATE audit_log` from false.
    op.execute(
        "CREATE TRIGGER audit_log_no_truncate "
        "BEFORE TRUNCATE ON audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log;")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_mutation ON audit_log;")
    op.execute("DROP FUNCTION IF EXISTS audit_log_append_only();")

    op.drop_index("ix_audit_log_action_at", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_at", table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_correlation_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_actor_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_action"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_at"), table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index("ix_auth_attempts_at", table_name="auth_attempts")
    op.drop_index("ix_auth_attempts_window", table_name="auth_attempts")
    op.drop_table("auth_attempts")
