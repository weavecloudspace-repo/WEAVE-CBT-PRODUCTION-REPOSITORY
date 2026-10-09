"""Database models for locally owned CBT question banks and questions."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

QUESTION_BANK_NAME_MAX_LENGTH = 255


class QuestionType(StrEnum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"


class QuestionBank(Base):
    """Locally owned question collection for one synchronized CurriculumSubject."""

    __tablename__ = "question_banks"

    curriculum_subject_id: Mapped[UUID] = mapped_column(
        ForeignKey("curriculum_subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(QUESTION_BANK_NAME_MAX_LENGTH), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sql_text("true")
    )

    __table_args__ = (
        UniqueConstraint(
            "curriculum_subject_id",
            "name",
            name="uq_question_banks_curriculum_subject_name",
        ),
        Index(
            "ix_question_banks_curriculum_subject_active",
            "curriculum_subject_id",
            "is_active",
        ),
    )


class Question(Base):
    __tablename__ = "questions"

    bank_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_banks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    question_type: Mapped[QuestionType] = mapped_column(
        SQLEnum(
            QuestionType,
            name="question_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=QuestionType.SINGLE_CHOICE,
        server_default=QuestionType.SINGLE_CHOICE.value,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=sql_text("1"),
    )
    created_by_actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    last_edited_by_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_actors.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sql_text("true")
    )

    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_questions_version_positive"),
        Index("ix_questions_bank_active", "bank_id", "is_active"),
    )


class QuestionOption(Base):
    __tablename__ = "question_options"

    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    is_correct: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sql_text("false"),
    )

    __table_args__ = (
        UniqueConstraint(
            "question_id", "position", name="uq_question_options_question_position"
        ),
        CheckConstraint("position >= 1", name="ck_question_options_position_positive"),
        CheckConstraint(
            "text IS NOT NULL OR image_asset_id IS NOT NULL",
            name="ck_question_options_content_required",
        ),
        Index("ix_question_options_question_position", "question_id", "position"),
    )
