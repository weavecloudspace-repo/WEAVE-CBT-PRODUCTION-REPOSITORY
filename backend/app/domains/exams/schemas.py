"""Schemas consumed by the exam service and route layers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.domains.exams.models import (
    ExamQuestionSelectionMode,
    ExamRosterStatus,
    ExamStatus,
)
from app.domains.exams.schedule_validation import validate_normal_entry_window


def _validate_future_exam_datetime(
    value: datetime | None,
    *,
    field_name: str,
) -> None:
    """Reject ambiguous or elapsed schedule timestamps supplied by clients."""

    if value is None:
        return
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    if value.astimezone(UTC) <= datetime.now(UTC):
        raise ValueError(f"{field_name} must be in the future")


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


# ========================== #
# CREATE
# ========================== #


class ExamCreate(InputBase):
    """Create a new revision-1 examination in DRAFT state."""

    session_id: UUID
    term_id: UUID
    curriculum_subject_id: UUID
    assessment_scheme_id: UUID
    assessment_component_id: UUID
    question_bank_id: UUID
    question_selection_mode: ExamQuestionSelectionMode = (
        ExamQuestionSelectionMode.RANDOM
    )
    question_count: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=255)
    instructions: str | None = None
    folder_color: str | None = Field(
        default=None,
        pattern=r"^#[0-9A-Fa-f]{6}$",
        description="Hex colour used by the examination folder card, for example #397fd6.",
    )
    duration_minutes: int = Field(gt=0)
    shuffle_questions: bool = True
    shuffle_options: bool = True
    scheduled_start_at: datetime | None = None
    latest_normal_start_at: datetime | None = None
    # Admins may nominate an academically eligible teacher as lead at create
    # time. Teacher creators are always their own lead, so this field may be
    # omitted by teacher clients.
    lead_teacher_id: UUID | None = None

    @model_validator(mode="after")
    def validate_start_window(self) -> ExamCreate:
        _validate_future_exam_datetime(
            self.scheduled_start_at,
            field_name="scheduled_start_at",
        )
        _validate_future_exam_datetime(
            self.latest_normal_start_at,
            field_name="latest_normal_start_at",
        )
        validate_normal_entry_window(
            self.scheduled_start_at, self.latest_normal_start_at
        )
        return self


# ========================== #
# UPDATE
# ========================== #


class ExamUpdate(InputBase):
    """PATCH payload for a DRAFT examination."""

    # The client version last read. Version 1 is the backwards-compatible
    # initial draft value; after any authoring mutation clients must use the
    # authoring_version returned by the server.
    expected_authoring_version: int = Field(default=1, ge=1)

    session_id: UUID | None = None
    term_id: UUID | None = None
    assessment_scheme_id: UUID | None = None
    assessment_component_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    instructions: str | None = None
    folder_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    duration_minutes: int | None = Field(default=None, gt=0)
    shuffle_questions: bool | None = None
    shuffle_options: bool | None = None
    scheduled_start_at: datetime | None = None
    latest_normal_start_at: datetime | None = None

    @model_validator(mode="after")
    def validate_patch_contract(self) -> ExamUpdate:
        non_nullable_fields = {
            "session_id",
            "term_id",
            "assessment_scheme_id",
            "assessment_component_id",
            "title",
            "duration_minutes",
            "shuffle_questions",
            "shuffle_options",
        }
        for field_name in non_nullable_fields:
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name} cannot be null")

        if "scheduled_start_at" in self.model_fields_set:
            _validate_future_exam_datetime(
                self.scheduled_start_at,
                field_name="scheduled_start_at",
            )
        if "latest_normal_start_at" in self.model_fields_set:
            _validate_future_exam_datetime(
                self.latest_normal_start_at,
                field_name="latest_normal_start_at",
            )

        if (
            "scheduled_start_at" in self.model_fields_set
            and "latest_normal_start_at" in self.model_fields_set
        ):
            validate_normal_entry_window(
                self.scheduled_start_at, self.latest_normal_start_at
            )
        return self


# ========================== #
# QUESTION CONFIGURATION
# ========================== #


class ExamQuestionConfiguration(InputBase):
    question_bank_id: UUID
    question_selection_mode: ExamQuestionSelectionMode
    question_count: int = Field(gt=0)
    clear_existing_manual_selections: bool = False
    expected_authoring_version: int = Field(default=1, ge=1)


class ManualQuestionAdd(InputBase):
    question_ids: list[UUID] = Field(min_length=1)
    expected_authoring_version: int = Field(default=1, ge=1)

    @field_validator("question_ids")
    @classmethod
    def validate_unique_question_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("question_ids cannot contain duplicate questions")
        return value


class ManualQuestionReorder(InputBase):
    question_ids: list[UUID] = Field(min_length=1)
    expected_authoring_version: int = Field(default=1, ge=1)

    @field_validator("question_ids")
    @classmethod
    def validate_unique_question_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("question_ids cannot contain duplicate questions")
        return value


class ManualQuestionRemove(InputBase):
    question_id: UUID
    expected_authoring_version: int = Field(default=1, ge=1)


class ExamAuthoringAction(InputBase):
    expected_authoring_version: int = Field(default=1, ge=1)


class ExamLeadAssignment(InputBase):
    """Assign an eligible teacher as lead, or null to return leadership to admin."""

    lead_teacher_id: UUID | None = None
    expected_authoring_version: int = Field(default=1, ge=1)


class ExamInvigilatorAssignment(InputBase):
    teacher_ids: list[UUID] = Field(min_length=1)


class ExamReasonPayload(InputBase):
    reason: str = Field(min_length=1)


class ExamResumePayload(InputBase):
    reason: str | None = Field(default=None, min_length=1)


# ========================== #
# RESPONSES
# ========================== #


class ExamResponse(OutputBase):
    id: UUID
    session_id: UUID
    term_id: UUID
    curriculum_subject_id: UUID
    assessment_scheme_id: UUID
    assessment_component_id: UUID
    question_bank_id: UUID
    question_selection_mode: ExamQuestionSelectionMode
    question_count: int
    title: str
    instructions: str | None
    folder_color: str | None
    duration_minutes: int
    shuffle_questions: bool
    shuffle_options: bool
    status: ExamStatus
    scheduled_start_at: datetime | None
    latest_normal_start_at: datetime | None
    roster_status: ExamRosterStatus
    roster_version: int
    roster_candidate_count: int
    authoring_version: int = 1
    revision_number: int
    revision_of_exam_id: UUID | None
    created_by_actor_id: UUID
    lead_teacher_id: UUID | None
    lead_assigned_by_actor_id: UUID | None
    lead_assigned_at: datetime | None
    submitted_by_actor_id: UUID | None
    submitted_at: datetime | None
    sealed_by_actor_id: UUID | None
    sealed_at: datetime | None
    activated_by_actor_id: UUID | None
    activated_at: datetime | None
    closed_by_actor_id: UUID | None
    closed_at: datetime | None
    cancelled_by_actor_id: UUID | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    component_maximum_score: Decimal | None
    created_at: datetime
    updated_at: datetime


class ExamQuestionSelectionResponse(OutputBase):
    id: UUID
    exam_id: UUID
    question_id: UUID
    position: int
    added_by_actor_id: UUID
    created_at: datetime
    updated_at: datetime


class ExamInvigilatorResponse(OutputBase):
    exam_id: UUID
    teacher_id: UUID
    created_at: datetime
    updated_at: datetime


class AcademicTeacherResponse(OutputBase):
    id: UUID
    teacher_account_id: UUID
    first_name: str | None
    last_name: str | None
    staff_id: str | None
    status: str
