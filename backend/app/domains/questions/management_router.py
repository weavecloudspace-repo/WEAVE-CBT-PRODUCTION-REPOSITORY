from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.core.database import DbSession
from app.core.exceptions import AcademicAuthorizationError, AcademicScopeError
from app.domains.auth.dependencies import CurrentLocalActor
from app.domains.questions.response_builder import build_question_responses
from app.domains.questions.schemas import QuestionResponse
from app.domains.questions.service import QuestionService

router = APIRouter(prefix="/questions", tags=["Questions"])


@router.get(
    "/manageable",
    response_model=list[QuestionResponse],
)
async def list_manageable_questions(
    db: DbSession,
    actor: CurrentLocalActor,
    bank_id: Annotated[UUID | None, Query()] = None,
    include_archived: bool = Query(default=True),
    offset: int = Query(default=0, ge=0),
    limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
) -> list[QuestionResponse]:
    """Return the question-management scope for the current actor.

    Administrators receive all questions on the local node. Teachers receive only
    questions they personally contributed, further constrained to question banks
    that remain inside their current synchronized teaching scope.

    ``offset`` and ``limit`` are available for server-side pagination. Omitting
    ``limit`` preserves the current workspace contract while callers migrate to a
    paginated management view.
    """

    try:
        questions = await QuestionService.list_actor_manageable_questions(
            db,
            actor=actor,
            bank_id=bank_id,
            active_only=not include_archived,
            offset=offset,
            limit=limit,
        )
    except AcademicAuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except AcademicScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return await build_question_responses(db, questions, request_actor=actor)
