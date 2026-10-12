"""Atomic question-authoring endpoint for lead/admin draft editing."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.core.database import DbSession
from app.domains.auth.dependencies import CurrentLocalActor
from app.domains.exams.question_authoring_schema import ExamQuestionAuthoringSave
from app.domains.exams.router import DOMAIN_ERRORS, _domain_http_error
from app.domains.exams.schemas import ExamResponse
from app.domains.exams.service import ExamService

router = APIRouter(prefix="/exams", tags=["Exams"])


@router.put("/{exam_id}/questions/authoring", response_model=ExamResponse)
async def save_exam_question_authoring(
    exam_id: UUID,
    payload: ExamQuestionAuthoringSave,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    """Save question source, mode, count and final manual selection together."""

    try:
        exam = await ExamService.save_question_authoring(
            db,
            actor=actor,
            exam_id=exam_id,
            payload=payload,
        )
    except DOMAIN_ERRORS as exc:
        raise _domain_http_error(exc) from exc
    return ExamResponse.model_validate(exam)
