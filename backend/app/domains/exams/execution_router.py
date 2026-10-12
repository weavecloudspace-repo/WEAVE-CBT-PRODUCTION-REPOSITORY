"""HTTP routes for result review after a local CBT sitting closes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.core.database import DbSession
from app.core.exceptions import AcademicAuthorizationError
from app.domains.auth.dependencies import CurrentLocalActor
from app.domains.exams.exceptions import (
    ExamAuthorizationError,
    ExamNotFound,
    ExamStateError,
)
from app.domains.exams.execution_schemas import (
    ExamExecutionControlResponse,
    ResultDecisionReason,
)
from app.domains.exams.execution_service import ExamExecutionService
from app.domains.exams.service import ExamService
from app.workers.producer import arq_producer

router = APIRouter(prefix="/exams", tags=["Exam Results Review"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ExamNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (AcademicAuthorizationError, ExamAuthorizationError)):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ExamStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/{exam_id}/execution-control",
    response_model=ExamExecutionControlResponse | None,
)
async def get_execution_control(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamExecutionControlResponse | None:
    try:
        await ExamService.get_exam(db, actor=actor, exam_id=exam_id)
        control = await ExamExecutionService.get_control(db, exam_id=exam_id)
    except (
        AcademicAuthorizationError,
        ExamAuthorizationError,
        ExamNotFound,
        ExamStateError,
        ValueError,
    ) as exc:
        raise _http_error(exc) from exc
    return (
        ExamExecutionControlResponse.model_validate(control)
        if control is not None
        else None
    )


@router.post(
    "/{exam_id}/results/approve",
    response_model=ExamExecutionControlResponse,
)
async def approve_exam_results(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamExecutionControlResponse:
    try:
        control = await ExamExecutionService.approve_results(
            db,
            actor=actor,
            exam_id=exam_id,
        )
    except (
        AcademicAuthorizationError,
        ExamNotFound,
        ExamStateError,
        ValueError,
    ) as exc:
        raise _http_error(exc) from exc

    # Approval is the only normal trigger that permits local scores to leave CBT.
    # Queue delivery is best-effort; PostgreSQL-backed maintenance reconstructs it.
    await arq_producer.enqueue("sync_exam_results", str(exam_id))
    return ExamExecutionControlResponse.model_validate(control)


@router.post(
    "/{exam_id}/results/void",
    response_model=ExamExecutionControlResponse,
)
async def void_exam_results(
    exam_id: UUID,
    payload: ResultDecisionReason,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamExecutionControlResponse:
    try:
        control = await ExamExecutionService.void_results(
            db,
            actor=actor,
            exam_id=exam_id,
            reason=payload.reason,
        )
    except (
        AcademicAuthorizationError,
        ExamNotFound,
        ExamStateError,
        ValueError,
    ) as exc:
        raise _http_error(exc) from exc
    return ExamExecutionControlResponse.model_validate(control)
