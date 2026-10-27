"""Allow administrator-authorized retakes after individually voided results.

The original CBT baseline remains frozen. This upgrade does not remove or
rewrite existing candidate, attempt, answer, result or audit rows.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261027_individual_retakes"
down_revision = "20261006_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exam_attempts",
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "exam_attempts",
        sa.Column("makeup_authorization_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # The frozen baseline created an indexed UNIQUE candidate_id. Keep its
    # lookup index but release the uniqueness only after the new guards exist.
    op.drop_index("ix_exam_attempts_candidate_id", table_name="exam_attempts")
    op.create_index("ix_exam_attempts_candidate_id", "exam_attempts", ["candidate_id"])
    op.create_unique_constraint(
        "uq_exam_attempts_candidate_number", "exam_attempts", ["candidate_id", "attempt_number"]
    )
    op.create_check_constraint(
        "ck_exam_attempts_attempt_number_positive", "exam_attempts", "attempt_number >= 1"
    )
    op.create_index(
        "uq_exam_attempts_one_active_candidate", "exam_attempts", ["candidate_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('in_progress', 'interrupted')"),
    )
    op.create_foreign_key(
        "fk_exam_attempts_makeup_authorization_id_candidate_make_up_authorizations",
        "exam_attempts", "candidate_make_up_authorizations",
        ["makeup_authorization_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_exam_attempts_makeup_authorization_id", "exam_attempts", ["makeup_authorization_id"]
    )
    # Legacy makeup attempts consumed their unique approval before this column
    # existed. Backfill the exact existing linkage without touching answers.
    op.execute(sa.text("""
        UPDATE exam_attempts a
        SET makeup_authorization_id = m.id
        FROM candidate_make_up_authorizations m
        WHERE m.candidate_id = a.candidate_id
          AND m.consumed_at IS NOT NULL
          AND m.revoked_at IS NULL
    """))
    op.drop_constraint("uq_exam_results_candidate_exam", "exam_results", type_="unique")
    op.create_index(
        "uq_exam_results_candidate_exam_nonvoided", "exam_results",
        ["candidate_id", "exam_id"], unique=True,
        postgresql_where=sa.text("voided_at IS NULL"),
    )
    op.drop_index("uq_candidate_makeup_one_active", table_name="candidate_make_up_authorizations")
    op.create_index(
        "uq_candidate_makeup_one_pending", "candidate_make_up_authorizations",
        ["candidate_id"], unique=True,
        postgresql_where=sa.text("revoked_at IS NULL AND consumed_at IS NULL"),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Retake migration preserves historical sittings and is not safely reversible; "
        "restore a verified backup instead."
    )
