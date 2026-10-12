"""Schemas for examination execution and result-review control."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.exams.execution_models import (
    ExamExecutionOperation,
    ExamOperationSource,
    ExamResultDisposition,
)


class ResultDecisionReason(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class ExamExecutionControlResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    exam_id: UUID
    operation: ExamExecutionOperation | None = None
    operation_source: ExamOperationSource | None = None
    operation_requested_at: datetime | None = None
    operation_requested_by_actor_id: UUID | None = None
    operation_reason: str | None = None
    operation_attempts: int
    last_operation_attempt_at: datetime | None = None
    operation_error: str | None = None
    result_disposition: ExamResultDisposition | None = None
    results_decided_at: datetime | None = None
    results_decided_by_actor_id: UUID | None = None
    results_decision_reason: str | None = None
