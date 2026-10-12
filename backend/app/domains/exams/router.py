from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.core.database import DbSession
from app.core.exceptions import AcademicAuthorizationError, AcademicScopeError
from app.domains.auth.dependencies import CurrentLocalActor
from app.domains.exams.exceptions import (
    ExamAuthorizationError,
    ExamNotFound,
    ExamStateError,
)
from app.domains.exams.execution_service import ExamExecutionService
from app.domains.exams.operations_service import ExamOperationsService
from app.domains.exams.schemas import (
    AcademicTeacherResponse,
    ExamAuthoringAction,
    ExamCreate,
    ExamInvigilatorAssignment,
    ExamInvigilatorResponse,
    ExamLeadAssignment,
    ExamQuestionConfiguration,
    ExamQuestionSelectionResponse,
    ExamReasonPayload,
    ExamResponse,
    ExamResumePayload,
    ExamUpdate,
    ManualQuestionAdd,
    ManualQuestionRemove,
    ManualQuestionReorder,
)
from app.domains.exams.service import ExamService
from app.domains.exams.timetable_schemas import ActivationPreflightResponse
from app.workers.producer import arq_producer

router = APIRouter(prefix="/exams", tags=["Exams"])


def _domain_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ExamNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (AcademicAuthorizationError, ExamAuthorizationError)):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, (AcademicScopeError, ExamStateError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    detail = str(exc)
    lowered = detail.lower()
    if "does not exist" in lowered:
        code = status.HTTP_404_NOT_FOUND
    elif any(
        marker in lowered
        for marker in (
            "cannot",
            "inactive",
            "already",
            "conflict",
            "not enough",
            "exceed",
        )
    ):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=detail)


def _activation_preflight_http_error(preflight) -> HTTPException:
    if "schedule_date_expired" in preflight.blockers:
        code = "activation_schedule_date_expired"
        message = (
            "This examination was scheduled for a previous date. "
            "Reschedule it before activation."
        )
    elif "too_early" in preflight.blockers:
        code = "activation_too_early"
        message = (
            "This examination is scheduled to start later. Wait until its "
            "scheduled start time before activating it."
        )
    elif "candidate_scope_conflict" in preflight.blockers:
        code = "candidate_scope_conflict"
        message = (
            "Some candidates are already taking another examination. Resolve "
            "that examination before activating this one."
        )
    elif preflight.affected_exams:
        code = "activation_schedule_impact"
        message = (
            "Starting this examination now would affect later examinations. "
            "Reschedule the affected timetable before activating it."
        )
    else:
        code = "activation_preflight_failed"
        message = (
            "This examination is not ready to be activated. Review the "
            "activation requirements and try again."
        )

    payload = ActivationPreflightResponse.model_validate(preflight).model_dump(
        mode="json"
    )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message, "preflight": payload},
    )


DOMAIN_ERRORS = (
    AcademicAuthorizationError,
    AcademicScopeError,
    ExamAuthorizationError,
    ExamNotFound,
    ExamStateError,
    ValueError,
)


