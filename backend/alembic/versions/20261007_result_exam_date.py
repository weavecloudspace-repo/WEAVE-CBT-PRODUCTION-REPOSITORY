"""Freeze assessment dates for original and new-enrollee makeup results."""

import sqlalchemy as sa
from alembic import op

revision = "20261007_result_exam_date"
down_revision = "20261007_individual_result_void"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("exam_results", sa.Column("exam_date", sa.Date(), nullable=True))
    # Preserve the original payload date for existing durable batches. Changing
    # it would violate idempotency for uncertain deliveries already in flight.
    op.execute("""
        UPDATE exam_results AS r
        SET exam_date = (COALESCE(e.activated_at, e.scheduled_start_at, e.closed_at, r.calculated_at) AT TIME ZONE 'UTC')::date
        FROM exams AS e WHERE e.id = r.exam_id
    """)
    op.alter_column("exam_results", "exam_date", nullable=False)


def downgrade():
    op.drop_column("exam_results", "exam_date")
