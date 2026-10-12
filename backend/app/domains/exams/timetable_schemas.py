from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domains.exams.models import ExamStatus


class BatchExamStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exam_ids: list[UUID] = Field(min_length=1)

    @field_validator("exam_ids")
    @classmethod
    def unique_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("exam_ids cannot contain duplicates")
        return value


class TimetableImpactResponse(BaseModel):
    exam_id: UUID
    title: str
    original_start_at: datetime
    proposed_start_at: datetime
    proposed_end_at: datetime


class BatchExamStartItemResponse(BaseModel):
    exam_id: UUID
    started: bool
    error: str | None = None
    impacts: list[TimetableImpactResponse] = Field(default_factory=list)


class BatchExamStartResponse(BaseModel):
    results: list[BatchExamStartItemResponse]


class ActivationScheduleImpactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    exam_id: UUID
    title: str
    status: ExamStatus
    scheduled_start_at: datetime | None
    scheduled_end_at: datetime | None
    suggested_start_at: datetime | None
    suggested_end_at: datetime | None
    delay_seconds: int | None
    blocked_by_exam_ids: list[UUID] | tuple[UUID, ...]
    reason: str


class ActivationPreflightResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    exam_id: UUID
    checked_at: datetime
    scheduled_start_at: datetime | None
    proposed_activation_at: datetime
    projected_end_at: datetime | None
    delay_seconds: int
    can_activate: bool
    blockers: list[str] | tuple[str, ...]
    conflicting_operational_exam_ids: list[UUID] | tuple[UUID, ...]
    affected_exams: (
        list[ActivationScheduleImpactResponse]
        | tuple[ActivationScheduleImpactResponse, ...]
    )
    suggestion_valid_until_at: datetime | None = None


class ActivationRescheduleItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exam_id: UUID
    scheduled_start_at: datetime

    @field_validator("scheduled_start_at")
    @classmethod
    def validate_future_start(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scheduled_start_at must include a timezone")
        normalized = value.astimezone(UTC)
        if normalized <= datetime.now(UTC):
            raise ValueError("scheduled_start_at must be in the future")
        return normalized


class ActivationRescheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    changes: list[ActivationRescheduleItem] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("changes")
    @classmethod
    def unique_exam_ids(
        cls, value: list[ActivationRescheduleItem]
    ) -> list[ActivationRescheduleItem]:
        exam_ids = [item.exam_id for item in value]
        if len(exam_ids) != len(set(exam_ids)):
            raise ValueError("changes cannot contain duplicate exam_ids")
        return value


class ActivationRescheduleResponse(BaseModel):
    rescheduled_exam_ids: list[UUID]
    preflight: ActivationPreflightResponse


class BatchExamOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    operation: Literal["activate", "suspend", "resume", "close", "cancel"]
    exam_ids: list[UUID] = Field(min_length=1, max_length=100)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("exam_ids")
    @classmethod
    def unique_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("exam_ids cannot contain duplicates")
        return value

    @model_validator(mode="after")
    def require_audit_reason(self):
        if self.operation in {"suspend", "cancel"} and not self.reason:
            raise ValueError("A reason is required for suspension or cancellation")
        return self


class BatchExamOperationItemResponse(BaseModel):
    exam_id: UUID
    succeeded: bool
    status: ExamStatus | None = None
    error: str | None = None
    warning: str | None = None
    preflight: ActivationPreflightResponse | None = None


class BatchExamOperationResponse(BaseModel):
    results: list[BatchExamOperationItemResponse]
