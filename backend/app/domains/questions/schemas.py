# ===============================================#
# backend.app.domains.questions.schemas.py
# ===============================================#

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.questions.models import QuestionType

MAX_BANK_DESCRIPTION_LENGTH = 4_000
MAX_QUESTION_PROMPT_LENGTH = 20_000
MAX_QUESTION_INSTRUCTION_LENGTH = 10_000
MAX_OPTION_TEXT_LENGTH = 10_000
MAX_OPTIONS_PER_QUESTION = 50


class InputBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, use_enum_values=True)


class OutputBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class QuestionBankCreate(InputBase):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(
        default=None, max_length=MAX_BANK_DESCRIPTION_LENGTH
    )


class QuestionBankUpdate(InputBase):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(
        default=None, max_length=MAX_BANK_DESCRIPTION_LENGTH
    )
    curriculum_subject_id: UUID | None = None


class QuestionBankResponse(OutputBase):
    id: UUID
    curriculum_subject_id: UUID
    name: str
    description: str | None
    created_by_actor_id: UUID
    is_active: bool
    can_delete: bool = False


class QuestionOptionCreate(InputBase):
    text: str | None = Field(default=None, max_length=MAX_OPTION_TEXT_LENGTH)
    image_asset_id: UUID | None = None
    is_correct: bool = False

    @model_validator(mode="after")
    def require_content(self) -> QuestionOptionCreate:
        if not self.text and self.image_asset_id is None:
            raise ValueError("An answer option must include text, an image, or both")
        return self


class SingleChoiceQuestionCreate(InputBase):
    prompt: str = Field(min_length=1, max_length=MAX_QUESTION_PROMPT_LENGTH)
    instruction: str | None = Field(
        default=None, max_length=MAX_QUESTION_INSTRUCTION_LENGTH
    )
    image_asset_id: UUID | None = None
    options: list[QuestionOptionCreate] = Field(
        min_length=2,
        max_length=MAX_OPTIONS_PER_QUESTION,
    )


class MultipleChoiceQuestionCreate(InputBase):
    prompt: str = Field(min_length=1, max_length=MAX_QUESTION_PROMPT_LENGTH)
    instruction: str | None = Field(
        default=None, max_length=MAX_QUESTION_INSTRUCTION_LENGTH
    )
    image_asset_id: UUID | None = None
    options: list[QuestionOptionCreate] = Field(
        min_length=2,
        max_length=MAX_OPTIONS_PER_QUESTION,
    )


class QuestionUpdate(InputBase):
    """PATCH payload; omitted fields are preserved, explicit null clears nullable fields."""

    expected_version: int | None = Field(default=None, ge=1)
    prompt: str | None = Field(default=None, max_length=MAX_QUESTION_PROMPT_LENGTH)
    instruction: str | None = Field(
        default=None, max_length=MAX_QUESTION_INSTRUCTION_LENGTH
    )
    image_asset_id: UUID | None = None
    options: list[QuestionOptionCreate] | None = Field(
        default=None,
        min_length=2,
        max_length=MAX_OPTIONS_PER_QUESTION,
    )


class QuestionOptionResponse(OutputBase):
    id: UUID
    question_id: UUID
    position: int
    text: str | None
    image_asset_id: UUID | None
    is_correct: bool


class QuestionResponse(OutputBase):
    id: UUID
    bank_id: UUID
    question_type: QuestionType
    prompt: str
    instruction: str | None
    image_asset_id: UUID | None
    version: int
    created_by_actor_id: UUID
    author_name: str
    last_edited_by_actor_id: UUID | None
    is_active: bool
    can_delete: bool = False
    options: list[QuestionOptionResponse] = Field(default_factory=list)
