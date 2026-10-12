"""Persistence operations for examination candidates and candidate policy data.

Repositories only perform database reads/writes and row locking. Roster
eligibility, late-start policy, makeup policy, lifecycle decisions, and
transaction boundaries belong to services/workers.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.academics.models import Curriculum, CurriculumSubject
from app.domains.attempts.models import ExamAttempt
from app.domains.candidates.models import (
    CandidateLateStartAuthorization,
    CandidateMakeupAuthorization,
    CandidateStatus,
    ExamCandidate,
)
from app.domains.exams.models import Exam


class CandidateRepository:
    """Provide persistence operations for rosters and candidate policy state."""

    @staticmethod
    async def add_candidate(
        db: AsyncSession, candidate: ExamCandidate
    ) -> ExamCandidate:
        db.add(candidate)
        await db.flush()
        return candidate

    @staticmethod
    async def add_candidates(
        db: AsyncSession,
        candidates: Sequence[ExamCandidate],
    ) -> list[ExamCandidate]:
        rows = list(candidates)
        if rows:
            db.add_all(rows)
            await db.flush()
        return rows

    @staticmethod
    async def save_candidate(
        db: AsyncSession, candidate: ExamCandidate
    ) -> ExamCandidate:
        db.add(candidate)
        await db.flush()
        return candidate

    @staticmethod
    async def save_candidates(
        db: AsyncSession,
        candidates: Sequence[ExamCandidate],
    ) -> list[ExamCandidate]:
        rows = list(candidates)
        if rows:
            db.add_all(rows)
            await db.flush()
        return rows

    @staticmethod
    async def get_candidate_by_id(
        db: AsyncSession,
        candidate_id: UUID,
        *,
        lock: bool = False,
    ) -> ExamCandidate | None:
        query = select(ExamCandidate).where(ExamCandidate.id == candidate_id)
        if lock:
            query = query.with_for_update(of=ExamCandidate)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_candidate_by_enrollment(
        db: AsyncSession,
        exam_id: UUID,
        enrollment_id: UUID,
        *,
        lock: bool = False,
    ) -> ExamCandidate | None:
        query = select(ExamCandidate).where(
            ExamCandidate.exam_id == exam_id,
            ExamCandidate.enrollment_id == enrollment_id,
        )
        if lock:
            query = query.with_for_update(of=ExamCandidate)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_candidate_by_student_id(
        db: AsyncSession,
        exam_id: UUID,
        student_id: UUID,
        *,
        lock: bool = False,
    ) -> ExamCandidate | None:
        query = select(ExamCandidate).where(
            ExamCandidate.exam_id == exam_id,
            ExamCandidate.student_id == student_id,
        )
        if lock:
            query = query.with_for_update(of=ExamCandidate)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_candidate_by_admission_number(
        db: AsyncSession,
        exam_id: UUID,
        admission_number: str,
        *,
        lock: bool = False,
    ) -> ExamCandidate | None:
        query = select(ExamCandidate).where(
            ExamCandidate.exam_id == exam_id,
            ExamCandidate.admission_number == admission_number,
        )
        if lock:
            query = query.with_for_update(of=ExamCandidate)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_candidates_for_exam(
        db: AsyncSession,
        exam_id: UUID,
        *,
        status: CandidateStatus | None = None,
        class_id: UUID | None = None,
        roster_version: int | None = None,
        offset: int = 0,
        limit: int | None = None,
        lock: bool = False,
        skip_locked: bool = False,
    ) -> list[ExamCandidate]:
        query = select(ExamCandidate).where(ExamCandidate.exam_id == exam_id)
        if status is not None:
            query = query.where(ExamCandidate.status == status)
        if class_id is not None:
            query = query.where(ExamCandidate.class_id == class_id)
        if roster_version is not None:
            query = query.where(ExamCandidate.roster_version == roster_version)
        query = query.order_by(
            ExamCandidate.display_name.asc(),
            ExamCandidate.admission_number.asc(),
            ExamCandidate.id.asc(),
        ).offset(offset)
        if limit is not None:
            query = query.limit(limit)
        if lock:
            query = query.with_for_update(
                of=ExamCandidate,
                skip_locked=skip_locked,
            )
        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def list_candidates_not_seen_in_roster_version(
        db: AsyncSession,
        exam_id: UUID,
        roster_version: int,
        *,
        lock: bool = False,
        skip_locked: bool = False,
    ) -> list[ExamCandidate]:
        query = (
            select(ExamCandidate)
            .where(
                ExamCandidate.exam_id == exam_id,
                ExamCandidate.roster_version < roster_version,
            )
            .order_by(ExamCandidate.id.asc())
        )
        if lock:
            query = query.with_for_update(
                of=ExamCandidate,
                skip_locked=skip_locked,
            )
        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def count_candidates_for_exam(
        db: AsyncSession,
        exam_id: UUID,
        *,
        status: CandidateStatus | None = None,
        class_id: UUID | None = None,
    ) -> int:
        query = (
            select(func.count())
            .select_from(ExamCandidate)
            .where(ExamCandidate.exam_id == exam_id)
        )
        if status is not None:
            query = query.where(ExamCandidate.status == status)
        if class_id is not None:
            query = query.where(ExamCandidate.class_id == class_id)
        return int((await db.execute(query)).scalar_one() or 0)

    @staticmethod
    async def add_late_start_authorization(
        db: AsyncSession,
        authorization: CandidateLateStartAuthorization,
    ) -> CandidateLateStartAuthorization:
        db.add(authorization)
        await db.flush()
        return authorization

    @staticmethod
    async def get_late_start_authorization_by_id(
        db: AsyncSession,
        authorization_id: UUID,
        *,
        lock: bool = False,
    ) -> CandidateLateStartAuthorization | None:
        query = select(CandidateLateStartAuthorization).where(
            CandidateLateStartAuthorization.id == authorization_id
        )
        if lock:
            query = query.with_for_update(of=CandidateLateStartAuthorization)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_usable_late_start_authorization(
        db: AsyncSession,
        candidate_id: UUID,
        *,
        at: datetime,
        lock: bool = False,
    ) -> CandidateLateStartAuthorization | None:
        query = (
            select(CandidateLateStartAuthorization)
            .where(
                CandidateLateStartAuthorization.candidate_id == candidate_id,
                CandidateLateStartAuthorization.consumed_at.is_(None),
                CandidateLateStartAuthorization.revoked_at.is_(None),
                (
                    CandidateLateStartAuthorization.expires_at.is_(None)
                    | (CandidateLateStartAuthorization.expires_at >= at)
                ),
            )
            .order_by(
                CandidateLateStartAuthorization.granted_at.desc(),
                CandidateLateStartAuthorization.id.desc(),
            )
            .limit(1)
        )
        if lock:
            query = query.with_for_update(of=CandidateLateStartAuthorization)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_candidates_by_ids(
        db: AsyncSession,
        candidate_ids: Sequence[UUID],
    ) -> list[ExamCandidate]:
        """
        Load candidate snapshots in one query for result synchronization.
        """

        ids = list(dict.fromkeys(candidate_ids))

        if not ids:
            return []

        result = await db.execute(
            select(ExamCandidate)
            .where(ExamCandidate.id.in_(ids))
            .order_by(ExamCandidate.id.asc())
        )

        return list(result.scalars().all())

    @staticmethod
    async def list_late_start_authorizations(
        db: AsyncSession,
        candidate_id: UUID,
    ) -> list[CandidateLateStartAuthorization]:
        result = await db.execute(
            select(CandidateLateStartAuthorization)
            .where(CandidateLateStartAuthorization.candidate_id == candidate_id)
            .order_by(
                CandidateLateStartAuthorization.granted_at.asc(),
                CandidateLateStartAuthorization.id.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def save_late_start_authorization(
        db: AsyncSession,
        authorization: CandidateLateStartAuthorization,
    ) -> CandidateLateStartAuthorization:
        db.add(authorization)
        await db.flush()
        return authorization

    @staticmethod
    async def list_missed_candidates_for_exam(
        db: AsyncSession,
        exam_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ExamCandidate]:
        has_attempt = exists(
            select(ExamAttempt.id).where(ExamAttempt.candidate_id == ExamCandidate.id)
        )
        query = (
            select(ExamCandidate)
            .where(
                ExamCandidate.exam_id == exam_id,
                ExamCandidate.status == CandidateStatus.ELIGIBLE,
                ~has_attempt,
            )
            .order_by(
                ExamCandidate.display_name.asc(),
                ExamCandidate.admission_number.asc(),
                ExamCandidate.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def count_missed_candidates_for_exam(
        db: AsyncSession,
        exam_id: UUID,
    ) -> int:
        has_attempt = exists(
            select(ExamAttempt.id).where(ExamAttempt.candidate_id == ExamCandidate.id)
        )
        query = (
            select(func.count())
            .select_from(ExamCandidate)
            .where(
                ExamCandidate.exam_id == exam_id,
                ExamCandidate.status == CandidateStatus.ELIGIBLE,
                ~has_attempt,
            )
        )
        return int((await db.execute(query)).scalar_one() or 0)

    @staticmethod
    async def add_makeup_authorization(
        db: AsyncSession,
        authorization: CandidateMakeupAuthorization,
    ) -> CandidateMakeupAuthorization:
        db.add(authorization)
        await db.flush()
        return authorization

    @staticmethod
    async def save_makeup_authorization(
        db: AsyncSession,
        authorization: CandidateMakeupAuthorization,
    ) -> CandidateMakeupAuthorization:
        db.add(authorization)
        await db.flush()
        return authorization

    @staticmethod
    async def get_makeup_authorization_by_id(
        db: AsyncSession,
        authorization_id: UUID,
        *,
        lock: bool = False,
    ) -> CandidateMakeupAuthorization | None:
        query = select(CandidateMakeupAuthorization).where(
            CandidateMakeupAuthorization.id == authorization_id
        )
        if lock:
            query = query.with_for_update(of=CandidateMakeupAuthorization)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def get_active_makeup_authorization(
        db: AsyncSession,
        candidate_id: UUID,
        *,
        lock: bool = False,
    ) -> CandidateMakeupAuthorization | None:
        query = (
            select(CandidateMakeupAuthorization)
            .where(
                CandidateMakeupAuthorization.candidate_id == candidate_id,
                CandidateMakeupAuthorization.revoked_at.is_(None),
            )
            .order_by(
                CandidateMakeupAuthorization.approved_at.desc(),
                CandidateMakeupAuthorization.id.desc(),
            )
            .limit(1)
        )
        if lock:
            query = query.with_for_update(of=CandidateMakeupAuthorization)
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def list_makeup_authorizations(
        db: AsyncSession,
        candidate_id: UUID,
    ) -> list[CandidateMakeupAuthorization]:
        result = await db.execute(
            select(CandidateMakeupAuthorization)
            .where(CandidateMakeupAuthorization.candidate_id == candidate_id)
            .order_by(
                CandidateMakeupAuthorization.approved_at.asc(),
                CandidateMakeupAuthorization.id.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_active_makeup_authorizations_for_candidates(
        db: AsyncSession,
        candidate_ids: Sequence[UUID],
    ) -> list[CandidateMakeupAuthorization]:
        ids = list(dict.fromkeys(candidate_ids))
        if not ids:
            return []
        result = await db.execute(
            select(CandidateMakeupAuthorization)
            .where(
                CandidateMakeupAuthorization.candidate_id.in_(ids),
                CandidateMakeupAuthorization.revoked_at.is_(None),
            )
            .order_by(
                CandidateMakeupAuthorization.candidate_id.asc(),
                CandidateMakeupAuthorization.approved_at.asc(),
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_pending_makeups_for_student(
        db: AsyncSession,
        *,
        student_id: UUID,
        session_id: UUID,
        term_id: UUID,
    ) -> int:
        query = (
            select(func.count())
            .select_from(CandidateMakeupAuthorization)
            .join(
                ExamCandidate,
                ExamCandidate.id == CandidateMakeupAuthorization.candidate_id,
            )
            .join(Exam, Exam.id == ExamCandidate.exam_id)
            .where(
                ExamCandidate.student_id == student_id,
                CandidateMakeupAuthorization.revoked_at.is_(None),
                CandidateMakeupAuthorization.consumed_at.is_(None),
                Exam.session_id == session_id,
                Exam.term_id == term_id,
            )
        )
        return int((await db.execute(query)).scalar_one() or 0)

    @staticmethod
    async def list_pending_makeups_for_student(
        db: AsyncSession,
        *,
        student_id: UUID,
        session_id: UUID,
        term_id: UUID,
    ) -> list[
        tuple[
            CandidateMakeupAuthorization,
            ExamCandidate,
            Exam,
            UUID,
        ]
    ]:
        result = await db.execute(
            select(
                CandidateMakeupAuthorization,
                ExamCandidate,
                Exam,
                Curriculum.academic_level_id,
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
            .join(
                Curriculum,
                Curriculum.id == CurriculumSubject.curriculum_id,
            )
            .where(
                ExamCandidate.student_id == student_id,
                CandidateMakeupAuthorization.revoked_at.is_(None),
                CandidateMakeupAuthorization.consumed_at.is_(None),
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
