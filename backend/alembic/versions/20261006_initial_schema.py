"""Consolidated, frozen initial CBT schema."""

from alembic import op
from app.core.schema_baseline import create_schema

revision = "20261006_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_schema(op.get_bind())


def downgrade() -> None:
    raise RuntimeError(
        "Initial schema downgrade would erase school data; restore a backup instead."
    )
