"""Payload for saving an exam's question configuration and manual paper together."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.domains.exams.models import ExamQuestionSelectionMode
from app.domains.exams.schemas import InputBase


class ExamQuestionAuthoringSave(InputBase):
    """Persist the effective question setup for one draft in one transaction.

    The payload is intentionally a complete question-authoring snapshot rather
    than a patch. That lets a lead/admin change the bank, selection mode or
    question count and shape the resulting manual paper before anything is
    committed.
    """

    question_bank_id: UUID
    question_selection_mode: ExamQuestionSelectionMode
    question_count: int = Field(gt=0)
    manual_question_ids: list[UUID] = Field(default_factory=list)
    expected_authoring_version: int = Field(default=1, ge=1)

    @field_validator("manual_question_ids")
    @classmethod
    def validate_unique_manual_question_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("manual_question_ids cannot contain duplicate questions")
        return value

    @model_validator(mode="after")
    def validate_effective_question_setup(self) -> ExamQuestionAuthoringSave:
        mode = ExamQuestionSelectionMode(self.question_selection_mode)
        if mode == ExamQuestionSelectionMode.RANDOM and self.manual_question_ids:
            raise ValueError(
                "Random selection cannot include manual question selections"
            )
        if (
            mode == ExamQuestionSelectionMode.MANUAL
            and len(self.manual_question_ids) > self.question_count
        ):
            raise ValueError(
                "Manual selections cannot exceed the examination question count"
            )
        return self
