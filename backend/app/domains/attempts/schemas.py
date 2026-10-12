"""Schemas for candidate attempt execution."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.attempts.models import AttemptEndReason, AttemptStatus
from app.domains.questions.models import QuestionType


class InputBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class OutputBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class AttemptOptionResponse(OutputBase):
    id: UUID
    position: int
    text: str | None
    image_asset_id: UUID | None = None


class AttemptQuestionResponse(OutputBase):
    id: UUID
    position: int
    question_type: QuestionType
    prompt: str
    instruction: str | None
    image_asset_id: UUID | None
    options: list[AttemptOptionResponse]
    selected_option_ids: list[UUID]
    is_flagged: bool
    mutation_sequence: int


class AttemptResponse(OutputBase):
    id: UUID
    candidate_id: UUID
    exam_id: UUID
    exam_title: str
    status: AttemptStatus
    started_at: datetime
    ended_at: datetime | None
    end_reason: AttemptEndReason | None
    time_limit_seconds: int
    remaining_seconds: int
    is_makeup: bool
    exam_suspended: bool
    questions: list[AttemptQuestionResponse]


class AttemptHeartbeatResponse(OutputBase):
    attempt_id: UUID
    status: AttemptStatus
    server_time: datetime
    last_heartbeat_at: datetime
    remaining_seconds: int
    exam_suspended: bool
    next_heartbeat_after_seconds: int = Field(ge=5, le=120)


class AttemptAnswerMutation(InputBase):
    mutation_sequence: int = Field(ge=1)
    selected_option_ids: list[UUID] = Field(default_factory=list)
    is_flagged: bool = False

    @field_validator("selected_option_ids")
    @classmethod
    def unique_options(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("selected_option_ids cannot contain duplicates")
        return value


class AttemptAnswerResponse(OutputBase):
    attempt_id: UUID
    attempt_question_id: UUID
    mutation_sequence: int
    selected_option_ids: list[UUID]
    is_flagged: bool
    remaining_seconds: int


class AttemptReasonPayload(InputBase):
    reason: str = Field(min_length=1, max_length=500)


class AttemptBulkInterruptPayload(AttemptReasonPayload):
    attempt_ids: list[UUID] = Field(min_length=1, max_length=5000)

    @field_validator("attempt_ids")
    @classmethod
    def unique_attempt_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("attempt_ids cannot contain duplicates")
        return value


class AttemptBulkOperatorResponse(OutputBase):
    action: Literal["interrupt"]
    updated_count: int
    attempt_ids: list[UUID]


class AttemptOperatorResponse(OutputBase):
    attempt_id: UUID
    status: AttemptStatus
    remaining_seconds: int
    ended_at: datetime | None
    end_reason: AttemptEndReason | None


class AttemptSubmissionResponse(OutputBase):
    voided_at: datetime | None = None
    subject_name: str
    attempt_id: UUID
    status: AttemptStatus
    end_reason: AttemptEndReason | None
    ended_at: datetime | None
    result_id: UUID
    raw_score: int
    raw_max_score: int
    percentage: str
    component_score: str
    component_maximum_score: str
