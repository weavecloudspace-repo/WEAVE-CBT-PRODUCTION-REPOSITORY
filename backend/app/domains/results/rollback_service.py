"""Durable local result withdrawal from WEAVE Cloud, with explicit resynchronization.

No Cloud network request is made until the local result status is held and
committed. The normal automatic sync worker can never republish held results.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicAuthorizationError
from app.domains.attempts.repository import AttemptRepository
from app.domains.audit.models import AuditActorType, AuditEvent
from app.domains.audit.repository import AuditRepository
from app.domains.auth.cloud_access import get_or_repair_weave_actor_access_token
from app.domains.auth.models import LocalActor
from app.domains.candidates.models import ExamCandidate
from app.domains.candidates.repository import CandidateRepository
from app.domains.exams.exceptions import ExamStateError
from app.domains.exams.execution_models import ExamResultDisposition
from app.domains.exams.execution_repository import ExamExecutionRepository
from app.domains.exams.models import ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.node.identity_store import node_identity_store
from app.domains.results.models import ExamResult, ResultSyncStatus
from app.domains.results.repository import ResultRepository
from app.domains.results.rollback_schemas import CloudRollbackResponse, LocalRollbackResponse
from app.integrations.weave.exceptions import WeaveIntegrationError
from app.integrations.weave.results import weave_result_gateway


class ResultRollbackService:
    @staticmethod
    def _admin(actor: LocalActor) -> None:
        if not actor.is_active or actor.role != "admin":
            raise AcademicAuthorizationError("An active administrator is required")

    @staticmethod
    def _reason(reason: str) -> str:
        reason = reason.strip()
        if not 5 <= len(reason) <= 1024:
            raise ExamStateError("Provide a rollback reason of 5 to 1024 characters")
        return reason

    @classmethod
    async def begin(
        cls, db: AsyncSession, *, actor: LocalActor, reason: str,
        result_id: UUID | None = None, batch_id: UUID | None = None,
    ) -> UUID:
        cls._admin(actor)
        reason = cls._reason(reason)
        if (result_id is None) == (batch_id is None):
            raise ExamStateError("Select one result or one synchronization batch")

        if result_id is not None:
            original = await ResultRepository.get_result_by_id(db, result_id)
            if original is None:
                raise ExamStateError("Result does not exist")
            exam_id = original.exam_id
        else:
            original = await db.scalar(
                select(ExamResult).where(
                    ExamResult.sync_batch_id == batch_id,
                    ExamResult.sync_status == ResultSyncStatus.SYNCED,
                ).limit(1)
            )
            if original is None:
                raise ExamStateError("No synchronized results exist in this batch")
            exam_id = original.exam_id

        exam = await ExamRepository.get_exam_by_id(db, exam_id, lock=True)
        if exam is None or exam.status != ExamStatus.CLOSED:
            raise ExamStateError("Only closed examination results can be rolled back")
        control = await ExamExecutionRepository.get_control(db, exam.id, lock=True)
        if (
            control is None
            or control.operation is not None
            or control.result_disposition != ExamResultDisposition.APPROVED
        ):
            raise ExamStateError("Examination results must be approved and finalized")

        if result_id is not None:
            rows = [await ResultRepository.get_result_by_id(db, result_id, lock=True)]
        else:
            # One original batch may contain a mixture of synced/rejected rows.
            rows = list((await db.execute(
                select(ExamResult).where(
                    ExamResult.sync_batch_id == batch_id,
                    ExamResult.sync_status == ResultSyncStatus.SYNCED,
                ).order_by(ExamResult.id).with_for_update()
            )).scalars().all())

        if not rows or any(
            row is None or row.exam_id != exam.id
            or row.sync_status != ResultSyncStatus.SYNCED
            or row.sync_batch_id is None or row.voided_at is not None
            for row in rows
        ):
            raise ExamStateError("Select only synchronized, non-voided results from one exam")
        if len({row.sync_batch_id for row in rows}) != 1:
            raise ExamStateError("A rollback must target one original synchronization batch")
        # New operation per explicit administrator request. All affected rows
        # retain this ID through offline recovery and Cloud completion.
        operation_id = uuid4()
        now = datetime.now(UTC)
        for row in rows:
            row.rollback_operation_id = operation_id
            row.rollback_original_batch_id = row.sync_batch_id
            row.rollback_previous_synced_at = row.synced_at
            row.rollback_requested_at = now
            row.rolled_back_at = None
            row.rollback_error = None
            row.synced_at = None
            row.sync_status = ResultSyncStatus.ROLLBACK_PENDING
        await ResultRepository.save_results(db, rows)
        await AuditRepository.add_event(db, AuditEvent(
            actor_type=AuditActorType.LOCAL_ACTOR, actor_id=actor.id,
            actor_role=actor.role, action="results.rollback_requested",
            entity_type="exam", entity_id=exam.id, reason=reason,
            metadata_json={
                "operation_id": str(operation_id),
                "batch_id": str(rows[0].rollback_original_batch_id),
                "result_ids": [str(row.id) for row in rows],
            },
        ))
        await db.commit()
        return operation_id

    @staticmethod
    async def _operation_rows(db: AsyncSession, operation_id: UUID) -> list[ExamResult]:
        return list((await db.execute(
            select(ExamResult).where(
                ExamResult.rollback_operation_id == operation_id
            ).order_by(ExamResult.id)
        )).scalars().all())

    @classmethod
    async def _payload(cls, db: AsyncSession, operation_id: UUID) -> tuple[UUID, list[UUID]]:
        rows = await cls._operation_rows(db, operation_id)
        if not rows or not all(row.rollback_original_batch_id == rows[0].rollback_original_batch_id for row in rows):
            raise ExamStateError("Rollback operation is missing its original batch")
        student_ids: list[UUID] = []
        for row in rows:
            candidate = await CandidateRepository.get_candidate_by_id(db, row.candidate_id)
            if candidate is None:
                raise ExamStateError("Rollback candidate no longer exists")
            student_ids.append(candidate.student_id)
        return rows[0].rollback_original_batch_id, student_ids

    @classmethod
    async def send(
        cls, db: AsyncSession, *, operation_id: UUID, session_id: UUID, reason: str,
    ) -> LocalRollbackResponse:
        # Retrying must supply the same original reason: Cloud checks the complete
        # original payload hash for the stable operation ID.
        batch_id, student_ids = await cls._payload(db, operation_id)
        token = await get_or_repair_weave_actor_access_token(db, session_id=session_id)
        identity = node_identity_store.load()
        try:
            cloud = await weave_result_gateway.request_rollback(
                operation_id=operation_id, batch_id=batch_id,
                student_ids=student_ids, reason=reason,
                server_credential=identity.server_credential, actor_access_token=token,
            )
        except WeaveIntegrationError as exc:
            # Cloud may have accepted the request before the connection failed.
            return LocalRollbackResponse(
                operation_id=operation_id, source_batch_id=batch_id,
                status="rollback_pending", results=[], error=str(exc),
            )
        return await cls.apply_cloud_status(db, operation_id=operation_id, cloud=cloud)

    @classmethod
    async def poll(cls, db: AsyncSession, *, operation_id: UUID) -> LocalRollbackResponse:
        batch_id, _ = await cls._payload(db, operation_id)
        identity = node_identity_store.load()
        cloud = await weave_result_gateway.rollback_status(
            operation_id=operation_id,
            server_credential=identity.server_credential,
        )
        return await cls.apply_cloud_status(db, operation_id=operation_id, cloud=cloud)

    @classmethod
    async def apply_cloud_status(
        cls, db: AsyncSession, *, operation_id: UUID, cloud: CloudRollbackResponse,
    ) -> LocalRollbackResponse:
        if cloud.operation_id != operation_id:
            raise ExamStateError("WEAVE returned a mismatched rollback operation")
        rows = await cls._operation_rows(db, operation_id)
        if not rows or cloud.source_batch_id != rows[0].rollback_original_batch_id:
            raise ExamStateError("WEAVE returned a mismatched rollback batch")
        if len(cloud.items) != len(rows):
            raise ExamStateError("WEAVE returned an incomplete rollback membership")
        by_student = {}
        for row in rows:
            candidate = await CandidateRepository.get_candidate_by_id(db, row.candidate_id)
            if candidate is None or candidate.student_id in by_student:
                raise ExamStateError("Unable to verify rollback student ownership")
            by_student[candidate.student_id] = row
        if set(by_student) != {item.student_id for item in cloud.items}:
            raise ExamStateError("WEAVE reported unexpected rollback students")
        completed = rejected = 0
        # Serialize Cloud responses with normal exam result mutations, using
        # the same lock order as voiding and the synchronization worker.
        exam = await ExamRepository.get_exam_by_id(db, rows[0].exam_id, lock=True)
        if exam is None:
            raise ExamStateError("Rollback examination no longer exists")
        await ExamExecutionRepository.get_control(db, exam.id, lock=True)
        for item in cloud.items:
            row = await ResultRepository.get_result_by_id(
                db, by_student[item.student_id].id, lock=True
            )
            if row.rollback_operation_id != operation_id:
                raise ExamStateError("Rollback operation has changed concurrently")
            if item.status == "completed":
                completed += 1
                if row.sync_status == ResultSyncStatus.ROLLBACK_PENDING:
                    row.sync_status = ResultSyncStatus.ROLLED_BACK
                    row.sync_batch_id = None
                    row.rolled_back_at = cloud.completed_at or datetime.now(UTC)
                    row.rollback_error = None
            elif item.status == "rejected":
                rejected += 1
                if row.sync_status == ResultSyncStatus.ROLLBACK_PENDING:
                    row.sync_status = ResultSyncStatus.SYNCED
                    row.synced_at = row.rollback_previous_synced_at or datetime.now(UTC)
                    row.rollback_error = item.error_detail or item.error_code
        await ResultRepository.save_results(db, rows)
        if completed or rejected:
            await AuditRepository.add_event(db, AuditEvent(
                actor_type=AuditActorType.SYSTEM, action="results.rollback_reconciled",
                entity_type="exam", entity_id=exam.id,
                metadata_json={
                    "operation_id": str(operation_id),
                    "completed_count": completed,
                    "rejected_count": rejected,
                },
            ))
        await db.commit()
        return LocalRollbackResponse(
            operation_id=operation_id, source_batch_id=cloud.source_batch_id,
            status=cloud.status, results=[row.id for row in rows],
            completed_count=completed, rejected_count=rejected,
        )

    @classmethod
    async def resync(cls, db: AsyncSession, *, actor: LocalActor, result_id: UUID) -> UUID:
        cls._admin(actor)
        reference = await ResultRepository.get_result_by_id(db, result_id)
        if reference is None:
            raise ExamStateError("Result does not exist")
        exam = await ExamRepository.get_exam_by_id(db, reference.exam_id, lock=True)
        if exam is None or exam.status != ExamStatus.CLOSED:
            raise ExamStateError("Only closed examinations can be republished")
        control = await ExamExecutionRepository.get_control(db, exam.id, lock=True)
        if control is None or control.result_disposition != ExamResultDisposition.APPROVED:
            raise ExamStateError("Examination results must be approved for resynchronization")
        row = await ResultRepository.get_result_by_id(db, result_id, lock=True)
        if row.sync_status != ResultSyncStatus.ROLLED_BACK or row.voided_at is not None:
            raise ExamStateError("Only non-voided, withdrawn results can be resynchronized")
        latest = await AttemptRepository.get_attempt_by_candidate_id(
            db, row.candidate_id, lock=True
        )
        if latest is not None and latest.id != row.attempt_id:
            raise ExamStateError("This score was superseded by a newer attempt")
        row.sync_status = ResultSyncStatus.PENDING
        row.sync_batch_id = None
        row.rollback_operation_id = None
        row.synced_at = None
        row.sync_error = None
        await ResultRepository.save_result(db, row)
        await AuditRepository.add_event(db, AuditEvent(
            actor_type=AuditActorType.LOCAL_ACTOR, actor_id=actor.id,
            actor_role=actor.role, action="result.resync_approved",
            entity_type="exam_result", entity_id=row.id,
            metadata_json={"previous_batch_id": str(row.rollback_original_batch_id)},
        ))
        await db.commit()
        return row.exam_id
