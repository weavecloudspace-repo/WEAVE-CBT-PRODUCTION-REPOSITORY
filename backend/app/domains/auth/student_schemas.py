"""Schemas for local/offline student CBT authentication."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StudentExamAvailability(StrEnum):
    NO_EXAM = "no_exam"
    WAITING_FOR_ACTIVATION = "waiting_for_activation"
    READY = "ready"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    MAKEUP = "makeup"


class StudentLoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    admission_number: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class StudentLoginResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    student_id: UUID
    candidate_id: UUID | None = None
    exam_id: UUID | None = None
    exam_title: str | None = None
    subject_name: str | None = None
    duration_minutes: int | None = None
    display_name: str
    availability: StudentExamAvailability
    status_message: str
    is_makeup: bool = False
    has_unfinished_attempt: bool = False
    scheduled_start_at: datetime | None = None
    activated_at: datetime | None = None


class StudentSessionResponse(StudentLoginResponse):
    expires_at: datetime
