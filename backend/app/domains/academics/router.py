from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.core.database import DbSession
from app.core.exceptions import AcademicAuthorizationError, AcademicScopeError
from app.domains.academics.repository import AcademicRepository
from app.domains.academics.schemas import (
    AcademicSessionResponse,
    AcademicTermResponse,
    AssessmentComponentResponse,
    AssessmentSchemeResponse,
    AuthorableCurriculumSubjectResponse,
    EligibleAcademicClassResponse,
    TeacherAssignmentResponse,
)
from app.domains.academics.service import AcademicQueryService
from app.domains.auth.dependencies import CurrentLocalActor

router = APIRouter(
    prefix="/academics",
    tags=["Academics"],
)


@router.get(
    "/session/current",
    response_model=AcademicSessionResponse,
)
async def get_current_academic_session(
    db: DbSession,
    _actor: CurrentLocalActor,
) -> AcademicSessionResponse:
    academic_session = await AcademicRepository.get_current_session(db)

    if academic_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current academic session is not available",
        )

    return AcademicSessionResponse.model_validate(academic_session)


@router.get(
    "/term/current",
    response_model=AcademicTermResponse,
)
async def get_current_academic_term(
    db: DbSession,
    _actor: CurrentLocalActor,
) -> AcademicTermResponse:
    academic_session = await AcademicRepository.get_current_session(db)
    if academic_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current academic session is not available",
        )

    academic_term = await AcademicRepository.get_current_term(
        db,
        session_id=academic_session.id,
    )

    if academic_term is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current academic term is not available",
        )
    return AcademicTermResponse.model_validate(academic_term)


@router.get(
    "/curriculum-subjects/authorable",
    response_model=list[AuthorableCurriculumSubjectResponse],
)
async def list_authorable_curriculum_subjects(
    db: DbSession,
    actor: CurrentLocalActor,
) -> list[AuthorableCurriculumSubjectResponse]:
    try:
        return await AcademicQueryService.list_authorable_curriculum_subjects(
            db,
            actor=actor,
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


@router.get(
    "/teacher-assignments/effective",
    response_model=list[TeacherAssignmentResponse],
)
async def list_effective_teacher_assignments(
    db: DbSession,
    actor: CurrentLocalActor,
) -> list[TeacherAssignmentResponse]:
    try:
        return await AcademicQueryService.list_effective_teacher_assignments(
            db,
            actor=actor,
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


@router.get(
    "/curriculum-subjects/{curriculum_subject_id}/eligible-classes",
    response_model=list[EligibleAcademicClassResponse],
)
async def list_eligible_classes_for_curriculum_subject(
    curriculum_subject_id: UUID,
    academic_term_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> list[EligibleAcademicClassResponse]:
    try:
        return await AcademicQueryService.list_eligible_classes_for_curriculum_subject(
            db,
            actor=actor,
            curriculum_subject_id=curriculum_subject_id,
            academic_term_id=academic_term_id,
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


@router.get(
    "/assessment-schemes",
    response_model=list[AssessmentSchemeResponse],
)
async def list_assessment_schemes(
    db: DbSession,
    actor: CurrentLocalActor,
    active_only: bool = True,
) -> list[AssessmentSchemeResponse]:
    try:
        return await AcademicQueryService.list_assessment_schemes(
            db,
            actor=actor,
            active_only=active_only,
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


@router.get(
    "/assessment-schemes/{assessment_scheme_id}/components",
    response_model=list[AssessmentComponentResponse],
)
async def list_assessment_components(
    assessment_scheme_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
    active_only: bool = True,
) -> list[AssessmentComponentResponse]:
    try:
        return await AcademicQueryService.list_assessment_components(
            db,
            actor=actor,
            assessment_scheme_id=assessment_scheme_id,
            active_only=active_only,
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
