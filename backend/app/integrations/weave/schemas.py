"""Typed contracts for communication with Weave Cloud."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, model_validator

SYNC_SCHEMA_VERSION = 5


class WeavePairingRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    pairing_code: str = Field(..., min_length=8, max_length=20)
    server_name: str = Field(..., min_length=2, max_length=150)
    client_version: str | None = Field(default=None, max_length=50)


class WeaveTenantInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str


class WeavePairingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: UUID
    server_credential: SecretStr
    server_name: str
    hostname: str | None = None
    tenant: WeaveTenantInfo
    paired_at: datetime


class WeaveStaffLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr
    password: str


class WeaveStaffAuthResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_id: UUID
    membership_id: UUID | None = None
    tenant_id: UUID
    role: Literal["admin", "teacher"]
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None


class SyncContractBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WeaveSyncMetadata(SyncContractBase):
    schema_version: int = SYNC_SCHEMA_VERSION
    snapshot_id: UUID
    generated_at: datetime
    cursor: int = Field(ge=0)


class WeaveSchoolSnapshot(SyncContractBase):
    id: UUID
    name: str
    institution_type: str | None = None
    timezone: str


class WeaveServerSnapshot(SyncContractBase):
    id: UUID
    name: str


class WeaveAcademicSessionSnapshot(SyncContractBase):
    id: UUID
    name: str
    status: str
    is_current: bool


class WeaveAcademicTermSnapshot(SyncContractBase):
    id: UUID
    academic_session_id: UUID
    name: str
    status: str
    is_current: bool


class WeaveAcademicLevelSnapshot(SyncContractBase):
    id: UUID
    name: str
    category: str
    position: int
    specialization_required_from_term_position: int | None = None


class WeaveArmLabelSnapshot(SyncContractBase):
    id: UUID
    label: str


class WeaveDepartmentSnapshot(SyncContractBase):
    id: UUID
    academic_level_id: UUID
    name: str


class WeaveClassSnapshot(SyncContractBase):
    id: UUID
    academic_level_id: UUID
    arm_label_id: UUID
    display_name: str
    is_active: bool


class WeaveClassTermDepartmentSnapshot(SyncContractBase):
    id: UUID
    class_id: UUID
    academic_term_id: UUID
    department_id: UUID


class WeaveSubjectSnapshot(SyncContractBase):
    id: UUID
    name: str
    code: str | None = None
    is_active: bool


class WeaveCurriculumSnapshot(SyncContractBase):
    id: UUID
    academic_level_id: UUID


class WeaveCurriculumSubjectSnapshot(SyncContractBase):
    id: UUID
    curriculum_id: UUID
    subject_id: UUID
    is_elective: bool
    elective_group_id: UUID | None = None
    is_active: bool


class WeaveCurriculumSubjectDepartmentSnapshot(SyncContractBase):
    id: UUID
    curriculum_subject_id: UUID
    department_id: UUID


class WeaveAssessmentSchemeSnapshot(SyncContractBase):
    id: UUID
    name: str
    status: str


class WeaveAssessmentComponentSnapshot(SyncContractBase):
    id: UUID
    assessment_scheme_id: UUID
    name: str
    code: str | None = None
    maximum_score: Decimal
    position: int
    is_active: bool


class WeaveAdminSnapshot(SyncContractBase):
    id: UUID
    email: EmailStr
    status: str


class WeaveTeacherSnapshot(SyncContractBase):
    id: UUID
    teacher_account_id: UUID
    first_name: str | None = None
    last_name: str | None = None
    staff_id: str | None = None
    status: str


class WeaveTeacherAssignmentSnapshot(SyncContractBase):
    id: UUID
    teacher_membership_id: UUID
    class_id: UUID
    curriculum_subject_id: UUID
    effective_from: date
    effective_to: date | None = None


class WeaveStudentEnrollmentSnapshot(SyncContractBase):
    id: UUID
    student_id: UUID
    admission_number: str
    first_name: str | None = None
    last_name: str | None = None
    academic_level_id: UUID
    class_id: UUID | None = None
    academic_session_id: UUID
    is_current: bool
    student_status: str


class WeaveStudentElectiveSelectionSnapshot(SyncContractBase):
    id: UUID
    student_id: UUID
    elective_group_id: UUID
    curriculum_subject_id: UUID


class WeaveAcademicBootstrap(SyncContractBase):
    metadata: WeaveSyncMetadata
    school: WeaveSchoolSnapshot
    server: WeaveServerSnapshot
    sessions: list[WeaveAcademicSessionSnapshot]
    terms: list[WeaveAcademicTermSnapshot]
    levels: list[WeaveAcademicLevelSnapshot]
    arm_labels: list[WeaveArmLabelSnapshot]
    departments: list[WeaveDepartmentSnapshot]
    classes: list[WeaveClassSnapshot]
    class_term_departments: list[WeaveClassTermDepartmentSnapshot]
    subjects: list[WeaveSubjectSnapshot]
    curricula: list[WeaveCurriculumSnapshot]
    curriculum_subjects: list[WeaveCurriculumSubjectSnapshot]
    curriculum_subject_departments: list[WeaveCurriculumSubjectDepartmentSnapshot]
    assessment_schemes: list[WeaveAssessmentSchemeSnapshot]
    assessment_components: list[WeaveAssessmentComponentSnapshot]
    admins: list[WeaveAdminSnapshot]
    teachers: list[WeaveTeacherSnapshot]
    teacher_assignments: list[WeaveTeacherAssignmentSnapshot]
    student_enrollments: list[WeaveStudentEnrollmentSnapshot]
    student_elective_selections: list[WeaveStudentElectiveSelectionSnapshot] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def require_supported_schema(self) -> WeaveAcademicBootstrap:
        if self.metadata.schema_version != SYNC_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported Weave CBT sync schema version {self.metadata.schema_version}."
            )
        return self


WeaveSyncEntityType = Literal[
    "academic_level",
    "department",
    "arm_label",
    "class",
    "class_term_department",
    "academic_session",
    "academic_term",
    "subject",
    "curriculum",
    "curriculum_subject",
    "curriculum_subject_department",
    "assessment_scheme",
    "assessment_component",
    "admin",
    "teacher",
    "teacher_assignment",
    "student_enrollment",
    "student_elective_selection",
]
WeaveSyncOperation = Literal["created", "updated", "deleted"]


class WeaveSyncChange(SyncContractBase):
    event_id: UUID
    cursor: int = Field(ge=1)
    entity_type: WeaveSyncEntityType
    entity_id: UUID
    operation: WeaveSyncOperation
    schema_version: int = SYNC_SCHEMA_VERSION
    payload: dict[str, Any] | None = None
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_change(self) -> WeaveSyncChange:
        if self.schema_version != SYNC_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported Weave CBT sync schema version {self.schema_version}."
            )
        if self.operation == "deleted" and self.payload is not None:
            raise ValueError("Deleted sync changes must carry a null payload.")
        if self.operation != "deleted" and self.payload is None:
            raise ValueError("Created/updated sync changes require a payload.")
        return self


class WeaveSyncDelta(SyncContractBase):
    from_cursor: int = Field(ge=0)
    next_cursor: int = Field(ge=0)
    has_more: bool
    changes: list[WeaveSyncChange]


class WeaveResultScore(BaseModel):
    """One student's component score sent from CBT to Weave."""

    model_config = ConfigDict(extra="forbid")

    student_id: UUID
    score: Decimal = Field(ge=0, max_digits=5, decimal_places=2)


