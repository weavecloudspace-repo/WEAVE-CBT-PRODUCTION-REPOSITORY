"""Administrator routes for missed-exam and makeup authorization workflows."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.core.database import DbSession
from app.core.exceptions import AcademicAuthorizationError
from app.domains.auth.dependencies import CurrentLocalActor
from app.domains.candidates.makeup_review_service import MakeupReviewService
from app.domains.candidates.schemas import (
    CandidateMakeupApprovalPayload,
    CandidateMakeupAuthorizationResponse,
    CandidateMakeupRevocationPayload,
    MakeupReviewResponse,
    MakeupReviewSetsResponse,
    MakeupStudentAddPayload,
    MissedCandidateListResponse,
)
from app.domains.candidates.service import CandidateService
from app.domains.exams.exceptions import ExamNotFound

router = APIRouter(tags=["Candidate Makeups"])


@router.get("/makeups/exams", response_model=MakeupReviewSetsResponse)
async def list_makeup_review_sets(db: DbSession, actor: CurrentLocalActor):
    try:
        return await MakeupReviewService.overview(db, actor=actor)
    except AcademicAuthorizationError as exc:
        raise _http_error(exc) from exc


@router.get("/exams/{exam_id}/makeup-review", response_model=MakeupReviewResponse)
async def get_makeup_review(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    try:
        return await MakeupReviewService.detail(
            db, actor=actor, exam_id=exam_id, offset=offset, limit=limit
        )
    except (AcademicAuthorizationError, ExamNotFound, ValueError) as exc:
        raise _http_error(exc) from exc


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ExamNotFound) or "does not exist" in str(exc).lower():
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, AcademicAuthorizationError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "/exams/{exam_id}/missed-candidates",
    response_model=MissedCandidateListResponse,
)
async def list_missed_candidates(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> MissedCandidateListResponse:
    try:
        return await CandidateService.list_missed_candidates(
            db,
            actor=actor,
            exam_id=exam_id,
            offset=offset,
            limit=limit,
        )
    except (AcademicAuthorizationError, ExamNotFound, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/candidates/{candidate_id}/makeup-authorizations",
    response_model=CandidateMakeupAuthorizationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def approve_makeup(
    candidate_id: UUID,
    payload: CandidateMakeupApprovalPayload,
    db: DbSession,
    actor: CurrentLocalActor,
) -> CandidateMakeupAuthorizationResponse:
    try:
        return await CandidateService.approve_makeup(
            db,
            actor=actor,
            candidate_id=candidate_id,
            reason=payload.reason,
        )
    except (AcademicAuthorizationError, ExamNotFound, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get(
    "/candidates/{candidate_id}/makeup-authorizations",
    response_model=list[CandidateMakeupAuthorizationResponse],
)
async def list_makeup_authorizations(
    candidate_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> list[CandidateMakeupAuthorizationResponse]:
    try:
        return await CandidateService.list_makeup_authorizations(
            db,
            actor=actor,
            candidate_id=candidate_id,
        )
    except (AcademicAuthorizationError, ExamNotFound, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/makeup-authorizations/{authorization_id}/revoke",
    response_model=CandidateMakeupAuthorizationResponse,
)
async def revoke_makeup(
    authorization_id: UUID,
    payload: CandidateMakeupRevocationPayload,
    db: DbSession,
    actor: CurrentLocalActor,
) -> CandidateMakeupAuthorizationResponse:
    try:
        return await CandidateService.revoke_makeup(
            db,
            actor=actor,
            authorization_id=authorization_id,
            reason=payload.reason,
        )
    except (AcademicAuthorizationError, ExamNotFound, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/exams/{exam_id}/makeups/students",
    response_model=CandidateMakeupAuthorizationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_makeup_student(
    exam_id: UUID,
    payload: MakeupStudentAddPayload,
    db: DbSession,
    actor: CurrentLocalActor,
):
    try:
        return await CandidateService.add_makeup_student(
            db,
            actor=actor,
            exam_id=exam_id,
            admission_number=payload.admission_number,
            reason=payload.reason,
        )
    except (AcademicAuthorizationError, ExamNotFound, ValueError) as exc:
        raise _http_error(exc) from exc
