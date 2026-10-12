"""Response schemas for calculated examination results."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.exams.execution_models import ExamResultDisposition
from app.domains.results.models import ResultSyncStatus


class ResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    attempt_id: UUID
    candidate_id: UUID
    exam_id: UUID
    assessment_component_id: UUID
    raw_score: int
    raw_max_score: int
    percentage: Decimal
    component_score: Decimal
    component_maximum_score: Decimal
    calculated_at: datetime
    sync_status: ResultSyncStatus
    sync_batch_id: UUID | None
    sync_attempts: int
    last_sync_attempt_at: datetime | None
    synced_at: datetime | None
    sync_error: str | None
    voided_at: datetime | None = None
    voided_by_actor_id: UUID | None = None
    void_reason: str | None = None


class ResultVoidPayload(BaseModel):
    reason: str = Field(min_length=1, max_length=1024)


class ResultReviewRowResponse(ResultResponse):
    candidate_display_name: str
    admission_number: str
    class_id: UUID


class ResultListResponse(BaseModel):
    exam_id: UUID
    offset: int
    limit: int
    total: int
    results: list[ResultReviewRowResponse]


class ResultReviewSetResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    exam_id: UUID
    completed_at: datetime | None = None
    result_disposition: ExamResultDisposition | None = None
    results_decided_at: datetime | None = None
    results_decision_reason: str | None = None
    result_count: int
    pending_count: int
    syncing_count: int
    synced_count: int
    failed_count: int
    voided_count: int = 0


class ResultReviewSetListResponse(BaseModel):
    reviews: list[ResultReviewSetResponse]


class ResultSyncRetryResponse(BaseModel):
    exam_id: UUID
    reset_count: int
    queued: bool