@router.get(
    "/lead-candidates",
    response_model=list[AcademicTeacherResponse],
)
async def list_eligible_lead_teachers(
    curriculum_subject_id: UUID,
    term_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> list[AcademicTeacherResponse]:
    """Return teachers an administrator may appoint as lead for this paper scope."""

    try:
        teachers = await ExamService.list_eligible_lead_teachers(
            db,
            actor=actor,
            curriculum_subject_id=curriculum_subject_id,
            term_id=term_id,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return [AcademicTeacherResponse.model_validate(teacher) for teacher in teachers]


@router.post("", response_model=ExamResponse, status_code=status.HTTP_201_CREATED)
async def create_exam(
    payload: ExamCreate,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    try:
        exam = await ExamService.create_exam(db, actor=actor, payload=payload)
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return ExamResponse.model_validate(exam)


@router.patch("/{exam_id}", response_model=ExamResponse)
async def update_exam(
    exam_id: UUID,
    payload: ExamUpdate,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    try:
        exam = await ExamService.update_exam(
            db,
            actor=actor,
            payload=payload,
            exam_id=exam_id,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return ExamResponse.model_validate(exam)


@router.put("/{exam_id}/lead", response_model=ExamResponse)
async def assign_exam_lead(
    exam_id: UUID,
    payload: ExamLeadAssignment,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    try:
        exam = await ExamService.assign_lead_teacher(
            db,
            actor=actor,
            exam_id=exam_id,
            lead_teacher_id=payload.lead_teacher_id,
            expected_authoring_version=payload.expected_authoring_version,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return ExamResponse.model_validate(exam)


@router.put("/{exam_id}/questions/configuration", response_model=ExamResponse)
async def configure_exam_questions(
    exam_id: UUID,
    payload: ExamQuestionConfiguration,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    try:
        exam = await ExamService.configure_questions(
            db,
            actor=actor,
            exam_id=exam_id,
            payload=payload,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return ExamResponse.model_validate(exam)


@router.post("/{exam_id}/submit", response_model=ExamResponse)
async def submit_exam(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
    payload: ExamAuthoringAction | None = None,
) -> ExamResponse:
    try:
        exam = await ExamService.submit_exam(
            db,
            actor=actor,
            exam_id=exam_id,
            expected_authoring_version=(
                payload.expected_authoring_version if payload is not None else 1
            ),
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return ExamResponse.model_validate(exam)


@router.post("/{exam_id}/return-to-draft", response_model=ExamResponse)
async def return_exam_to_draft(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    try:
        exam = await ExamService.return_exam_to_draft(
            db,
            actor=actor,
            exam_id=exam_id,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return ExamResponse.model_validate(exam)


@router.delete("/{exam_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft_exam(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
    expected_authoring_version: int = 1,
) -> None:
    try:
        await ExamService.delete_draft_exam(
            db,
            actor=actor,
            exam_id=exam_id,
            expected_authoring_version=expected_authoring_version,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc


@router.post("/{exam_id}/seal", response_model=ExamResponse)
async def seal_exam(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    try:
        exam = await ExamService.seal_exam(db, actor=actor, exam_id=exam_id)
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc

    await arq_producer.enqueue("prepare_exam_roster", str(exam.id))
    return ExamResponse.model_validate(exam)


@router.post(
    "/{exam_id}/revisions",
    response_model=ExamResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_revision(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    try:
        exam = await ExamService.create_revision(db, actor=actor, exam_id=exam_id)
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return ExamResponse.model_validate(exam)


@router.post("/{exam_id}/activate", response_model=ExamResponse)
async def activate_exam(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    try:
        # Preflight and activation intentionally share this DB transaction. The
        # preflight acquires the same transaction-scoped level advisory lock used
        # by timetable mutations, so a validated recovery schedule cannot change
        # between this check and the lifecycle commit.
        preflight = await ExamOperationsService.activation_preflight(
            db,
            actor=actor,
            exam_id=exam_id,
        )
        if not preflight.can_activate:
            raise _activation_preflight_http_error(preflight)
        exam = await ExamService.activate_exam(db, actor=actor, exam_id=exam_id)
    except HTTPException:
        raise
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return ExamResponse.model_validate(exam)


@router.post("/{exam_id}/suspend", response_model=ExamResponse)
async def suspend_exam(
    exam_id: UUID,
    payload: ExamReasonPayload,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    try:
        exam = await ExamService.suspend_exam(
            db,
            actor=actor,
            exam_id=exam_id,
            reason=payload.reason,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return ExamResponse.model_validate(exam)


@router.post("/{exam_id}/resume", response_model=ExamResponse)
async def resume_exam(
    exam_id: UUID,
    payload: ExamResumePayload,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    try:
        exam = await ExamService.resume_exam(
            db,
            actor=actor,
            exam_id=exam_id,
            reason=payload.reason,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return ExamResponse.model_validate(exam)


@router.post("/{exam_id}/close", response_model=ExamResponse)
async def close_exam(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    """Request durable exam closure; finalization is completed by the worker."""

    try:
        exam = await ExamExecutionService.request_close(
            db,
            actor=actor,
            exam_id=exam_id,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc

    await arq_producer.enqueue("finalize_exam_close", str(exam.id))
    return ExamResponse.model_validate(exam)


@router.post("/{exam_id}/cancel", response_model=ExamResponse)
async def cancel_exam(
    exam_id: UUID,
    payload: ExamReasonPayload,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    """Request durable exam cancellation; finalization is completed by the worker."""

    try:
        exam = await ExamExecutionService.request_cancel(
            db,
            actor=actor,
            exam_id=exam_id,
            reason=payload.reason,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc

    await arq_producer.enqueue("finalize_exam_cancellation", str(exam.id))
    return ExamResponse.model_validate(exam)


@router.get(
    "/invigilators/available",
    response_model=list[AcademicTeacherResponse],
)
async def list_available_invigilators(
    db: DbSession,
    actor: CurrentLocalActor,
) -> list[AcademicTeacherResponse]:
    try:
        teachers = await ExamService.list_available_invigilators(db, actor=actor)
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return [AcademicTeacherResponse.model_validate(teacher) for teacher in teachers]


@router.get(
    "/{exam_id}/invigilators",
    response_model=list[ExamInvigilatorResponse],
)
async def list_exam_invigilators(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> list[ExamInvigilatorResponse]:
    try:
        rows = await ExamService.list_invigilators(db, actor=actor, exam_id=exam_id)
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return [ExamInvigilatorResponse.model_validate(row) for row in rows]


@router.post(
    "/{exam_id}/invigilators",
    response_model=list[ExamInvigilatorResponse],
)
async def assign_exam_invigilators(
    exam_id: UUID,
    payload: ExamInvigilatorAssignment,
    db: DbSession,
    actor: CurrentLocalActor,
) -> list[ExamInvigilatorResponse]:
    try:
        rows = await ExamService.assign_invigilators(
            db,
            actor=actor,
            exam_id=exam_id,
            teacher_ids=payload.teacher_ids,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return [ExamInvigilatorResponse.model_validate(row) for row in rows]


@router.post(
    "/{exam_id}/invigilators/remove",
    response_model=list[ExamInvigilatorResponse],
)
async def remove_exam_invigilators(
    exam_id: UUID,
    payload: ExamInvigilatorAssignment,
    db: DbSession,
    actor: CurrentLocalActor,
) -> list[ExamInvigilatorResponse]:
    try:
        rows = await ExamService.remove_invigilators(
            db,
            actor=actor,
            exam_id=exam_id,
            teacher_ids=payload.teacher_ids,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return [ExamInvigilatorResponse.model_validate(row) for row in rows]


@router.get(
    "/{exam_id}/manual-questions",
    response_model=list[ExamQuestionSelectionResponse],
)
async def list_manual_questions(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> list[ExamQuestionSelectionResponse]:
    try:
        rows = await ExamService.list_manual_question_selections(
            db,
            actor=actor,
            exam_id=exam_id,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return [ExamQuestionSelectionResponse.model_validate(row) for row in rows]


@router.post("/{exam_id}/manual-questions", response_model=ExamResponse)
async def add_manual_questions(
    exam_id: UUID,
    payload: ManualQuestionAdd,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    try:
        exam = await ExamService.add_manual_questions(
            db,
            actor=actor,
            exam_id=exam_id,
            payload=payload,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return ExamResponse.model_validate(exam)


@router.post("/{exam_id}/manual-questions/remove", response_model=ExamResponse)
async def remove_manual_question(
    exam_id: UUID,
    payload: ManualQuestionRemove,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    try:
        exam = await ExamService.remove_manual_question(
            db,
            actor=actor,
            exam_id=exam_id,
            payload=payload,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return ExamResponse.model_validate(exam)


@router.post("/{exam_id}/manual-questions/reorder", response_model=ExamResponse)
async def reorder_manual_questions(
    exam_id: UUID,
    payload: ManualQuestionReorder,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    try:
        exam = await ExamService.reorder_manual_questions(
            db,
            actor=actor,
            exam_id=exam_id,
            payload=payload,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return ExamResponse.model_validate(exam)
