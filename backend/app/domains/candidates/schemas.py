from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.attempts.models import AttemptEndReason, AttemptStatus
from app.domains.candidates.models import CandidateStatus
from app.domains.exams.models import ExamRosterStatus

CandidateAttemptStateFilter = Literal[
    "not_started",
    "in_progress",
    "interrupted",
    "submitted",
    "terminated",
]


class InputBase(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=True,
        extra="forbid",
    )


class OutputBase(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        use_enum_values=True,
    )


class CandidateStatusReasonPayload(InputBase):
    reason: str = Field(min_length=1, max_length=500)


class CandidateLateStartGrantPayload(InputBase):
    reason: str = Field(min_length=1)
    expires_at: datetime | None = None


class CandidateLateStartRevocationPayload(InputBase):
    reason: str = Field(min_length=1)


class CandidateBulkActionPayload(InputBase):
    candidate_ids: list[UUID] = Field(min_length=1, max_length=5000)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("candidate_ids")
    @classmethod
    def unique_candidate_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("candidate_ids cannot contain duplicates")
        return value


class CandidateBulkLateStartGrantPayload(CandidateBulkActionPayload):
    expires_at: datetime | None = None


class CandidateBulkActionResponse(OutputBase):
    action: Literal["block", "late_start"]
    updated_count: int
    candidate_ids: list[UUID]


class CandidateMakeupApprovalPayload(InputBase):
    reason: str = Field(
        min_length=1,
        max_length=500,
    )


class CandidateMakeupRevocationPayload(InputBase):
    reason: str = Field(
        min_length=1,
        max_length=500,
    )


class CandidateAttemptSummaryResponse(OutputBase):
    id: UUID
    status: AttemptStatus
    started_at: datetime
    ended_at: datetime | None
    end_reason: AttemptEndReason | None


class CandidateResponse(OutputBase):
    id: UUID

    exam_id: UUID
    enrollment_id: UUID
    student_id: UUID
    class_id: UUID
    class_name: str | None = None

    admission_number: str
    display_name: str

    status: CandidateStatus
    status_reason: str | None

    roster_version: int

    attempt: CandidateAttemptSummaryResponse | None = None
    late_start_authorized: bool = False
    late_start_required: bool = False

    created_at: datetime
    updated_at: datetime


class CandidateRosterClassResponse(OutputBase):
    id: UUID
    display_name: str


class CandidateRosterResponse(OutputBase):
    exam_id: UUID

    roster_status: ExamRosterStatus
    roster_version: int

    roster_candidate_count: int
    eligible_not_started_count: int = 0
    in_progress_count: int = 0
    interrupted_count: int = 0
    submitted_count: int = 0
    terminated_count: int = 0
    late_start_required_count: int = 0

    offset: int
    limit: int
    total: int

    classes: list[CandidateRosterClassResponse] = Field(default_factory=list)
    candidates: list[CandidateResponse]


class CandidateRosterRetryResponse(OutputBase):
    exam_id: UUID
    roster_status: ExamRosterStatus
    roster_version: int
    recovery_mode: Literal["prepare", "reconcile"]
    queued: bool


class CandidateMakeupAuthorizationResponse(OutputBase):
    id: UUID
    candidate_id: UUID

    approved_by_actor_id: UUID
    reason: str
    approved_at: datetime

    consumed_at: datetime | None

    revoked_at: datetime | None
    revoked_by_actor_id: UUID | None
    revocation_reason: str | None

    created_at: datetime
    updated_at: datetime


class MissedCandidateResponse(OutputBase):
    candidate: CandidateResponse
    makeup_authorization: CandidateMakeupAuthorizationResponse | None


class MissedCandidateListResponse(OutputBase):
    exam_id: UUID
    exam_title: str
    scheduled_start_at: datetime | None

    offset: int
    limit: int
    total: int

    candidates: list[MissedCandidateResponse]


class MakeupReviewCounts(OutputBase):
    exam_id: UUID
    total: int
    awaiting_approval: int
    approved: int
    writing: int
    paused: int
    completed: int
    revoked: int
    needs_review: int
    terminated: int
    blocked: int
    withdrawn: int


class MakeupReviewSetsResponse(OutputBase):
    exams: list[MakeupReviewCounts]


class MakeupReviewCandidate(OutputBase):
    id: UUID
    name: str
    admission_number: str
    class_name: str
    state: str
    authorization_id: UUID | None
    reason: str | None
    can_approve: bool
    can_revoke: bool
    remaining_seconds: int | None
    percentage: str | None


class MakeupReviewResponse(OutputBase):
    exam_id: UUID
    total: int
    offset: int
    limit: int
    blockers: list[str]
    fresh_question_count: int
    required_question_count: int
    available: bool
    candidates: list[MakeupReviewCandidate]


class CandidateLateStartAuthorizationResponse(OutputBase):
    id: UUID
    candidate_id: UUID
    granted_by_actor_id: UUID
    reason: str
    granted_at: datetime
    expires_at: datetime | None
    consumed_at: datetime | None
    revoked_at: datetime | None
    revoked_by_actor_id: UUID | None
    revocation_reason: str | None
    created_at: datetime
    updated_at: datetime
