"""Lifecycle-aware candidate service facade."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.academics.repository import AcademicRepository
from app.domains.attempts.models import AttemptStatus, ExamAttempt
from app.domains.auth.models import LocalActor
from app.domains.candidates.exceptions import CandidateRosterError
from app.domains.candidates.models import (
    CandidateLateStartAuthorization,
    CandidateStatus,
    ExamCandidate,
)
from app.domains.candidates.query_repository import CandidateRosterQueryRepository
from app.domains.candidates.schemas import (
    CandidateAttemptStateFilter,
    CandidateAttemptSummaryResponse,
    CandidateBulkActionResponse,
    CandidateResponse,
    CandidateRosterClassResponse,
    CandidateRosterResponse,
)
from app.domains.candidates.service import CandidateService as _CandidateService
from app.domains.exams.exceptions import ExamNotFound
from app.domains.exams.models import Exam, ExamRosterStatus, ExamStatus
from app.domains.exams.repository import ExamRepository


class CandidateService(_CandidateService):
    """Candidate facade with lifecycle guards and admin roster read models."""

    @staticmethod
    def _ensure_exam_mutable(exam_status: ExamStatus) -> None:
        if exam_status in {
            ExamStatus.CLOSING,
            ExamStatus.CANCELLING,
            ExamStatus.CLOSED,
            ExamStatus.CANCELLED,
        }:
            raise ValueError(
                "Closing, cancelling, closed, or cancelled examinations are read-only"
            )

    @staticmethod
    async def _require_current_roster_revision(
        db: AsyncSession,
        exam: Exam,
    ) -> None:
        """Reject recovery after an examination revision has been superseded."""

        child_revision = await ExamRepository.get_latest_child_revision(db, exam.id)
        if child_revision is not None:
            raise CandidateRosterError(
                "This roster belongs to a superseded examination revision and is read-only"
            )

    @staticmethod
    def _effective_late_start_deadline(exam: Exam) -> datetime | None:
        """Return the finite normal-entry deadline used by candidate administration.

        Legacy rows may have latest_normal_start_at=NULL. Treat those as zero
        configured grace rather than unlimited entry so roster/admin behavior
        matches timetable planning and student-attempt enforcement.
        """

        deadline = exam.latest_normal_start_at or exam.scheduled_start_at
        if deadline is None:
            return None
        if (
            exam.scheduled_start_at is not None
            and exam.activated_at is not None
            and exam.activated_at > exam.scheduled_start_at
        ):
            deadline = deadline + (exam.activated_at - exam.scheduled_start_at)
        return deadline

    @classmethod
    def _late_start_required(cls, exam: Exam, *, at: datetime) -> bool:
        if exam.status != ExamStatus.ACTIVE:
            return False
        deadline = cls._effective_late_start_deadline(exam)
        return deadline is not None and at > deadline

    @staticmethod
    async def _require_candidate_not_started(
        db: AsyncSession,
        *,
        candidate_id: UUID,
    ) -> None:
        attempt = await db.scalar(
            select(ExamAttempt)
            .where(ExamAttempt.candidate_id == candidate_id)
            .with_for_update(of=ExamAttempt)
        )
        if attempt is not None:
            raise ValueError(
                "Candidate has already started this examination; use attempt controls instead"
            )

    @classmethod
    async def block_candidate(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        candidate_id: UUID,
        reason: str,
    ) -> CandidateResponse:
        # Lock the candidate before checking for an attempt. Attempt creation
        # takes the same candidate lock first, so start-vs-block cannot race into
        # BLOCKED + IN_PROGRESS state.
        await cls._get_candidate_and_exam(
            db,
            candidate_id=candidate_id,
            lock_candidate=True,
            lock_exam=True,
        )
        await cls._require_candidate_not_started(db, candidate_id=candidate_id)
        return await super().block_candidate(
            db,
            actor=actor,
            candidate_id=candidate_id,
            reason=reason,
        )

    @classmethod
    async def grant_late_start(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        candidate_id: UUID,
        reason: str,
        expires_at: datetime | None = None,
    ):
        candidate, exam = await cls._get_candidate_and_exam(
            db,
            candidate_id=candidate_id,
            lock_candidate=True,
            lock_exam=True,
        )
        await cls._require_candidate_not_started(db, candidate_id=candidate.id)

        now = datetime.now(UTC)
        if not cls._late_start_required(exam, at=now):
            raise ValueError(
                "Late-start authorization is only available after the normal entry deadline"
            )
        existing = await cls._usable_late_start_authorization(
            db,
            candidate_id=candidate.id,
            at=now,
            lock=True,
        )
        if existing is not None:
            raise ValueError("Candidate already has an active late-start authorization")

        return await super().grant_late_start(
            db,
            actor=actor,
            candidate_id=candidate_id,
            reason=reason,
            expires_at=expires_at,
        )

    @staticmethod
    async def _usable_late_start_authorization(
        db: AsyncSession,
        *,
        candidate_id: UUID,
        at: datetime,
        lock: bool = False,
    ) -> CandidateLateStartAuthorization | None:
        query = (
            select(CandidateLateStartAuthorization)
            .where(
                CandidateLateStartAuthorization.candidate_id == candidate_id,
                CandidateLateStartAuthorization.consumed_at.is_(None),
                CandidateLateStartAuthorization.revoked_at.is_(None),
                or_(
                    CandidateLateStartAuthorization.expires_at.is_(None),
                    CandidateLateStartAuthorization.expires_at >= at,
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

    @classmethod
    async def bulk_block_candidates(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        candidate_ids: list[UUID],
        reason: str,
    ) -> CandidateBulkActionResponse:
        cls._require_admin(actor)
        normalized_reason = cls._require_reason(reason)
        ids = list(dict.fromkeys(candidate_ids))
        if not ids:
            raise ValueError("Select at least one candidate")

        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        cls._ensure_exam_mutable(exam.status)

        candidates = list(
            (
                await db.execute(
                    select(ExamCandidate)
                    .where(
                        ExamCandidate.exam_id == exam.id,
                        ExamCandidate.id.in_(ids),
                    )
                    .order_by(ExamCandidate.id.asc())
                    .with_for_update(of=ExamCandidate)
                )
            )
            .scalars()
            .all()
        )
        if len(candidates) != len(ids):
            raise ValueError(
                "One or more selected candidates are not in this examination"
            )

        attempts = list(
            (
                await db.execute(
                    select(ExamAttempt).where(ExamAttempt.candidate_id.in_(ids))
                )
            )
            .scalars()
            .all()
        )
        if attempts:
            raise ValueError(
                "One or more selected candidates have already started; use attempt controls instead"
            )
        if any(
            candidate.status != CandidateStatus.ELIGIBLE for candidate in candidates
        ):
            raise ValueError("Only eligible candidates can be bulk blocked")

        for candidate in candidates:
            candidate.status = CandidateStatus.BLOCKED
            candidate.status_reason = normalized_reason
            db.add(candidate)

        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError("Selected candidates could not be blocked") from exc

        return CandidateBulkActionResponse(
            action="block",
            updated_count=len(candidates),
            candidate_ids=ids,
        )

    @classmethod
    async def bulk_grant_late_start(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        candidate_ids: list[UUID],
        reason: str,
        expires_at: datetime | None = None,
    ) -> CandidateBulkActionResponse:
        cls._require_admin(actor)
        normalized_reason = cls._require_reason(reason)
        ids = list(dict.fromkeys(candidate_ids))
        if not ids:
            raise ValueError("Select at least one candidate")

        now = datetime.now(UTC)
        normalized_expires_at = (
            cls._normalize_datetime(expires_at) if expires_at is not None else None
        )
        if normalized_expires_at is not None and normalized_expires_at < now:
            raise ValueError("Late-start authorization expiry cannot be in the past")

        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.ACTIVE:
            raise ValueError("Late start can only be granted for an active examination")
        if not cls._late_start_required(exam, at=now):
            raise ValueError(
                "Late-start authorization is only available after the normal entry deadline"
            )

        candidates = list(
            (
                await db.execute(
                    select(ExamCandidate)
                    .where(
                        ExamCandidate.exam_id == exam.id,
                        ExamCandidate.id.in_(ids),
                    )
                    .order_by(ExamCandidate.id.asc())
                    .with_for_update(of=ExamCandidate)
                )
            )
            .scalars()
            .all()
        )
        if len(candidates) != len(ids):
            raise ValueError(
                "One or more selected candidates are not in this examination"
            )
        if any(
            candidate.status != CandidateStatus.ELIGIBLE for candidate in candidates
        ):
            raise ValueError("Only eligible candidates can receive late start")

        attempts = list(
            (
                await db.execute(
                    select(ExamAttempt).where(ExamAttempt.candidate_id.in_(ids))
                )
            )
            .scalars()
            .all()
        )
        if attempts:
            raise ValueError(
                "One or more selected candidates have already started; late start is no longer applicable"
            )

        existing_authorizations = list(
            (
                await db.execute(
                    select(CandidateLateStartAuthorization)
                    .where(
                        CandidateLateStartAuthorization.candidate_id.in_(ids),
                        CandidateLateStartAuthorization.consumed_at.is_(None),
                        CandidateLateStartAuthorization.revoked_at.is_(None),
                        or_(
                            CandidateLateStartAuthorization.expires_at.is_(None),
                            CandidateLateStartAuthorization.expires_at >= now,
                        ),
                    )
                    .with_for_update(of=CandidateLateStartAuthorization)
                )
            )
            .scalars()
            .all()
        )
        if existing_authorizations:
            raise ValueError(
                "One or more selected candidates already have active late-start authorization"
            )

        authorizations = [
            CandidateLateStartAuthorization(
                candidate_id=candidate.id,
                granted_by_actor_id=actor.id,
                reason=normalized_reason,
                granted_at=now,
                expires_at=normalized_expires_at,
            )
            for candidate in candidates
        ]
        db.add_all(authorizations)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError("Late-start authorizations could not be granted") from exc

        return CandidateBulkActionResponse(
            action="late_start",
            updated_count=len(candidates),
            candidate_ids=ids,
        )

    @classmethod
    async def list_roster(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        status: CandidateStatus | None = None,
        class_id: UUID | None = None,
        search: str | None = None,
        attempt_state: CandidateAttemptStateFilter | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> CandidateRosterResponse:
        """Return a filterable roster read model without changing roster state."""

        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id)
        if exam is None:
            raise ExamNotFound("Examination does not exist")

        await cls._require_can_view_roster(
            db,
            actor=actor,
            exam_id=exam.id,
        )

        target_classes = await ExamRepository.list_target_classes_for_exam(db, exam.id)
        target_class_ids = {target.class_id for target in target_classes}
        if class_id is not None and class_id not in target_class_ids:
            raise ValueError("Class is not part of this examination")

        candidates = await CandidateRosterQueryRepository.list_candidates(
            db,
            exam_id=exam.id,
            status=status,
            class_id=class_id,
            search=search,
            attempt_state=attempt_state,
            offset=offset,
            limit=limit,
        )
        total = await CandidateRosterQueryRepository.count_candidates(
            db,
            exam_id=exam.id,
            status=status,
            class_id=class_id,
            search=search,
            attempt_state=attempt_state,
        )

        class_rows = []
        for target_class_id in target_class_ids:
            classroom = await AcademicRepository.get_class_by_id(
                db,
                class_id=target_class_id,
            )
            if classroom is not None:
                class_rows.append(classroom)
        class_rows.sort(
            key=lambda classroom: (classroom.display_name.casefold(), str(classroom.id))
        )
        class_name_by_id = {
            classroom.id: classroom.display_name for classroom in class_rows
        }

        candidate_ids = [candidate.id for candidate in candidates]
        attempts = (
            list(
                (
                    await db.execute(
                        select(ExamAttempt).where(
                            ExamAttempt.candidate_id.in_(candidate_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            if candidate_ids
            else []
        )
        attempt_by_candidate = {attempt.candidate_id: attempt for attempt in attempts}

        now = datetime.now(UTC)
        authorizations = (
            list(
                (
                    await db.execute(
                        select(CandidateLateStartAuthorization).where(
                            CandidateLateStartAuthorization.candidate_id.in_(
                                candidate_ids
                            ),
                            CandidateLateStartAuthorization.consumed_at.is_(None),
                            CandidateLateStartAuthorization.revoked_at.is_(None),
                            or_(
                                CandidateLateStartAuthorization.expires_at.is_(None),
                                CandidateLateStartAuthorization.expires_at >= now,
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if candidate_ids
            else []
        )
        authorized_candidate_ids = {
            authorization.candidate_id for authorization in authorizations
        }
        late_start_window_closed = cls._late_start_required(exam, at=now)

        candidate_rows = []
        for candidate in candidates:
            attempt = attempt_by_candidate.get(candidate.id)
            late_authorized = candidate.id in authorized_candidate_ids
            candidate_rows.append(
                CandidateResponse.model_validate(candidate).model_copy(
                    update={
                        "class_name": class_name_by_id.get(candidate.class_id),
                        "attempt": (
                            CandidateAttemptSummaryResponse.model_validate(attempt)
                            if attempt is not None
                            else None
                        ),
                        "late_start_authorized": late_authorized,
                        "late_start_required": bool(
                            late_start_window_closed
                            and candidate.status == CandidateStatus.ELIGIBLE
                            and attempt is None
                            and not late_authorized
                        ),
                    }
                )
            )

        attempt_count_rows = list(
            (
                await db.execute(
                    select(ExamAttempt.status, func.count())
                    .join(
                        ExamCandidate,
                        ExamCandidate.id == ExamAttempt.candidate_id,
                    )
                    .where(ExamCandidate.exam_id == exam.id)
                    .group_by(ExamAttempt.status)
                )
            )
            .tuples()
            .all()
        )
        attempt_counts = {
            status_value: int(count) for status_value, count in attempt_count_rows
        }

        has_attempt = exists(
            select(ExamAttempt.id).where(ExamAttempt.candidate_id == ExamCandidate.id)
        )
        eligible_not_started_count = int(
            await db.scalar(
                select(func.count())
                .select_from(ExamCandidate)
                .where(
                    ExamCandidate.exam_id == exam.id,
                    ExamCandidate.status == CandidateStatus.ELIGIBLE,
                    ~has_attempt,
                )
            )
            or 0
        )

        late_start_required_count = 0
        if late_start_window_closed:
            has_usable_authorization = exists(
                select(CandidateLateStartAuthorization.id).where(
                    CandidateLateStartAuthorization.candidate_id == ExamCandidate.id,
                    CandidateLateStartAuthorization.consumed_at.is_(None),
                    CandidateLateStartAuthorization.revoked_at.is_(None),
                    or_(
                        CandidateLateStartAuthorization.expires_at.is_(None),
                        CandidateLateStartAuthorization.expires_at >= now,
                    ),
                )
            )
            late_start_required_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(ExamCandidate)
                    .where(
                        ExamCandidate.exam_id == exam.id,
                        ExamCandidate.status == CandidateStatus.ELIGIBLE,
                        ~has_attempt,
                        ~has_usable_authorization,
                    )
                )
                or 0
            )

        return CandidateRosterResponse(
            exam_id=exam.id,
            roster_status=exam.roster_status,
            roster_version=exam.roster_version,
            roster_candidate_count=exam.roster_candidate_count,
            eligible_not_started_count=eligible_not_started_count,
            in_progress_count=attempt_counts.get(AttemptStatus.IN_PROGRESS, 0),
            interrupted_count=attempt_counts.get(AttemptStatus.INTERRUPTED, 0),
            submitted_count=attempt_counts.get(AttemptStatus.SUBMITTED, 0),
            terminated_count=attempt_counts.get(AttemptStatus.TERMINATED, 0),
            late_start_required_count=late_start_required_count,
            offset=offset,
            limit=limit,
            total=total,
            classes=[
                CandidateRosterClassResponse(
                    id=classroom.id,
                    display_name=classroom.display_name,
                )
                for classroom in class_rows
            ],
            candidates=candidate_rows,
        )

    @classmethod
    async def retry_failed_roster(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
    ) -> tuple[Exam, str]:
        """Return a failed sealed roster to a durable recoverable state.

        PostgreSQL owns the recovery request. Queue delivery is deliberately
        handled by the router after this transaction commits so Redis failure
        cannot lose the operator's retry request; maintenance can reconstruct
        PENDING/STale work later from the database.
        """

        cls._require_admin(actor)

        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")

        await cls._require_current_roster_revision(db, exam)
        if exam.status != ExamStatus.SEALED:
            raise CandidateRosterError(
                "Failed roster recovery is only available for a SEALED examination"
            )

        if exam.roster_status != ExamRosterStatus.FAILED:
            raise CandidateRosterError(
                "Roster recovery can only be retried from FAILED state"
            )

        initial_preparation = exam.roster_version == 0
        recovery_mode = "prepare" if initial_preparation else "reconcile"
        exam.roster_status = (
            ExamRosterStatus.PENDING if initial_preparation else ExamRosterStatus.STALE
        )
        exam.roster_error = None

        await ExamRepository.save_exam(db, exam)
        await db.commit()
        return exam, recovery_mode
