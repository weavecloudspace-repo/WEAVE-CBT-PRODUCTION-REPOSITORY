"""Durable synchronization of locally calculated CBT results to Weave Cloud."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.academics.repository import AcademicRepository
from app.domains.candidates.repository import CandidateRepository
from app.domains.exams.exceptions import ExamNotFound
from app.domains.exams.execution_models import ExamResultDisposition
from app.domains.exams.execution_repository import ExamExecutionRepository
from app.domains.exams.models import ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.node.identity_store import NodeIdentityStore, node_identity_store
from app.domains.results.models import (
    RESULT_SYNC_ERROR_MAX_LENGTH,
    ExamResult,
    ResultSyncStatus,
)
from app.domains.results.repository import ResultRepository
from app.integrations.weave.exceptions import (
    WeaveContractError,
    WeaveIntegrationError,
    WeaveRequestRejectedError,
)
from app.integrations.weave.results import WeaveResultGateway, weave_result_gateway
from app.integrations.weave.schemas import (
    WeaveResultBulkRequest,
    WeaveResultBulkResponse,
    WeaveResultScore,
)

MAX_RESULT_SYNC_BATCH_SIZE = 1000
_UNCERTAIN_OR_RETRYABLE_HTTP_STATUSES = {408, 409, 425, 429}


class ResultSyncError(RuntimeError):
    """Raised when local result synchronization state is invalid."""


@dataclass(frozen=True, slots=True)
class _PreparedResultBatch:
    """Local representation of one exact durable Weave result batch."""

    payload: WeaveResultBulkRequest
    student_id_by_result_id: dict[UUID, UUID]


class ResultSyncService:
    """Synchronize approved local component scores to Weave Cloud.

    PostgreSQL owns synchronization state. A batch identity is committed before
    any network I/O so uncertain delivery can safely replay the exact same
    payload after timeout, worker crash, power loss or API restart.
    """

    def __init__(
        self,
        *,
        gateway: WeaveResultGateway = weave_result_gateway,
        identity_store: NodeIdentityStore = node_identity_store,
    ) -> None:
        self.gateway = gateway
        self.identity_store = identity_store

    async def sync_next_batch(
        self,
        db: AsyncSession,
        *,
        exam_id: UUID,
        limit: int = MAX_RESULT_SYNC_BATCH_SIZE,
    ) -> WeaveResultBulkResponse | None:
        """Synchronize at most one durable result batch for an examination."""

        if limit < 1 or limit > MAX_RESULT_SYNC_BATCH_SIZE:
            raise ValueError(
                f"Result sync batch limit must be between 1 and {MAX_RESULT_SYNC_BATCH_SIZE}."
            )

        # Load node credentials before claiming database work. Pairing problems
        # must not move otherwise untouched rows into SYNCING.
        identity = await asyncio.to_thread(self.identity_store.load)

        batch_id = await self._claim_or_resume_batch(
            db,
            exam_id=exam_id,
            limit=limit,
        )
        if batch_id is None:
            return None

        try:
            prepared = await self._prepare_batch(db, batch_id=batch_id)

            # Reads above open an implicit transaction. Never keep one open while
            # waiting on the internet.
            await db.rollback()

            response = await self.gateway.submit_results(
                payload=prepared.payload,
                server_credential=identity.server_credential,
            )
            self._validate_response(prepared=prepared, response=response)

        except WeaveRequestRejectedError as exc:
            await db.rollback()
            preserve_batch = self._rejection_requires_same_batch_retry(exc)
            await self._mark_batch_failed(
                db,
                batch_id=batch_id,
                error_message=self._integration_error_message(exc),
                preserve_batch=preserve_batch,
            )
            raise

        except WeaveIntegrationError as exc:
            await db.rollback()
            # Network failures and successful-but-invalid acknowledgements are
            # uncertain: Weave may have accepted the request. Preserve the exact
            # idempotency batch for any retry.
            await self._mark_batch_failed(
                db,
                batch_id=batch_id,
                error_message=self._integration_error_message(exc),
                preserve_batch=True,
            )
            raise

        except Exception:
            await db.rollback()
            await self._mark_batch_failed(
                db,
                batch_id=batch_id,
                error_message="Unexpected result synchronization failure.",
                preserve_batch=True,
            )
            raise

        await self._finalize_batch(db, prepared=prepared, response=response)
        return response

    async def _claim_or_resume_batch(
        self,
        db: AsyncSession,
        *,
        exam_id: UUID,
        limit: int,
    ) -> UUID | None:
        """Claim fresh approved work or resume one uncertain prior batch."""

        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            await db.rollback()
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.CLOSED:
            await db.rollback()
            return None

        # Defense in depth: callers, workers and maintenance may all make a
        # mistake. The synchronization service itself is the final boundary and
        # must never let PENDING_REVIEW or VOIDED results leave the CBT node.
        control = await ExamExecutionRepository.get_control(
            db,
            exam.id,
            lock=True,
        )
        if (
            control is None
            or control.result_disposition != ExamResultDisposition.APPROVED
        ):
            await db.rollback()
            return None

        retry_batch_id = await ResultRepository.get_retryable_sync_batch_id_for_exam(
            db,
            exam_id=exam.id,
        )
        if retry_batch_id is not None:
            rows = await ResultRepository.list_results_for_sync_batch(
                db,
                retry_batch_id,
                lock=True,
            )
            if not rows:
                await db.rollback()
                raise ResultSyncError(
                    "A retryable result batch exists without result rows."
                )
            if any(row.exam_id != exam.id for row in rows):
                await db.rollback()
                raise ResultSyncError(
                    "A result sync batch cannot contain multiple examinations."
                )
            if any(row.sync_status == ResultSyncStatus.SYNCED for row in rows):
                await db.rollback()
                raise ResultSyncError(
                    "A retryable result batch cannot contain already synchronized rows."
                )

            await self._mark_rows_syncing(
                db,
                rows=rows,
                batch_id=retry_batch_id,
            )
            await db.commit()
            return retry_batch_id

        rows = await ResultRepository.list_pending_results_for_exam_sync(
            db,
            exam_id=exam.id,
            limit=limit,
            lock=True,
        )
        if not rows:
            await db.rollback()
            return None

        # Weave validates enrollment and teacher ownership at the batch date.
        # Never combine original scores and later makeup dates in one payload.
        batch_date = rows[0].exam_date
        rows = [row for row in rows if row.exam_date == batch_date]
        batch_id = uuid4()
        await self._mark_rows_syncing(db, rows=rows, batch_id=batch_id)
        # Commit BEFORE network I/O: the exact logical batch now survives a
        # process or machine failure.
        await db.commit()
        return batch_id

    @staticmethod
    async def _mark_rows_syncing(
        db: AsyncSession,
        *,
        rows: list[ExamResult],
        batch_id: UUID,
    ) -> None:
        attempted_at = datetime.now(UTC)
        for row in rows:
            # Never regress externally confirmed success.
            if row.sync_status == ResultSyncStatus.SYNCED:
                continue
            row.sync_status = ResultSyncStatus.SYNCING
            row.sync_batch_id = batch_id
            row.sync_attempts += 1
            row.last_sync_attempt_at = attempted_at
            row.sync_error = None
            row.synced_at = None
        await ResultRepository.save_results(db, rows)

    async def _prepare_batch(
        self,
        db: AsyncSession,
        *,
        batch_id: UUID,
    ) -> _PreparedResultBatch:
        """Reconstruct one exact Weave request entirely from PostgreSQL."""

        rows = await ResultRepository.list_results_for_sync_batch(db, batch_id)
        if not rows:
            raise ResultSyncError("Result synchronization batch does not exist.")

        exam_id = rows[0].exam_id
        if any(row.exam_id != exam_id for row in rows):
            raise ResultSyncError(
                "A result synchronization batch contains multiple examinations."
            )
        if any(row.sync_status != ResultSyncStatus.SYNCING for row in rows):
            raise ResultSyncError(
                "Every result in an active synchronization batch must be SYNCING."
            )
        if any(row.voided_at is not None for row in rows):
            raise ResultSyncError("Voided results cannot be synchronized.")

        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id)
        if exam is None:
            raise ExamNotFound("Examination does not exist")

        # Re-check the academic publication decision immediately before payload
        # construction. This should normally be guaranteed by the claim lock,
        # but it also protects reconstructed/manual service calls.
        control = await ExamExecutionRepository.get_control(db, exam.id)
        if (
            control is None
            or control.result_disposition != ExamResultDisposition.APPROVED
        ):
            raise ResultSyncError(
                "Examination results are not approved for synchronization."
            )

        curriculum_subject = await AcademicRepository.get_curriculum_subject_by_id(
            db,
            exam.curriculum_subject_id,
        )
        if curriculum_subject is None:
            raise ResultSyncError(
                "The examination curriculum subject is unavailable locally."
            )
        curriculum = await AcademicRepository.get_curriculum_by_id(
            db,
            curriculum_subject.curriculum_id,
        )
        if curriculum is None:
            raise ResultSyncError("The examination curriculum is unavailable locally.")

        candidate_ids = [row.candidate_id for row in rows]
        candidates = await CandidateRepository.list_candidates_by_ids(db, candidate_ids)
        candidate_by_id = {candidate.id: candidate for candidate in candidates}
        if len(candidate_by_id) != len(set(candidate_ids)):
            raise ResultSyncError(
                "One or more result candidates are unavailable locally."
            )

        student_id_by_result_id: dict[UUID, UUID] = {}
        scores: list[WeaveResultScore] = []
        for row in rows:
            candidate = candidate_by_id[row.candidate_id]
            if candidate.exam_id != exam.id:
                raise ResultSyncError(
                    "A result candidate does not belong to its examination."
                )
            student_id_by_result_id[row.id] = candidate.student_id
            scores.append(
                WeaveResultScore(
                    student_id=candidate.student_id,
                    score=row.component_score,
                )
            )

        batch_dates = {row.exam_date for row in rows}
        if len(batch_dates) != 1:
            raise ResultSyncError(
                "A result batch cannot contain multiple assessment dates."
            )
        payload = WeaveResultBulkRequest(
            batch_id=batch_id,
            source_exam_id=exam.id,
            academic_session_id=exam.session_id,
            academic_term_id=exam.term_id,
            academic_level_id=curriculum.academic_level_id,
            curriculum_subject_id=exam.curriculum_subject_id,
            assessment_component_id=exam.assessment_component_id,
            exam_date=rows[0].exam_date,
            scores=scores,
        )
        return _PreparedResultBatch(
            payload=payload,
            student_id_by_result_id=student_id_by_result_id,
        )

    @staticmethod
    def _validate_response(
        *,
        prepared: _PreparedResultBatch,
        response: WeaveResultBulkResponse,
    ) -> None:
        payload = prepared.payload
        if response.batch_id != payload.batch_id:
            raise WeaveContractError("Weave acknowledged a different CBT result batch.")
        if response.source_exam_id != payload.source_exam_id:
            raise WeaveContractError("Weave acknowledged a different CBT examination.")
        if response.received != len(payload.scores):
            raise WeaveContractError(
                "Weave acknowledged an unexpected number of CBT results."
            )

        submitted_student_ids = {item.student_id for item in payload.scores}
        rejected_student_ids = [error.student_id for error in response.errors]
        if len(rejected_student_ids) != len(set(rejected_student_ids)):
            raise WeaveContractError(
                "Weave returned duplicate rejected student results."
            )
        if not set(rejected_student_ids).issubset(submitted_student_ids):
            raise WeaveContractError(
                "Weave rejected a student that was not present in the CBT batch."
            )

    async def _finalize_batch(
        self,
        db: AsyncSession,
        *,
        prepared: _PreparedResultBatch,
        response: WeaveResultBulkResponse,
    ) -> None:
        batch_id = prepared.payload.batch_id
        rows = await ResultRepository.list_results_for_sync_batch(
            db,
            batch_id,
            lock=True,
        )

        expected_result_ids = set(prepared.student_id_by_result_id)
        actual_result_ids = {row.id for row in rows}
        if actual_result_ids != expected_result_ids:
            await db.rollback()
            raise ResultSyncError(
                "Result batch membership changed during synchronization."
            )

        error_by_student_id = {error.student_id: error for error in response.errors}
        for row in rows:
            # A concurrent/stale worker must never demote a confirmed result.
            if row.sync_status == ResultSyncStatus.SYNCED:
                continue

            student_id = prepared.student_id_by_result_id[row.id]
            error = error_by_student_id.get(student_id)
            if error is None:
                row.sync_status = ResultSyncStatus.SYNCED
                row.synced_at = response.processed_at
                row.sync_error = None
                # Preserve batch ID as historical evidence of the accepted
                # Weave ingestion batch.
                continue

            # Weave definitely processed this batch and rejected this student's
            # score. Detach it from the completed idempotency batch. A later
            # operator retry will create a new batch after the underlying issue
            # is fixed.
            row.sync_status = ResultSyncStatus.FAILED
            row.sync_batch_id = None
            row.synced_at = None
            row.sync_error = self._bounded_error(f"{error.code}: {error.detail}")

        await ResultRepository.save_results(db, rows)
        await db.commit()

    async def _mark_batch_failed(
        self,
        db: AsyncSession,
        *,
        batch_id: UUID,
        error_message: str,
        preserve_batch: bool,
    ) -> None:
        rows = await ResultRepository.list_results_for_sync_batch(
            db,
            batch_id,
            lock=True,
        )
        if not rows:
            await db.rollback()
            return

        bounded_error = self._bounded_error(error_message)
        for row in rows:
            if row.sync_status == ResultSyncStatus.SYNCED:
                continue
            row.sync_status = ResultSyncStatus.FAILED
            row.sync_error = bounded_error
            row.synced_at = None
            if not preserve_batch:
                row.sync_batch_id = None
        await ResultRepository.save_results(db, rows)
        await db.commit()

    @staticmethod
    def _rejection_requires_same_batch_retry(exc: WeaveRequestRejectedError) -> bool:
        """Classify HTTP rejection by whether the exact batch must be retained.

        408/409/425/429 and 5xx can represent transient or uncertain processing,
        so retries must preserve the idempotency key and payload. Other 4xx are
        definitive request/auth/validation failures: detach the failed rows and
        require an explicit operator retry after the cause is fixed.
        """

        return (
            exc.status_code in _UNCERTAIN_OR_RETRYABLE_HTTP_STATUSES
            or exc.status_code >= 500
        )

    @staticmethod
    def _integration_error_message(exc: WeaveIntegrationError) -> str:
        return str(exc) or "Weave result synchronization failed."

    @staticmethod
    def _bounded_error(message: str) -> str:
        normalized = " ".join(message.split())
        if not normalized:
            normalized = "Result synchronization failed."
        return normalized[:RESULT_SYNC_ERROR_MAX_LENGTH]


result_sync_service = ResultSyncService()
