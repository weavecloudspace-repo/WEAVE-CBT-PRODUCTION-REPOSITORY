from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.core.database import DbSession
from app.core.exceptions import AcademicAuthorizationError, AcademicScopeError
from app.domains.auth.dependencies import CurrentLocalActor
from app.domains.exams.exceptions import ExamAuthorizationError, ExamNotFound
from app.domains.exams.models import ExamRosterStatus, ExamStatus
from app.domains.exams.query_schemas import ExamListResponse
from app.domains.exams.query_service import ExamQueryService
from app.domains.exams.schemas import ExamResponse
from app.domains.exams.service import ExamService

router = APIRouter(
    prefix="/exams",
    tags=["Exams"],
)


@router.get("", response_model=ExamListResponse)
async def list_exams(
    db: DbSession,
    actor: CurrentLocalActor,
    session_id: UUID | None = None,
    term_id: UUID | None = None,
    curriculum_subject_id: UUID | None = None,
    level_id: UUID | None = None,
    subject_id: UUID | None = None,
    target_class_id: UUID | None = None,
    assessment_scheme_id: UUID | None = None,
    assessment_component_id: UUID | None = None,
    created_by_actor_id: UUID | None = None,
    exam_status: Annotated[ExamStatus | None, Query(alias="status")] = None,
    roster_status: ExamRosterStatus | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> ExamListResponse:
    try:
        rows, total = await ExamQueryService.list_visible_exams(
            db,
            actor=actor,
            session_id=session_id,
            term_id=term_id,
            curriculum_subject_id=curriculum_subject_id,
            level_id=level_id,
            subject_id=subject_id,
            target_class_id=target_class_id,
            assessment_scheme_id=assessment_scheme_id,
            assessment_component_id=assessment_component_id,
            created_by_actor_id=created_by_actor_id,
            status=exam_status,
            roster_status=roster_status,
            offset=offset,
            limit=limit,
        )
    except (AcademicAuthorizationError, ExamAuthorizationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except AcademicScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return ExamListResponse(
        offset=offset,
        limit=limit,
        total=total,
        exams=[ExamResponse.model_validate(row) for row in rows],
    )


@router.get(
    "/{exam_id}",
    response_model=ExamResponse,
)
async def get_exam(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ExamResponse:
    try:
        exam = await ExamService.get_exam(
            db,
            actor=actor,
            exam_id=exam_id,
        )
    except ExamNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (AcademicAuthorizationError, ExamAuthorizationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except AcademicScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return ExamResponse.model_validate(exam)
