from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class InputBase(BaseModel):
    pass


class OutputBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AcademicSessionResponse(OutputBase):
    """carries academic session context"""

    id: UUID
    name: str
    status: str
    is_current: bool
    synced_at: datetime


class AcademicTermResponse(OutputBase):
    """carries academic term context"""

    id: UUID
    academic_session_id: UUID
    name: str
    status: str
    is_current: bool
    synced_at: datetime


class AuthorableCurriculumSubjectResponse(OutputBase):
    id: UUID
    curriculum_id: UUID

    academic_level_id: UUID
    academic_level_name: str
    academic_level_category: str
    academic_level_position: int

    subject_id: UUID
    subject_name: str
    subject_code: str | None

    is_elective: bool
    is_active: bool


class TeacherAssignmentResponse(OutputBase):
    id: UUID

    teacher_membership_id: UUID
    teacher_name: str

    class_id: UUID
    class_name: str

    curriculum_subject_id: UUID

    subject_id: UUID
    subject_name: str
    subject_code: str | None

    effective_from: date
    effective_to: date | None


class EligibleAcademicClassResponse(OutputBase):
    id: UUID
    academic_level_id: UUID
    arm_label_id: UUID
    display_name: str
    is_active: bool


class AssessmentSchemeResponse(OutputBase):
    id: UUID
    name: str
    status: str


class AssessmentComponentResponse(OutputBase):
    id: UUID
    assessment_scheme_id: UUID
    name: str
    code: str | None
    maximum_score: Decimal
    position: int
    is_active: bool
