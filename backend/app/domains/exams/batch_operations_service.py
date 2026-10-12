"""Bounded, per-examination lifecycle batches using canonical transitions."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicAuthorizationError, AcademicScopeError
from app.domains.auth.models import LocalActor
from app.domains.exams.exceptions import ExamDomainError
from app.domains.exams.execution_service import ExamExecutionService
from app.domains.exams.operations_service import ExamOperationsService
from app.domains.exams.service import ExamService
from app.domains.exams.timetable_schemas import (
    ActivationPreflightResponse,
    BatchExamOperationItemResponse,
    BatchExamOperationRequest,
)
from app.workers.producer import arq_producer

logger = logging.getLogger(__name__)


class ExamBatchOperationsService:
    @staticmethod
    async def apply(
        db: AsyncSession, *, actor: LocalActor, payload: BatchExamOperationRequest
    ) -> list[BatchExamOperationItemResponse]:
        ExamOperationsService._require_admin(actor)
        results = []
        # Each canonical transition commits independently. Sequential processing
        # allows a successful activation to block later overlapping candidates.
        # Failed items roll back their transaction before the next item starts.
        for exam_id in payload.exam_ids:
            try:
                args = {"actor": actor, "exam_id": exam_id}
                finalization_job = None
                if payload.operation == "activate":
                    preflight = await ExamOperationsService.activation_preflight(
                        db, **args
                    )
                    if not preflight.can_activate:
                        results.append(
                            BatchExamOperationItemResponse(
                                exam_id=exam_id,
                                succeeded=False,
                                error="Activation is blocked. Review the timetable and candidate availability.",
                                preflight=ActivationPreflightResponse.model_validate(
                                    preflight
                                ),
                            )
                        )
                        await db.rollback()
                        continue
                    exam = await ExamService.activate_exam(db, **args)
                elif payload.operation == "suspend":
                    exam = await ExamService.suspend_exam(
                        db, **args, reason=payload.reason
                    )
                elif payload.operation == "resume":
                    exam = await ExamService.resume_exam(
                        db, **args, reason=payload.reason
                    )
                elif payload.operation == "close":
                    exam = await ExamExecutionService.request_close(db, **args)
                    finalization_job = "finalize_exam_close"
                else:
                    exam = await ExamExecutionService.request_cancel(
                        db, **args, reason=payload.reason
                    )
                    finalization_job = "finalize_exam_cancellation"
                result = BatchExamOperationItemResponse(
                    exam_id=exam_id, succeeded=True, status=exam.status
                )
                if finalization_job:
                    try:
                        await arq_producer.enqueue(finalization_job, str(exam_id))
                    except Exception:
                        # The request is already durable. Maintenance re-enqueues
                        # CLOSING/CANCELLING exams; never report this as unsaved.
                        logger.exception(
                            "Batch exam finalization enqueue failed for %s", exam_id
                        )
                        result.warning = "Operation saved; finalization will be retried by the recovery worker."
                results.append(result)
            except (
                ExamDomainError,
                AcademicAuthorizationError,
                AcademicScopeError,
                ValueError,
            ) as exc:
                await db.rollback()
                results.append(
                    BatchExamOperationItemResponse(
                        exam_id=exam_id, succeeded=False, error=str(exc)
                    )
                )
            except Exception:
                logger.exception("Batch exam operation failed for %s", exam_id)
                await db.rollback()
                results.append(
                    BatchExamOperationItemResponse(
                        exam_id=exam_id,
                        succeeded=False,
                        error="The operation could not be confirmed. Refresh this examination before trying again.",
                    )
                )
        return results
