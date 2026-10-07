"""Audit individual result voids without deleting calculated scores."""

import sqlalchemy as sa

from alembic import op

revision = "20261007_individual_result_void"
down_revision = "20261006_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("exam_results", sa.Column("voided_at", sa.DateTime(timezone=True)))
    op.add_column("exam_results", sa.Column("voided_by_actor_id", sa.UUID()))
    op.add_column("exam_results", sa.Column("void_reason", sa.Text()))
    op.create_foreign_key(
        "fk_exam_results_voided_by_actor_id_local_actors",
        "exam_results",
        "local_actors",
        ["voided_by_actor_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_exam_results_void_audit",
        "exam_results",
        "(voided_at IS NULL AND voided_by_actor_id IS NULL AND void_reason IS NULL) OR (voided_at IS NOT NULL AND voided_by_actor_id IS NOT NULL AND void_reason IS NOT NULL AND char_length(trim(void_reason)) BETWEEN 1 AND 1024)",
    )
    op.create_check_constraint(
        "ck_exam_results_void_unsent",
        "exam_results",
        "voided_at IS NULL OR (sync_batch_id IS NULL AND sync_status IN ('pending', 'failed'))",
    )


def downgrade():
    op.drop_constraint("ck_exam_results_void_unsent", "exam_results", type_="check")
    op.drop_constraint("ck_exam_results_void_audit", "exam_results", type_="check")
    op.drop_constraint(
        "fk_exam_results_voided_by_actor_id_local_actors",
        "exam_results",
        type_="foreignkey",
    )
    for column in ("void_reason", "voided_by_actor_id", "voided_at"):
        op.drop_column("exam_results", column)
