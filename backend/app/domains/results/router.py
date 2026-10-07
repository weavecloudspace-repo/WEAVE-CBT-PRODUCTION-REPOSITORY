"""Read and recovery routes for locally calculated CBT results."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status

from app.core.database import DbSession
from app.core.exceptions import AcademicAuthorizationError, AcademicScopeError
from app.domains.auth.dependencies import CurrentLocalActor
from app.domains.exams.exceptions import ExamNotFound, ExamStateError
from app.domains.results.models import ResultSyncStatus
from app.domains.results.retry_service import ResultRetryService
from app.domains.results.schemas import (
    ResultListResponse,
    ResultResponse,
    ResultReviewRowResponse,
    ResultReviewSetListResponse,
    ResultReviewSetResponse,
    ResultSyncRetryResponse,
    ResultVoidPayload,
)
from app.domains.results.service import ResultService
from app.workers.producer import arq_producer

router = APIRouter(tags=["Results"])


@router.post("/results/{result_id}/void", response_model=ResultResponse)
async def void_individual_result(
    result_id: UUID, payload: ResultVoidPayload, db: DbSession, actor: CurrentLocalActor
):
    try:
        result = await ResultService.void_result(
            db, actor=actor, result_id=result_id, reason=payload.reason
        )
    except (
        AcademicAuthorizationError,
        ExamNotFound,
        ExamStateError,
        ValueError,
    ) as exc:
        raise _http_error(exc) from exc
    return ResultResponse.model_validate(result)


@router.post("/results/{result_id}/restore", response_model=ResultResponse)
async def restore_individual_result(
    result_id: UUID, payload: ResultVoidPayload, db: DbSession, actor: CurrentLocalActor
):
    try:
        result = await ResultService.restore_result(
            db, actor=actor, result_id=result_id, reason=payload.reason
        )
    except (
        AcademicAuthorizationError,
        ExamNotFound,
        ExamStateError,
        ValueError,
    ) as exc:
        raise _http_error(exc) from exc
    response = ResultResponse.model_validate(result)
    if result.sync_status == ResultSyncStatus.PENDING:
        # Restoration commits before enqueueing. A new job identity avoids an
        # earlier completed exam job suppressing this newly eligible score.
        # The worker still enforces academic approval; maintenance recovers
        # pending rows if Redis is unavailable during this handoff.
        await arq_producer.enqueue(
            "sync_exam_results",
            str(result.exam_id),
            _job_id=f"weave-cbt:restore-result:{result.id}:{uuid4()}",
        )
    return response


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ExamNotFound) or "does not exist" in str(exc).lower():
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, AcademicAuthorizationError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, (AcademicScopeError, ExamStateError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/results/review-sets", response_model=ResultReviewSetListResponse)
async def list_result_review_sets(
    db: DbSession,
    actor: CurrentLocalActor,
) -> ResultReviewSetListResponse:
    """List terminal examination result sets for administrator review."""

    try:
        rows = await ResultService.list_result_review_sets(db, actor=actor)
    except (AcademicAuthorizationError, ValueError) as exc:
        raise _http_error(exc) from exc
    return ResultReviewSetListResponse(
        reviews=[ResultReviewSetResponse.model_validate(row) for row in rows]
    )


@router.get("/results/{result_id}", response_model=ResultResponse)
async def get_result(
    result_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ResultResponse:
    try:
        result = await ResultService.get_result(db, actor=actor, result_id=result_id)
    except (
        AcademicAuthorizationError,
        AcademicScopeError,
        ExamNotFound,
        ValueError,
    ) as exc:
        raise _http_error(exc) from exc
    return ResultResponse.model_validate(result)


@router.get("/exams/{exam_id}/results", response_model=ResultListResponse)
async def list_exam_results(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
    search: str | None = Query(default=None, max_length=255),
    sync_status: ResultSyncStatus | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> ResultListResponse:
    try:
        rows, total = await ResultService.list_exam_result_review_rows(
            db,
            actor=actor,
            exam_id=exam_id,
            search=search,
            sync_status=sync_status,
            offset=offset,
            limit=limit,
        )
    except (
        AcademicAuthorizationError,
        AcademicScopeError,
        ExamNotFound,
        ValueError,
    ) as exc:
        raise _http_error(exc) from exc

    results = []
    for result, candidate in rows:
        base = ResultResponse.model_validate(result).model_dump()
        results.append(
            ResultReviewRowResponse(
                **base,
                candidate_display_name=candidate.display_name,
                admission_number=candidate.admission_number,
                class_id=candidate.class_id,
            )
        )
    return ResultListResponse(
        exam_id=exam_id,
        offset=offset,
        limit=limit,
        total=total,
        results=results,
    )


@router.post(
    "/exams/{exam_id}/results/retry-sync",
    response_model=ResultSyncRetryResponse,
)
async def retry_failed_result_sync(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ResultSyncRetryResponse:
    """Retry only definitive/detached failures after an administrator fixes them."""

    try:
        reset_count = await ResultRetryService.retry_detached_failures(
            db,
            actor=actor,
            exam_id=exam_id,
        )
    except (
        AcademicAuthorizationError,
        AcademicScopeError,
        ExamNotFound,
        ExamStateError,
        ValueError,
    ) as exc:
        raise _http_error(exc) from exc

    queued = False
    if reset_count:
        queued = await arq_producer.enqueue("sync_exam_results", str(exam_id))
    return ResultSyncRetryResponse(
        exam_id=exam_id,
        reset_count=reset_count,
        queued=queued,
    )
