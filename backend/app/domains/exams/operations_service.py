"""Operational activation preflight and disruption-recovery workflows."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicAuthorizationError
from app.domains.auth.models import LocalActor
from app.domains.exams.exceptions import (
    ExamNotFound,
    ExamScheduleImpactError,
    ExamStateError,
)
from app.domains.exams.models import Exam, ExamRosterStatus, ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.exams.schedule_validation import validate_normal_entry_window
from app.domains.exams.timetable_service import (
    ActivationPreflight,
    ExamTimetableService,
)
from app.domains.runtime.models import RealtimeOutboxEvent
from app.domains.runtime.repository import RuntimeRepository


class ExamOperationsService:
    """Own non-authoring timetable decisions immediately around exam start."""

    @staticmethod
    def _require_admin(actor: LocalActor) -> None:
        if not actor.is_active:
            raise AcademicAuthorizationError("Active local actor is required")
        if actor.role != "admin":
            raise AcademicAuthorizationError("School administrator access required")

    @staticmethod
    async def _require_latest_revision(db: AsyncSession, exam: Exam) -> None:
        current = exam
        while True:
            child = await ExamRepository.get_latest_child_revision(
                db,
                current.id,
                lock=True,
            )
            if child is None:
                break
            current = child
        if current.id != exam.id:
            raise ExamStateError(
                "Only the latest examination revision can perform this operation"
            )

    @classmethod
    async def _require_activation_static_readiness(
        cls,
        db: AsyncSession,
        exam: Exam,
    ) -> None:
        if exam.status != ExamStatus.SEALED:
            raise ExamStateError("Only SEALED examinations can be activated")
        await cls._require_latest_revision(db, exam)
        if exam.roster_status != ExamRosterStatus.READY:
            raise ExamStateError("Candidate roster must be READY before activation")
        frozen_count = await ExamRepository.count_exam_questions(db, exam.id)
        if frozen_count != exam.question_count:
            raise ExamStateError("Frozen question count does not match exam setup")
        if exam.sealed_at is None or exam.component_maximum_score is None:
            raise ExamStateError("Exam is missing required sealed state")
        if exam.scheduled_start_at is None:
            raise ExamStateError("Examination is missing a scheduled start time")
        try:
            validate_normal_entry_window(
                exam.scheduled_start_at, exam.latest_normal_start_at
            )
        except ValueError as exc:
            raise ExamStateError(str(exc)) from exc

    @classmethod
    async def activation_preflight(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        proposed_activation_at: datetime | None = None,
        suggest_recovery_times: bool = False,
    ) -> ActivationPreflight:
        """Validate static readiness and calculate activation/timetable state.

        The timetable preflight acquires the transaction-scoped level advisory
        lock before we acquire exam row locks. Keeping that order consistent
        prevents activation/recovery deadlocks between parallel admin actions.
        """

        cls._require_admin(actor)
        preflight = await ExamTimetableService.activation_preflight(
            db,
            exam_id=exam_id,
            proposed_activation_at=proposed_activation_at,
            include_conflict_details=True,
            apply_recovery_buffer=False,
        )
        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id, lock=True)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        await cls._require_activation_static_readiness(db, exam)
        # Recovery headroom belongs to suggestions, not activation readiness.
        # Re-applying a rolling five-minute buffer to an already saved recovery
        # schedule would manufacture another clash on every UI check.
        if suggest_recovery_times and preflight.affected_exams:
            preflight = await ExamTimetableService.activation_preflight(
                db,
                exam_id=exam_id,
                proposed_activation_at=preflight.proposed_activation_at,
                include_conflict_details=True,
                apply_recovery_buffer=True,
            )
        return preflight

    @classmethod
    async def reschedule_activation_impact(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        source_exam_id: UUID,
        changes: dict[UUID, datetime],
        reason: str,
    ) -> tuple[list[Exam], ActivationPreflight]:
        """Atomically validate and persist an admin-selected recovery timetable.

        ``changes`` may use the backend suggestions or custom future times. The
        complete proposed timetable is simulated first; no exam is changed unless
        the resulting activation preflight is clean.
        """

        cls._require_admin(actor)
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("reason is required")
        if not changes:
            raise ValueError("At least one affected examination must be rescheduled")

        checked_at = datetime.now(UTC)

        # Acquire the level advisory lock through timetable preflight before any
        # source/downstream row lock. All recovery row locks below therefore use
        # one deterministic lock order: level advisory lock -> exam rows.
        current = await ExamTimetableService.activation_preflight(
            db,
            exam_id=source_exam_id,
            proposed_activation_at=checked_at,
            include_conflict_details=True,
            apply_recovery_buffer=True,
        )
        source = await ExamRepository.get_exam_by_id(
            db,
            exam_id=source_exam_id,
            lock=True,
        )
        if source is None:
            raise ExamNotFound("Examination does not exist")
        await cls._require_activation_static_readiness(db, source)

        if "too_early" in current.blockers:
            raise ExamStateError(
                "Examination cannot be activated before its scheduled start time"
            )
        if "candidate_scope_conflict" in current.blockers:
            raise ExamStateError(
                "Rescheduling cannot resolve candidates already assigned to another "
                "active, suspended, or finalizing examination"
            )
        if not current.affected_exams:
            raise ExamStateError(
                "Activation does not currently require downstream timetable rescheduling"
            )

        affected_ids = {impact.exam_id for impact in current.affected_exams}
        unexpected_ids = set(changes) - affected_ids
        if unexpected_ids:
            raise ExamStateError(
                "Reschedule changes may only target examinations in the current "
                "activation impact chain"
            )

        for value in changes.values():
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Rescheduled start times must include a timezone")
            if value.astimezone(UTC) <= checked_at:
                raise ValueError("Rescheduled start times must be in the future")

        change_ids = sorted(changes, key=str)
        rows = await db.execute(
            select(Exam)
            .where(Exam.id.in_(change_ids))
            .order_by(Exam.id.asc())
            .with_for_update(of=Exam)
        )
        exams = list(rows.scalars().all())
        exams_by_id = {exam.id: exam for exam in exams}
        if set(exams_by_id) != set(change_ids):
            raise ExamNotFound("One or more affected examinations no longer exist")

        for exam in exams:
            if exam.status != ExamStatus.SEALED:
                raise ExamStateError(
                    "Only SEALED downstream examinations can be operationally rescheduled"
                )
            await cls._require_latest_revision(db, exam)

        overrides = {
            exam_id: value.astimezone(UTC) for exam_id, value in changes.items()
        }
        # Validation uses the real current activation time, not a fresh rolling
        # suggestion buffer. This makes the backend suggestion stable while the
        # admin applies it and still validates custom times rigorously.
        proposed = await ExamTimetableService.activation_preflight(
            db,
            exam_id=source.id,
            proposed_activation_at=checked_at,
            schedule_overrides=overrides,
            include_conflict_details=True,
            apply_recovery_buffer=False,
        )
        if "candidate_scope_conflict" in proposed.blockers:
            raise ExamStateError(
                "Candidates became occupied by another operational examination; "
                "refresh activation preflight before rescheduling"
            )
        if proposed.affected_exams:
            raise ExamScheduleImpactError(
                "The proposed recovery timetable still contains conflicts",
                preflight=proposed,
            )

        now = datetime.now(UTC)
        try:
            for exam in exams:
                old_start = exam.scheduled_start_at
                old_latest = exam.latest_normal_start_at
                new_start = overrides[exam.id]
                grace = ExamTimetableService.entry_grace(exam)

                exam.scheduled_start_at = new_start
                exam.latest_normal_start_at = (
                    new_start + grace if old_latest is not None else None
                )
                await ExamRepository.save_exam(db, exam)
                await RuntimeRepository.add_outbox_event(
                    db,
                    RealtimeOutboxEvent(
                        aggregate_type="exam",
                        aggregate_id=exam.id,
                        event_type="exam.rescheduled",
                        payload={
                            "exam_id": str(exam.id),
                            "source_exam_id": str(source.id),
                            "actor_id": str(actor.id),
                            "reason": normalized_reason,
                            "old_scheduled_start_at": (
                                old_start.isoformat() if old_start is not None else None
                            ),
                            "new_scheduled_start_at": new_start.isoformat(),
                            "old_latest_normal_start_at": (
                                old_latest.isoformat()
                                if old_latest is not None
                                else None
                            ),
                            "new_latest_normal_start_at": (
                                exam.latest_normal_start_at.isoformat()
                                if exam.latest_normal_start_at is not None
                                else None
                            ),
                            "occurred_at": now.isoformat(),
                        },
                    ),
                )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "The recovery timetable could not be saved because examination "
                "state changed concurrently"
            ) from exc

        return exams, proposed
