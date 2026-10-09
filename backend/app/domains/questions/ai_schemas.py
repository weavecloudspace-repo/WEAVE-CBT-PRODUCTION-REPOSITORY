"""Question-domain contracts for Cloud-backed AI authoring drafts."""

from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.questions.schemas import QuestionResponse

AIQuestionType = Literal["single_choice", "multiple_choice"]
AIQuestionDifficulty = Literal["easy", "medium", "difficult"]
AIVisualMode = Literal["text_only", "auto"]
AIImageSource = Literal["search", "generated"]

MAX_AI_QUESTION_COUNT = 50
MAX_AI_IMAGE_BYTES = 5 * 1024 * 1024
MAX_AI_IMAGE_BASE64_LENGTH = ((MAX_AI_IMAGE_BYTES + 2) // 3) * 4
ALLOWED_AI_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


class QuestionAISchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class QuestionAIImage(QuestionAISchema):
    content_type: str = Field(min_length=1, max_length=100)
    data_base64: str = Field(min_length=1, max_length=MAX_AI_IMAGE_BASE64_LENGTH)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    alt_text: str | None = Field(default=None, max_length=2_000)
    source: AIImageSource
    source_url: str | None = None
    creator: str | None = None
    attribution_text: str | None = None
    license_name: str | None = None
    license_url: str | None = None

    @model_validator(mode="after")
    def validate_binary(self) -> Self:
        normalized_type = self.content_type.casefold()
        if normalized_type not in ALLOWED_AI_IMAGE_TYPES:
            raise ValueError("Unsupported AI image content type")
        self.content_type = normalized_type
        try:
            decoded = base64.b64decode(self.data_base64, validate=True)
        except (binascii.Error, ValueError, TypeError) as exc:
            raise ValueError(
                "data_base64 must contain valid Base64 image data"
            ) from exc
        if not decoded or len(decoded) > MAX_AI_IMAGE_BYTES:
            raise ValueError("AI image payload exceeds the maximum allowed size")
        digest = hashlib.sha256(decoded).hexdigest()
        if digest.casefold() != self.sha256.casefold():
            raise ValueError("AI image SHA-256 does not match data_base64")
        self.sha256 = self.sha256.casefold()
        return self


class QuestionAIDraftOption(QuestionAISchema):
    text: str | None = Field(default=None, max_length=10_000)
    image: QuestionAIImage | None = None
    is_correct: bool

    @model_validator(mode="after")
    def require_content(self) -> Self:
        if not self.text and self.image is None:
            raise ValueError("Answer options must contain text, an image, or both")
        return self


class QuestionAIDraft(QuestionAISchema):
    question_type: AIQuestionType
    prompt: str = Field(min_length=1, max_length=20_000)
    instruction: str | None = Field(default=None, max_length=10_000)
    image: QuestionAIImage | None = None
    options: list[QuestionAIDraftOption] = Field(min_length=2, max_length=50)

    @model_validator(mode="after")
    def validate_answers(self) -> Self:
        correct_count = sum(1 for option in self.options if option.is_correct)
        if self.question_type == "single_choice" and correct_count != 1:
            raise ValueError(
                "A single-choice question must have exactly one correct option"
            )
        if self.question_type == "multiple_choice":
            if correct_count < 2:
                raise ValueError(
                    "A multiple-choice question must have at least two correct options"
                )
            if correct_count == len(self.options):
                raise ValueError(
                    "A multiple-choice question must have at least one incorrect option"
                )
        return self


class QuestionAIGenerateRequest(QuestionAISchema):
    operation_id: UUID
    generation_prompt: str = Field(min_length=1, max_length=10_000)
    question_count: int = Field(ge=1, le=MAX_AI_QUESTION_COUNT)
    question_type_counts: dict[AIQuestionType, int] | None = None
    difficulty: AIQuestionDifficulty = "medium"
    visual_mode: AIVisualMode = "auto"
    context: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
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


class QuestionAIRegenerateDraftRequest(QuestionAISchema):
    operation_id: UUID
    generation_prompt: str = Field(min_length=1, max_length=10_000)
    existing_question: QuestionAIDraft
    instruction: str = Field(min_length=1, max_length=10_000)
    difficulty: AIQuestionDifficulty = "medium"
    visual_mode: AIVisualMode = "auto"
    context: str | None = Field(default=None, max_length=20_000)


class QuestionAIRegenerateStoredRequest(QuestionAISchema):
    operation_id: UUID
    generation_prompt: str = Field(min_length=1, max_length=10_000)
    instruction: str = Field(min_length=1, max_length=10_000)
    difficulty: AIQuestionDifficulty = "medium"
    visual_mode: AIVisualMode = "auto"
    context: str | None = Field(default=None, max_length=20_000)


class QuestionAICharge(QuestionAISchema):
    reservation_id: UUID
    credits_charged: int = Field(ge=0)
    credits_released: int = Field(ge=0)


class QuestionAIGenerateResponse(QuestionAISchema):
    operation_id: UUID
    questions: list[QuestionAIDraft]
    repaired: bool
    charge: QuestionAICharge


class QuestionAIRegenerateResponse(QuestionAISchema):
    operation_id: UUID
    question: QuestionAIDraft
    repaired: bool
    charge: QuestionAICharge


class QuestionAIBulkSaveRequest(QuestionAISchema):
    draft_id: UUID
    questions: list[QuestionAIDraft] = Field(
        min_length=1, max_length=MAX_AI_QUESTION_COUNT
    )


class QuestionAIBulkSaveResponse(QuestionAISchema):
    draft_id: UUID
    questions: list[QuestionResponse]
