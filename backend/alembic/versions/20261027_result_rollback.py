"""Allow durable CBT result withdrawal and explicit republication."""

import sqlalchemy as sa
from alembic import op

revision = "20261027_result_rollback"
down_revision = "20261027_individual_retakes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, column in (
        ("rollback_operation_id", sa.UUID()),
        ("rollback_original_batch_id", sa.UUID()),
        ("rollback_previous_synced_at", sa.DateTime(timezone=True)),
        ("rollback_requested_at", sa.DateTime(timezone=True)),
        ("rolled_back_at", sa.DateTime(timezone=True)),
        ("rollback_error", sa.Text()),
        ("rollback_reason", sa.Text()),
    ):
        op.add_column("exam_results", sa.Column(name, column, nullable=True))
    op.create_index(
        "ix_exam_results_rollback_operation_id",
        "exam_results",
        ["rollback_operation_id"],
    )
    op.drop_constraint("result_sync_status", "exam_results", type_="check")
    op.alter_column(
        "exam_results", "sync_status",
        existing_type=sa.String(length=7), type_=sa.String(length=16),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "result_sync_status",
        "exam_results",
        "sync_status IN ('pending', 'syncing', 'synced', 'failed', 'rollback_pending', 'rolled_back')",
    )
    op.drop_constraint("ck_exam_results_void_unsent", "exam_results", type_="check")
    op.create_check_constraint(
        "ck_exam_results_void_unsent",
        "exam_results",
        "voided_at IS NULL OR (sync_batch_id IS NULL AND sync_status IN ('pending', 'failed', 'rolled_back'))",
    )


def downgrade() -> None:
    raise RuntimeError(
        "Rollback publication history must not be removed after operations begin; "
        "restore a verified database backup instead."
    )
