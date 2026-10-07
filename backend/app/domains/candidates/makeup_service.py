"""Resolve the deterministic makeup queue for one student."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.academics.models import Curriculum, CurriculumSubject
from app.domains.attempts.models import AttemptStatus, ExamAttempt
from app.domains.candidates.models import (
    CandidateMakeupAuthorization,
    CandidateStatus,
    ExamCandidate,
)
from app.domains.exams.models import Exam
from app.domains.exams.repository import ExamRepository


@dataclass(frozen=True)
class MakeupQueueResolution:
    available: bool
    next_candidate_id: UUID | None = None
    next_exam_id: UUID | None = None
    authorization_id: UUID | None = None
    academic_level_id: UUID | None = None
    pending_count: int = 0
    blocked_reason: str | None = None
    resume_existing_attempt: bool = False


class CandidateMakeupService:
    """Determine which approved missed paper a student may write next."""

    @staticmethod
    async def _queue_rows(
        db: AsyncSession,
        *,
        student_id: UUID,
        session_id: UUID,
        term_id: UUID,
    ):
        result = await db.execute(
            select(
                CandidateMakeupAuthorization,
                ExamCandidate,
                Exam,
                Curriculum.academic_level_id,
                ExamAttempt,
            )
            .join(
                ExamCandidate,
                ExamCandidate.id == CandidateMakeupAuthorization.candidate_id,
            )
            .join(Exam, Exam.id == ExamCandidate.exam_id)
            .join(
                CurriculumSubject,
                CurriculumSubject.id == Exam.curriculum_subject_id,
            )
            .join(Curriculum, Curriculum.id == CurriculumSubject.curriculum_id)
            .outerjoin(ExamAttempt, ExamAttempt.candidate_id == ExamCandidate.id)
            .where(
                ExamCandidate.student_id == student_id,
                ExamCandidate.status == CandidateStatus.ELIGIBLE,
                CandidateMakeupAuthorization.revoked_at.is_(None),
                Exam.session_id == session_id,
                Exam.term_id == term_id,
            )
            .order_by(
                Exam.scheduled_start_at.asc().nulls_last(),
                Exam.id.asc(),
                ExamCandidate.id.asc(),
            )
        )
        return list(result.tuples().all())

    @classmethod
    async def resolve_queue(
        cls,
        db: AsyncSession,
        *,
        student_id: UUID,
        session_id: UUID,
        term_id: UUID,
    ) -> MakeupQueueResolution:
        rows = await cls._queue_rows(
            db,
            student_id=student_id,
            session_id=session_id,
            term_id=term_id,
        )
        if not rows:
            return MakeupQueueResolution(
                available=False,
                blocked_reason="Student has no approved makeup examinations",
            )

        level_ids = {row[3] for row in rows}
        if len(level_ids) != 1:
            return MakeupQueueResolution(
                available=False,
                pending_count=len(rows),
                blocked_reason=(
                    "Approved makeup examinations span multiple academic levels; "
                    "administrator review is required"
                ),
            )
        level_id = next(iter(level_ids))

        unfinished = await ExamRepository.has_unfinished_scheduled_exam_for_level(
            db,
            session_id=session_id,
            term_id=term_id,
            level_id=level_id,
        )
        if unfinished:
            return MakeupQueueResolution(
                available=False,
                academic_level_id=level_id,
                pending_count=len(rows),
                blocked_reason=(
                    "Makeup examinations remain locked until the academic level's "
                    "normal scheduled examination cycle is complete"
                ),
            )

        pending_count = sum(1 for row in rows if row[4] is None or row[4].status != AttemptStatus.SUBMITTED)
        for authorization, candidate, exam, _level_id, attempt in rows:
            if attempt is not None and attempt.status == AttemptStatus.SUBMITTED:
                continue

            if attempt is not None:
                if attempt.status in {
                    AttemptStatus.IN_PROGRESS,
                    AttemptStatus.INTERRUPTED,
                }:
                    return MakeupQueueResolution(
                        available=True,
                        next_candidate_id=candidate.id,
                        next_exam_id=exam.id,
                        authorization_id=authorization.id,
                        academic_level_id=level_id,
                        pending_count=pending_count,
                        resume_existing_attempt=True,
                    )
                if attempt.status == AttemptStatus.TERMINATED:
                    return MakeupQueueResolution(
                        available=False,
                        next_candidate_id=candidate.id,
                        next_exam_id=exam.id,
                        authorization_id=authorization.id,
                        academic_level_id=level_id,
                        pending_count=pending_count,
                        blocked_reason=(
                            "The next makeup attempt was terminated; administrator "
                            "review is required before the queue can continue"
                        ),
                    )

            if authorization.consumed_at is not None:
                return MakeupQueueResolution(
                    available=False,
                    next_candidate_id=candidate.id,
                    next_exam_id=exam.id,
                    authorization_id=authorization.id,
                    academic_level_id=level_id,
                    pending_count=pending_count,
                    blocked_reason=(
                        "Makeup authorization was consumed without a recoverable attempt; "
                        "administrator review is required"
                    ),
                )

            return MakeupQueueResolution(
                available=True,
                next_candidate_id=candidate.id,
                next_exam_id=exam.id,
                authorization_id=authorization.id,
                academic_level_id=level_id,
                pending_count=pending_count,
            )

        return MakeupQueueResolution(
            available=False,
            academic_level_id=level_id,
            pending_count=0,
            blocked_reason="Student has completed all approved makeup examinations",
        )
