"""ARQ jobs for examination candidate-roster preparation and reconciliation."""

from __future__ import annotations

import logging
from uuid import UUID

from app.core.database import async_session_factory
from app.domains.candidates.exceptions import CandidateRosterError
from app.domains.candidates.service import CandidateService
from app.domains.exams.models import (
    ROSTER_ERROR_MAX_LENGTH,
    Exam,
    ExamRosterStatus,
    ExamStatus,
)
from app.domains.exams.repository import ExamRepository

logger = logging.getLogger(__name__)


async def _is_superseded_revision(db, exam: Exam) -> bool:
    """Return whether this roster belongs to an older exam revision."""

    return await ExamRepository.get_latest_child_revision(db, exam.id) is not None


async def _mark_roster_failed(
    *,
    exam_id: UUID,
    error_message: str,
) -> None:
    """Persist a recoverable roster failure in PostgreSQL."""

    async with async_session_factory() as db:
        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )

        if exam is None:
            return

        # Historical revisions are immutable. A stale queued job from an older
        # deployment must not even rewrite the old snapshot to FAILED.
        if await _is_superseded_revision(db, exam):
            return

        # Do not overwrite a roster another execution already completed.
        if exam.roster_status == ExamRosterStatus.READY:
            return

        # Roster preparation/reconciliation only belongs to sealed examinations.
        if exam.status != ExamStatus.SEALED:
            return

        exam.roster_status = ExamRosterStatus.FAILED
        exam.roster_error = error_message[:ROSTER_ERROR_MAX_LENGTH]

        await ExamRepository.save_exam(db, exam)
        await db.commit()


async def prepare_exam_roster(
    _ctx: dict,
    exam_id: str,
) -> None:
    """Prepare the candidate roster for one sealed examination."""

    try:
        parsed_exam_id = UUID(exam_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("prepare_exam_roster received an invalid exam ID") from exc

    try:
        async with async_session_factory() as db:
            # Lock before deciding whether duplicate delivery still needs work.
            exam = await ExamRepository.get_exam_by_id(
                db,
                exam_id=parsed_exam_id,
                lock=True,
            )

            if exam is None:
                logger.warning(
                    "Roster job ignored because exam %s no longer exists",
                    parsed_exam_id,
                )
                return

            if await _is_superseded_revision(db, exam):
                logger.info(
                    "Roster preparation ignored for historical exam revision %s",
                    parsed_exam_id,
                )
                return

            if exam.roster_status == ExamRosterStatus.READY:
                return

            # A queued job may outlive the exam state that created it.
            if exam.status != ExamStatus.SEALED:
                return

            if exam.roster_status not in {
                ExamRosterStatus.PENDING,
                ExamRosterStatus.FAILED,
            }:
                return

            await CandidateService.prepare_roster(
                db,
                exam_id=parsed_exam_id,
            )

    except CandidateRosterError as exc:
        await _mark_roster_failed(
            exam_id=parsed_exam_id,
            error_message=str(exc),
        )
        logger.warning(
            "Candidate roster preparation failed for exam %s: %s",
            parsed_exam_id,
            exc,
        )
        raise

    except Exception:
        await _mark_roster_failed(
            exam_id=parsed_exam_id,
            error_message="Candidate roster preparation failed unexpectedly",
        )
        logger.exception(
            "Unexpected candidate roster preparation failure for exam %s",
            parsed_exam_id,
        )
        raise


async def reconcile_exam_roster(
    _ctx: dict,
    exam_id: str,
) -> None:
    """Reconcile one stale sealed roster against current Weave enrollment truth.

    Delivery is intentionally idempotent. PostgreSQL owns the roster lifecycle;
    duplicate or delayed ARQ jobs simply exit when another execution has already
    completed the reconciliation, the exam has moved beyond SEALED, or the
    revision has been superseded and become historical evidence.
    """

    try:
        parsed_exam_id = UUID(exam_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("reconcile_exam_roster received an invalid exam ID") from exc

    try:
        async with async_session_factory() as db:
            exam = await ExamRepository.get_exam_by_id(
                db,
                exam_id=parsed_exam_id,
                lock=True,
            )

            if exam is None:
                logger.warning(
                    "Roster reconciliation ignored because exam %s no longer exists",
                    parsed_exam_id,
                )
                return

            if await _is_superseded_revision(db, exam):
                logger.info(
                    "Roster reconciliation ignored for historical exam revision %s",
                    parsed_exam_id,
                )
                return

            if exam.status != ExamStatus.SEALED:
                return

            if exam.roster_status == ExamRosterStatus.READY:
                return

            if exam.roster_status not in {
                ExamRosterStatus.STALE,
                ExamRosterStatus.FAILED,
            }:
                return

            await CandidateService.reconcile_roster(
                db,
                exam_id=parsed_exam_id,
            )

    except CandidateRosterError as exc:
        await _mark_roster_failed(
            exam_id=parsed_exam_id,
            error_message=str(exc),
        )
        logger.warning(
            "Candidate roster reconciliation failed for exam %s: %s",
            parsed_exam_id,
            exc,
        )
        raise

    except Exception:
        await _mark_roster_failed(
            exam_id=parsed_exam_id,
            error_message="Candidate roster reconciliation failed unexpectedly",
        )
        logger.exception(
            "Unexpected candidate roster reconciliation failure for exam %s",
            parsed_exam_id,
        )
        raise
