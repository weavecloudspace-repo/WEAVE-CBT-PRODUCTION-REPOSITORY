"""HTTP routes for candidate examination attempts."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.core.database import DbSession
from app.core.exceptions import AcademicAuthorizationError
from app.domains.attempts.guarded_service import AttemptService
from app.domains.attempts.models import AttemptStatus
from app.domains.attempts.query_schemas import AttemptMonitorListResponse
from app.domains.attempts.query_service import AttemptQueryService
from app.domains.attempts.repository import AttemptRepository
from app.domains.attempts.schemas import (
    AttemptAnswerMutation,
    AttemptAnswerResponse,
    AttemptBulkInterruptPayload,
    AttemptBulkOperatorResponse,
    AttemptHeartbeatResponse,
    AttemptOperatorResponse,
    AttemptReasonPayload,
    AttemptResponse,
    AttemptSubmissionResponse,
)
from app.domains.attempts.service import AttemptStateError
from app.domains.auth.dependencies import CurrentLocalActor
from app.domains.auth.student_dependencies import CurrentStudentExamSession
from app.domains.exams.exceptions import ExamNotFound, ExamStateError
from app.domains.media.service import MediaService

student_router = APIRouter(prefix="/student/attempts", tags=["Student Attempts"])
operator_router = APIRouter(prefix="/attempts", tags=["Attempts"])
exam_router = APIRouter(prefix="/exams", tags=["Attempts"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ExamNotFound) or "does not exist" in str(exc).lower():
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, AcademicAuthorizationError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, (AttemptStateError, ExamStateError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


async def _attach_option_media(
    db: DbSession, attempt: AttemptResponse
) -> AttemptResponse:
    """Attach immutable option-media snapshot IDs with one batched lookup."""
    question_ids = [question.id for question in attempt.questions]
    allocations = await AttemptRepository.list_option_allocations_for_questions(
        db, question_ids
    )
    media_by_option_id = {
        allocation.id: allocation.image_asset_id for allocation in allocations
    }
    for question in attempt.questions:
        for option in question.options:
            option.image_asset_id = media_by_option_id.get(option.id)
    return attempt


async def _load_current_attempt(
    db: DbSession, context: CurrentStudentExamSession
) -> AttemptResponse:
    attempt = await AttemptService.get_current(db, context=context)
    return await _attach_option_media(db, attempt)


async def _current_attempt_row(db: DbSession, context: CurrentStudentExamSession):
    attempt = await AttemptRepository.get_attempt_by_candidate_id(
        db, context.candidate_id
    )
    if attempt is None:
        raise AttemptStateError("Candidate has not started this examination")
    return attempt


@student_router.post("/current/start", response_model=AttemptResponse)
async def start_current_attempt(
    db: DbSession, context: CurrentStudentExamSession
) -> AttemptResponse:
    try:
        attempt = await AttemptService.start_current(db, context=context)
        return await _attach_option_media(db, attempt)
    except (AttemptStateError, ExamNotFound, ExamStateError, ValueError) as exc:
        raise _http_error(exc) from exc


@student_router.get("/current", response_model=AttemptResponse)
async def get_current_attempt(
    db: DbSession, context: CurrentStudentExamSession
) -> AttemptResponse:
    try:
        return await _load_current_attempt(db, context)
    except (AttemptStateError, ExamNotFound, ExamStateError, ValueError) as exc:
        raise _http_error(exc) from exc


@student_router.get("/current/result", response_model=AttemptSubmissionResponse)
async def get_current_attempt_result(
    db: DbSession, context: CurrentStudentExamSession
) -> AttemptSubmissionResponse:
    try:
        return await AttemptService.get_current_result(db, context=context)
    except (AttemptStateError, ExamNotFound, ExamStateError, ValueError) as exc:
        raise _http_error(exc) from exc


@student_router.post("/current/heartbeat", response_model=AttemptHeartbeatResponse)
async def heartbeat_current_attempt(
    db: DbSession,
    context: CurrentStudentExamSession,
) -> AttemptHeartbeatResponse:
    try:
        return await AttemptService.heartbeat_current(db, context=context)
    except (AttemptStateError, ExamNotFound, ExamStateError, ValueError) as exc:
        raise _http_error(exc) from exc


@student_router.get("/current/questions/{attempt_question_id}/image")
async def get_current_question_image(
    attempt_question_id: UUID,
    db: DbSession,
    context: CurrentStudentExamSession,
) -> Response:
    try:
        attempt = await _current_attempt_row(db, context)
        question = await AttemptRepository.get_question_allocation_by_id(
            db, attempt_question_id
        )
    except (AttemptStateError, ValueError) as exc:
        raise _http_error(exc) from exc
    if question is None or question.attempt_id != attempt.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question does not belong to this attempt.",
        )
    if question.image_asset_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question does not have an image.",
        )
    content = await MediaService.load_asset_content(
        db, asset_id=question.image_asset_id
    )
    return Response(
        content=content.data,
        media_type=content.mime_type,
        headers={"Cache-Control": "no-store"},
    )


@student_router.get(
    "/current/questions/{attempt_question_id}/options/{attempt_option_id}/image"
)
async def get_current_option_image(
    attempt_question_id: UUID,
    attempt_option_id: UUID,
    db: DbSession,
    context: CurrentStudentExamSession,
) -> Response:
    try:
        attempt = await _current_attempt_row(db, context)
        question = await AttemptRepository.get_question_allocation_by_id(
            db, attempt_question_id
        )
        option = await AttemptRepository.get_option_allocation_by_id(
            db, attempt_option_id
        )
    except (AttemptStateError, ValueError) as exc:
        raise _http_error(exc) from exc
    if question is None or question.attempt_id != attempt.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question does not belong to this attempt.",
        )
    if option is None or option.attempt_question_id != question.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Answer option does not belong to this question.",
        )
    if option.image_asset_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Answer option does not have an image.",
        )
    content = await MediaService.load_asset_content(db, asset_id=option.image_asset_id)
    return Response(
        content=content.data,
        media_type=content.mime_type,
        headers={"Cache-Control": "no-store"},
    )


@student_router.put(
    "/current/questions/{attempt_question_id}/answer",
    response_model=AttemptAnswerResponse,
)
async def save_current_answer(
    attempt_question_id: UUID,
    payload: AttemptAnswerMutation,
    db: DbSession,
    context: CurrentStudentExamSession,
) -> AttemptAnswerResponse:
    try:
        return await AttemptService.mutate_answer(
            db,
            context=context,
            attempt_question_id=attempt_question_id,
            mutation_sequence=payload.mutation_sequence,
            selected_option_ids=payload.selected_option_ids,
            is_flagged=payload.is_flagged,
        )
    except (AttemptStateError, ExamNotFound, ExamStateError, ValueError) as exc:
        raise _http_error(exc) from exc


@student_router.post("/current/submit", response_model=AttemptSubmissionResponse)
async def submit_current_attempt(
    db: DbSession, context: CurrentStudentExamSession
) -> AttemptSubmissionResponse:
    try:
        return await AttemptService.submit_current(db, context=context)
    except (AttemptStateError, ExamNotFound, ExamStateError, ValueError) as exc:
        raise _http_error(exc) from exc


@exam_router.get("/{exam_id}/attempts", response_model=AttemptMonitorListResponse)
async def list_exam_attempts(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
    attempt_statuses: Annotated[
        list[AttemptStatus] | None, Query(alias="status")
    ] = None,
    candidate_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> AttemptMonitorListResponse:
    try:
        rows, total = await AttemptQueryService.list_exam_attempts(
            db,
            actor=actor,
            exam_id=exam_id,
            statuses=attempt_statuses,
            candidate_id=candidate_id,
            offset=offset,
            limit=limit,
        )
    except (
        AcademicAuthorizationError,
        AttemptStateError,
        ExamNotFound,
        ExamStateError,
        ValueError,
    ) as exc:
        raise _http_error(exc) from exc
    return AttemptMonitorListResponse(
        exam_id=exam_id, offset=offset, limit=limit, total=total, attempts=rows
    )


@exam_router.post(
    "/{exam_id}/attempts/bulk-interrupt",
    response_model=AttemptBulkOperatorResponse,
)
async def bulk_interrupt_attempts(
    exam_id: UUID,
    payload: AttemptBulkInterruptPayload,
    db: DbSession,
    actor: CurrentLocalActor,
) -> AttemptBulkOperatorResponse:
    try:
        return await AttemptService.bulk_interrupt_attempts(
            db,
            actor=actor,
            exam_id=exam_id,
            attempt_ids=payload.attempt_ids,
            reason=payload.reason,
        )
    except (
        AcademicAuthorizationError,
        AttemptStateError,
        ExamNotFound,
        ExamStateError,
        ValueError,
    ) as exc:
        raise _http_error(exc) from exc


@operator_router.post("/{attempt_id}/interrupt", response_model=AttemptOperatorResponse)
async def interrupt_attempt(
    attempt_id: UUID,
    payload: AttemptReasonPayload,
    db: DbSession,
    actor: CurrentLocalActor,
) -> AttemptOperatorResponse:
    try:
        return await AttemptService.interrupt_attempt(
            db, actor=actor, attempt_id=attempt_id, reason=payload.reason
        )
    except (
        AcademicAuthorizationError,
        AttemptStateError,
        ExamNotFound,
        ExamStateError,
        ValueError,
    ) as exc:
        raise _http_error(exc) from exc


@operator_router.post("/{attempt_id}/resume", response_model=AttemptOperatorResponse)
async def resume_attempt(
    attempt_id: UUID,
    payload: AttemptReasonPayload,
    db: DbSession,
    actor: CurrentLocalActor,
) -> AttemptOperatorResponse:
    try:
        return await AttemptService.resume_attempt(
            db, actor=actor, attempt_id=attempt_id, reason=payload.reason
        )
    except (
        AcademicAuthorizationError,
        AttemptStateError,
        ExamNotFound,
        ExamStateError,
        ValueError,
    ) as exc:
        raise _http_error(exc) from exc


@operator_router.post("/{attempt_id}/terminate", response_model=AttemptOperatorResponse)
async def terminate_attempt(
    attempt_id: UUID,
    payload: AttemptReasonPayload,
    db: DbSession,
    actor: CurrentLocalActor,
) -> AttemptOperatorResponse:
    try:
        return await AttemptService.terminate_attempt(
            db, actor=actor, attempt_id=attempt_id, reason=payload.reason
        )
    except (
        AcademicAuthorizationError,
        AttemptStateError,
        ExamNotFound,
        ExamStateError,
        ValueError,
    ) as exc:
        raise _http_error(exc) from exc