class WeaveResultBulkRequest(BaseModel):
    """One local CBT exam result batch sent to Weave."""

    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    source_exam_id: UUID
    academic_session_id: UUID
    academic_term_id: UUID
    academic_level_id: UUID
    curriculum_subject_id: UUID
    assessment_component_id: UUID
    exam_date: date
    scores: list[WeaveResultScore] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_unique_students(self) -> WeaveResultBulkRequest:
        student_ids = [item.student_id for item in self.scores]
        if len(student_ids) != len(set(student_ids)):
            raise ValueError(
                "Each student may appear only once in a Weave result batch."
            )
        return self


class WeaveResultBulkError(BaseModel):
    """One student score rejected by Weave."""

    model_config = ConfigDict(extra="forbid")

    student_id: UUID
    code: str = Field(min_length=1, max_length=100)
    detail: str = Field(min_length=1, max_length=1000)


class WeaveResultBulkResponse(BaseModel):
    """Acknowledgement returned by Weave after processing a result batch."""

    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    source_exam_id: UUID
    processed_at: datetime
    received: int = Field(ge=0)
    applied: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    rejected: int = Field(ge=0)
    errors: list[WeaveResultBulkError] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_processing_counts(self) -> WeaveResultBulkResponse:
        processed = self.applied + self.unchanged + self.rejected
        if processed != self.received:
            raise ValueError(
                "Applied, unchanged and rejected counts must equal received count."
            )
        if len(self.errors) != self.rejected:
            raise ValueError("Each rejected result must have a corresponding error.")
        return self
