"""Durable idempotency metadata for reviewed AI question imports."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QuestionAIImportBatch(Base):
    """One permanently persisted browser AI draft.

    The generated draft body remains browser-owned until save. This row is only
    created inside the same transaction as the accepted Questions so a lost
    local HTTP response can replay the already-persisted batch instead of
    inserting duplicate questions.
    """

    __tablename__ = "question_ai_import_batches"

    draft_id: Mapped[UUID] = mapped_column(nullable=False)
    bank_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_banks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"),
        nullable=False,
    )
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("draft_id", name="uq_question_ai_import_batches_draft_id"),
        Index("ix_question_ai_import_batches_bank", "bank_id", "created_at"),
        Index("ix_question_ai_import_batches_actor", "actor_id", "created_at"),
    )


class QuestionAIImportItem(Base):
    """Ordered Questions created by one reviewed AI draft import."""

    __tablename__ = "question_ai_import_items"

    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_ai_import_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "position",
            name="uq_question_ai_import_items_batch_position",
        ),
        UniqueConstraint(
            "batch_id",
            "question_id",
            name="uq_question_ai_import_items_batch_question",
        ),
        Index("ix_question_ai_import_items_question", "question_id"),
    )
