"""Persist hybrid assessment capabilities and draft CBT score allocations.

Revision ID: 20261020_hybrid_allocation
Revises: 20261006_initial_schema
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261020_hybrid_allocation"
down_revision = "20261006_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assessment_components",
        sa.Column("is_hybrid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "exams",
        sa.Column("cbt_maximum_score", sa.Numeric(8, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_exams_cbt_maximum_score_positive",
        "exams",
        "cbt_maximum_score IS NULL OR cbt_maximum_score > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_exams_cbt_maximum_score_positive", "exams", type_="check")
    op.drop_column("exams", "cbt_maximum_score")
    op.drop_column("assessment_components", "is_hybrid")
