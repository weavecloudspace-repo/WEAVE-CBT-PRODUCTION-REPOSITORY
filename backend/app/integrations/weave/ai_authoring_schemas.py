"""Typed Weave Cloud transport contracts for CBT AI question authoring."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

AIQuestionType = Literal["single_choice", "multiple_choice"]
AIQuestionDifficulty = Literal["easy", "medium", "difficult"]
AIVisualMode = Literal["text_only", "auto"]


class WeaveAIQuestionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AIImagePayload(WeaveAIQuestionSchema):
    content_type: str
    data_base64: str
    sha256: str
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None
    source: Literal["search", "generated"] | None = None
    source_url: str | None = None
    creator: str | None = None
    attribution_text: str | None = None
    license_name: str | None = None
    license_url: str | None = None


class AIExistingQuestionOption(WeaveAIQuestionSchema):
    text: str | None = None
    image: AIImagePayload | None = None
    is_correct: bool


class AIExistingQuestion(WeaveAIQuestionSchema):
    question_type: AIQuestionType
    prompt: str
    instruction: str | None = None
    image: AIImagePayload | None = None
    options: list[AIExistingQuestionOption]


class AIGenerateQuestionsRequest(WeaveAIQuestionSchema):
    subject: str = Field(min_length=1, max_length=200)
    academic_level: str = Field(min_length=1, max_length=200)
    generation_prompt: str = Field(min_length=1, max_length=10_000)
    question_count: int = Field(ge=1, le=50)
    question_type_counts: dict[AIQuestionType, int] | None = None
    difficulty: AIQuestionDifficulty = "medium"
    visual_mode: AIVisualMode = "auto"
    context: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def validate_counts(self):
        if self.question_type_counts is not None:
            if any(
                type(count) is not int or count < 0
                for count in self.question_type_counts.values()
            ):
                raise ValueError(
                    "question_type_counts values must be non-negative integers"
                )
            if sum(self.question_type_counts.values()) != self.question_count:
                raise ValueError("question_type_counts must sum to question_count")
        return self


class AIRegenerateQuestionRequest(WeaveAIQuestionSchema):
    subject: str = Field(min_length=1, max_length=200)
    academic_level: str = Field(min_length=1, max_length=200)
    generation_prompt: str = Field(min_length=1, max_length=10_000)
    existing_question: AIExistingQuestion
    instruction: str = Field(min_length=1, max_length=10_000)
    difficulty: AIQuestionDifficulty = "medium"
    visual_mode: AIVisualMode = "auto"
    context: str | None = Field(default=None, max_length=20_000)


class AIResolvedImageResponse(WeaveAIQuestionSchema):
    content_type: str
    data_base64: str
    sha256: str
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None
    source: Literal["search", "generated"]
    source_url: str | None = None
    creator: str | None = None
    attribution_text: str | None = None
    license_name: str | None = None
    license_url: str | None = None


class AIQuestionOptionResponse(WeaveAIQuestionSchema):
    text: str | None = None
    is_correct: bool
    image: AIResolvedImageResponse | None = None


class AIQuestionResponse(WeaveAIQuestionSchema):
    question_type: AIQuestionType
    prompt: str
    instruction: str | None = None
    image: AIResolvedImageResponse | None = None
    options: list[AIQuestionOptionResponse]


class AICreditChargeResponse(WeaveAIQuestionSchema):
    reservation_id: UUID
    credits_charged: int = Field(ge=0)
    credits_released: int = Field(ge=0)


class AIGenerateQuestionsResponse(WeaveAIQuestionSchema):
    questions: list[AIQuestionResponse]
    repaired: bool
    charge: AICreditChargeResponse


class AIRegenerateQuestionResponse(WeaveAIQuestionSchema):
    question: AIQuestionResponse
    repaired: bool
    charge: AICreditChargeResponse
