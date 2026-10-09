from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.core.database import DbSession
from app.core.exceptions import AcademicAuthorizationError
from app.domains.auth.dependencies import CurrentLocalActor
from app.domains.candidates.exceptions import CandidateRosterError
from app.domains.candidates.lifecycle_service import CandidateService
from app.domains.candidates.models import CandidateStatus
from app.domains.candidates.schemas import (
    CandidateAttemptStateFilter,
    CandidateBulkActionPayload,
    CandidateBulkActionResponse,
    CandidateBulkLateStartGrantPayload,
    CandidateLateStartAuthorizationResponse,
    CandidateLateStartGrantPayload,
    CandidateLateStartRevocationPayload,
    CandidateResponse,
    CandidateRosterResponse,
    CandidateRosterRetryResponse,
    CandidateStatusReasonPayload,
)
from app.domains.exams.exceptions import ExamNotFound
from app.workers.producer import arq_producer

router = APIRouter(tags=["Candidates"])


def _domain_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ExamNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    if isinstance(exc, AcademicAuthorizationError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )

    if isinstance(exc, CandidateRosterError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    detail = str(exc)
    lowered = detail.lower()

    if "does not exist" in lowered:
        code = status.HTTP_404_NOT_FOUND
    elif any(
        marker in lowered
        for marker in (
            "read-only",
            "only eligible",
            "only blocked",
            "only assigned",
            "already",
            "consumed",
            "active examination",
            "not part of this examination",
            "has already started",
            "attempt controls",
            "normal entry deadline",
        )
    ):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST

    return HTTPException(status_code=code, detail=detail)


@router.get(
    "/exams/{exam_id}/candidates",
    response_model=CandidateRosterResponse,
)
async def list_exam_roster(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
    candidate_status: Annotated[CandidateStatus | None, Query(alias="status")] = None,
    class_id: Annotated[UUID | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=128)] = None,
    attempt_state: Annotated[CandidateAttemptStateFilter | None, Query()] = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> CandidateRosterResponse:
    try:
        return await CandidateService.list_roster(
            db,
            actor=actor,
            exam_id=exam_id,
            status=candidate_status,
            class_id=class_id,
            search=search,
            attempt_state=attempt_state,
            offset=offset,
            limit=limit,
        )
    except (
        AcademicAuthorizationError,
        CandidateRosterError,
        ExamNotFound,
        ValueError,
    ) as exc:
        raise _domain_http_error(exc) from exc


@router.post(
    "/exams/{exam_id}/candidates/bulk-block",
    response_model=CandidateBulkActionResponse,
)
async def bulk_block_candidates(
    exam_id: UUID,
    payload: CandidateBulkActionPayload,
    db: DbSession,
    actor: CurrentLocalActor,
) -> CandidateBulkActionResponse:
    try:
        return await CandidateService.bulk_block_candidates(
            db,
            actor=actor,
            exam_id=exam_id,
            candidate_ids=payload.candidate_ids,
            reason=payload.reason,
        )
    except (
        AcademicAuthorizationError,
        CandidateRosterError,
        ExamNotFound,
        ValueError,
    ) as exc:
        raise _domain_http_error(exc) from exc


@router.post(
    "/exams/{exam_id}/candidates/bulk-late-start",
    response_model=CandidateBulkActionResponse,
)
async def bulk_grant_late_start(
    exam_id: UUID,
    payload: CandidateBulkLateStartGrantPayload,
    db: DbSession,
    actor: CurrentLocalActor,
) -> CandidateBulkActionResponse:
    try:
        return await CandidateService.bulk_grant_late_start(
            db,
            actor=actor,
            exam_id=exam_id,
            candidate_ids=payload.candidate_ids,
            reason=payload.reason,
            expires_at=payload.expires_at,
        )
    except (
        AcademicAuthorizationError,
        CandidateRosterError,
        ExamNotFound,
        ValueError,
    ) as exc:
        raise _domain_http_error(exc) from exc


@router.post(
    "/exams/{exam_id}/roster/retry",
    response_model=CandidateRosterRetryResponse,
)
async def retry_failed_roster(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> CandidateRosterRetryResponse:
    """Retry one FAILED sealed roster without making Redis authoritative."""

    try:
        exam, recovery_mode = await CandidateService.retry_failed_roster(
            db,
            actor=actor,
            exam_id=exam_id,
        )
    except (
        AcademicAuthorizationError,
        CandidateRosterError,
        ExamNotFound,
        ValueError,
    ) as exc:
        raise _domain_http_error(exc) from exc

    job_name = (
        "prepare_exam_roster" if recovery_mode == "prepare" else "reconcile_exam_roster"
    )
    queued = await arq_producer.enqueue(job_name, str(exam.id))

    return CandidateRosterRetryResponse(
        exam_id=exam.id,
        roster_status=exam.roster_status,
        roster_version=exam.roster_version,
        recovery_mode=recovery_mode,
        queued=queued,
    )


@router.get(
    "/candidates/{candidate_id}",
    response_model=CandidateResponse,
)
async def get_candidate(
    candidate_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> CandidateResponse:
    try:
        return await CandidateService.get_candidate(
            db,
            actor=actor,
            candidate_id=candidate_id,
        )
    except (
        AcademicAuthorizationError,
        CandidateRosterError,
        ExamNotFound,
        ValueError,
    ) as exc:
        raise _domain_http_error(exc) from exc


@router.post(
    "/candidates/{candidate_id}/block",
    response_model=CandidateResponse,
)
async def block_candidate(
    candidate_id: UUID,
    payload: CandidateStatusReasonPayload,
    db: DbSession,
    actor: CurrentLocalActor,
) -> CandidateResponse:
    try:
        return await CandidateService.block_candidate(
            db,
            actor=actor,
            candidate_id=candidate_id,
            reason=payload.reason,
        )
    except (
        AcademicAuthorizationError,
        CandidateRosterError,
        ExamNotFound,
        ValueError,
    ) as exc:
        raise _domain_http_error(exc) from exc


@router.post(
    "/candidates/{candidate_id}/unblock",
    response_model=CandidateResponse,
)
async def unblock_candidate(
    candidate_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> CandidateResponse:
    try:
        return await CandidateService.unblock_candidate(
            db,
            actor=actor,
            candidate_id=candidate_id,
        )
    except (
        AcademicAuthorizationError,
        CandidateRosterError,
        ExamNotFound,
        ValueError,
    ) as exc:
        raise _domain_http_error(exc) from exc


@router.post(
    "/candidates/{candidate_id}/late-start-authorizations",
    response_model=CandidateLateStartAuthorizationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def grant_late_start(
    candidate_id: UUID,
    payload: CandidateLateStartGrantPayload,
    db: DbSession,
    actor: CurrentLocalActor,
) -> CandidateLateStartAuthorizationResponse:
    try:
        return await CandidateService.grant_late_start(
            db,
            actor=actor,
            candidate_id=candidate_id,
            reason=payload.reason,
            expires_at=payload.expires_at,
        )
    except (
        AcademicAuthorizationError,
        CandidateRosterError,
        ExamNotFound,
        ValueError,
    ) as exc:
        raise _domain_http_error(exc) from exc


@router.get(
    "/candidates/{candidate_id}/late-start-authorizations",
    response_model=list[CandidateLateStartAuthorizationResponse],
)
async def list_late_start_authorizations(
    candidate_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> list[CandidateLateStartAuthorizationResponse]:
    try:
        return await CandidateService.list_late_start_authorizations(
            db,
            actor=actor,
            candidate_id=candidate_id,
        )
    except (
        AcademicAuthorizationError,
        CandidateRosterError,
        ExamNotFound,
        ValueError,
    ) as exc:
        raise _domain_http_error(exc) from exc


@router.post(
    "/late-start-authorizations/{authorization_id}/revoke",
    response_model=CandidateLateStartAuthorizationResponse,
)
async def revoke_late_start(
    authorization_id: UUID,
    payload: CandidateLateStartRevocationPayload,
    db: DbSession,
    actor: CurrentLocalActor,
) -> CandidateLateStartAuthorizationResponse:
    try:
        return await CandidateService.revoke_late_start(
            db,
            actor=actor,
            authorization_id=authorization_id,
            reason=payload.reason,
        )
    except (
        AcademicAuthorizationError,
        CandidateRosterError,
        ExamNotFound,
        ValueError,
    ) as exc:
        raise _domain_http_error(exc) from exc
