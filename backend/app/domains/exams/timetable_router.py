"""Batch exam-start and timetable-impact routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.core.database import DbSession
from app.core.exceptions import AcademicAuthorizationError
from app.domains.auth.dependencies import CurrentLocalActor
from app.domains.exams.batch_operations_service import ExamBatchOperationsService
from app.domains.exams.exceptions import (
    ExamNotFound,
    ExamScheduleImpactError,
    ExamStateError,
)
from app.domains.exams.operations_service import ExamOperationsService
from app.domains.exams.repository import ExamRepository
from app.domains.exams.service import ExamService
from app.domains.exams.timetable_schemas import (
    ActivationPreflightResponse,
    ActivationRescheduleRequest,
    ActivationRescheduleResponse,
    BatchExamOperationRequest,
    BatchExamOperationResponse,
    BatchExamStartItemResponse,
    BatchExamStartRequest,
    BatchExamStartResponse,
    TimetableImpactResponse,
)
from app.domains.exams.timetable_service import ExamTimetableService

router = APIRouter(prefix="/exams", tags=["Exam Timetable"])


@router.post("/operations-batch", response_model=BatchExamOperationResponse)
async def apply_exam_operations_batch(
    payload: BatchExamOperationRequest,
    db: DbSession,
    actor: CurrentLocalActor,
) -> BatchExamOperationResponse:
    _require_admin(actor)
    results = await ExamBatchOperationsService.apply(db, actor=actor, payload=payload)
    return BatchExamOperationResponse(results=results)


def _require_admin(actor) -> None:
    if not actor.is_active or actor.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="School administrator access required.",
        )


def _preflight_payload(preflight) -> dict:
    return ActivationPreflightResponse.model_validate(preflight).model_dump(mode="json")


@router.post(
    "/{exam_id}/activation-preflight",
    response_model=ActivationPreflightResponse,
)
async def activation_preflight(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ActivationPreflightResponse:
    try:
        preflight = await ExamOperationsService.activation_preflight(
            db,
            actor=actor,
            exam_id=exam_id,
            suggest_recovery_times=True,
        )
    except ExamNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AcademicAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ExamStateError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ActivationPreflightResponse.model_validate(preflight)


@router.post(
    "/{exam_id}/activation-reschedule",
    response_model=ActivationRescheduleResponse,
)
async def reschedule_activation_impact(
    exam_id: UUID,
    payload: ActivationRescheduleRequest,
    db: DbSession,
    actor: CurrentLocalActor,
) -> ActivationRescheduleResponse:
    changes = {item.exam_id: item.scheduled_start_at for item in payload.changes}
    try:
        exams, preflight = await ExamOperationsService.reschedule_activation_impact(
            db,
            actor=actor,
            source_exam_id=exam_id,
            changes=changes,
            reason=payload.reason,
        )
    except ExamScheduleImpactError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "recovery_schedule_still_conflicts",
                "message": str(exc),
                "preflight": _preflight_payload(exc.preflight),
            },
        ) from exc
    except ExamNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AcademicAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ExamStateError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return ActivationRescheduleResponse(
        rescheduled_exam_ids=[exam.id for exam in exams],
        preflight=ActivationPreflightResponse.model_validate(preflight),
    )


@router.get("/{exam_id}/timetable-impact", response_model=list[TimetableImpactResponse])
async def timetable_impact(
    exam_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> list[TimetableImpactResponse]:
    _require_admin(actor)
    try:
        rows = await ExamTimetableService.impact_after_start(db, exam_id=exam_id)
    except ExamNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [TimetableImpactResponse(**row.__dict__) for row in rows]


@router.post("/start-batch", response_model=BatchExamStartResponse)
async def start_exam_batch(
    payload: BatchExamStartRequest,
    db: DbSession,
    actor: CurrentLocalActor,
) -> BatchExamStartResponse:
    """Start any mutually compatible exams, including parallel same-level scopes."""

    _require_admin(actor)

    results: list[BatchExamStartItemResponse] = []
    for exam_id in payload.exam_ids:
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id)
        if exam is None:
            results.append(
                BatchExamStartItemResponse(
                    exam_id=exam_id,
                    started=False,
                    error="Examination does not exist",
                )
            )
            continue

        try:
            # Batch-start is an execution action, not a suggestion surface, so
            # validate against the real current time with no rolling headroom.
            preflight = await ExamOperationsService.activation_preflight(
                db,
                actor=actor,
                exam_id=exam_id,
                suggest_recovery_times=False,
            )
            if not preflight.can_activate:
                if "schedule_date_expired" in preflight.blockers:
                    error = (
                        "This examination was scheduled for a previous date. "
                        "Reschedule it before activation."
                    )
                elif preflight.affected_exams:
                    error = (
                        "Starting this examination now would affect later "
                        "examinations. Reschedule the affected timetable first: "
                        + ", ".join(impact.title for impact in preflight.affected_exams)
                    )
                elif "candidate_scope_conflict" in preflight.blockers:
                    error = (
                        "Some candidates are already taking another examination. "
                        "Resolve that examination before activating this one."
                    )
                elif "too_early" in preflight.blockers:
                    error = (
                        "This examination is scheduled to start later. Wait until "
                        "its scheduled start time before activating it."
                    )
                else:
                    error = (
                        "This examination is not ready to be activated. Review the "
                        "activation requirements and try again."
                    )
                results.append(
                    BatchExamStartItemResponse(
                        exam_id=exam_id,
                        started=False,
                        error=error,
                    )
                )
                continue

            await ExamService.activate_exam(db, actor=actor, exam_id=exam_id)
            results.append(
                BatchExamStartItemResponse(
                    exam_id=exam_id,
                    started=True,
                )
            )
        except (ExamNotFound, ExamStateError, ValueError) as exc:
            results.append(
                BatchExamStartItemResponse(
                    exam_id=exam_id,
                    started=False,
                    error=str(exc),
                )
            )

    return BatchExamStartResponse(results=results)
