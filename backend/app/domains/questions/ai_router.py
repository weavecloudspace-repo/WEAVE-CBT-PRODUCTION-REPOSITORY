"""AI authoring routes owned by the local question domain."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.core.database import DbSession
from app.core.exceptions import AcademicAuthorizationError, AcademicScopeError
from app.domains.auth.dependencies import CurrentLocalContext
from app.domains.questions.ai_schemas import (
    QuestionAIBulkSaveRequest,
    QuestionAIBulkSaveResponse,
    QuestionAIGenerateRequest,
    QuestionAIGenerateResponse,
    QuestionAIRegenerateDraftRequest,
    QuestionAIRegenerateResponse,
    QuestionAIRegenerateStoredRequest,
)
from app.domains.questions.ai_service import question_ai_service
from app.domains.questions.response_builder import build_question_responses
from app.domains.questions.router import _domain_http_error

router = APIRouter(prefix="/questions", tags=["Questions"])


@router.post(
    "/banks/{bank_id}/ai/generate",
    response_model=QuestionAIGenerateResponse,
)
async def generate_question_drafts(
    bank_id: UUID,
    payload: QuestionAIGenerateRequest,
    db: DbSession,
    context: CurrentLocalContext,
) -> QuestionAIGenerateResponse:
    try:
        return await question_ai_service.generate_questions(
            db,
            actor=context.actor,
            session_id=context.session.id,
            bank_id=bank_id,
            payload=payload,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc


@router.post(
    "/banks/{bank_id}/ai/regenerate",
    response_model=QuestionAIRegenerateResponse,
)
async def regenerate_question_draft(
    bank_id: UUID,
    payload: QuestionAIRegenerateDraftRequest,
    db: DbSession,
    context: CurrentLocalContext,
) -> QuestionAIRegenerateResponse:
    try:
        return await question_ai_service.regenerate_draft_question(
            db,
            actor=context.actor,
            session_id=context.session.id,
            bank_id=bank_id,
            payload=payload,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc


@router.post(
    "/{question_id}/ai/regenerate",
    response_model=QuestionAIRegenerateResponse,
)
async def regenerate_stored_question(
    question_id: UUID,
    payload: QuestionAIRegenerateStoredRequest,
    db: DbSession,
    context: CurrentLocalContext,
) -> QuestionAIRegenerateResponse:
    try:
        return await question_ai_service.regenerate_stored_question(
            db,
            actor=context.actor,
            session_id=context.session.id,
            question_id=question_id,
            payload=payload,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc


@router.post(
    "/banks/{bank_id}/ai/save",
    response_model=QuestionAIBulkSaveResponse,
)
async def persist_reviewed_question_drafts(
    bank_id: UUID,
    payload: QuestionAIBulkSaveRequest,
    db: DbSession,
    context: CurrentLocalContext,
) -> QuestionAIBulkSaveResponse:
    try:
        questions = await question_ai_service.persist_reviewed_questions(
            db,
            actor=context.actor,
            bank_id=bank_id,
            payload=payload,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return QuestionAIBulkSaveResponse(
        draft_id=payload.draft_id,
        questions=await build_question_responses(
            db,
            questions,
            request_actor=context.actor,
        ),
    )
