"""Exam timetable integrity helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domains.academics.electives import ElectiveEligibilityService
from app.domains.academics.eligibility import AcademicEligibilityService
from app.domains.academics.models import Curriculum, CurriculumSubject
from app.domains.candidates.models import CandidateStatus, ExamCandidate
from app.domains.exams.exceptions import (
    ExamNotFound,
    ExamScheduleImpactError,
    ExamStateError,
)
from app.domains.exams.models import (
    Exam,
    ExamRosterStatus,
    ExamStatus,
    ExamSuspension,
)
from app.domains.exams.repository import ExamRepository

OPERATIONAL_EXAM_STATUSES = (
    ExamStatus.ACTIVE,
    ExamStatus.SUSPENDED,
    ExamStatus.CLOSING,
    ExamStatus.CANCELLING,
)

# A few seconds of API/UI latency must not force a school to reschedule an
# entire back-to-back timetable. Runtime candidate-overlap protection still
# prevents the next sitting from becoming active while candidates remain busy.
ACTIVATION_IMPACT_TOLERANCE = timedelta(minutes=1)

# Suggested recovery times reserve a short operational window for the admin to
# review/apply the proposed timetable and then start the delayed exam. Without
# this headroom, a suggestion calculated at 11:40:00 could become invalid at
# 11:40:10 simply because the projected finish moved by ten seconds.
ACTIVATION_RECOVERY_BUFFER = timedelta(minutes=5)

# The current CBT deployment calendar is Nigerian school-local time (WAT,
# UTC+01:00). Keep the business-date check independent of the host/container
# timezone, because the packaged Docker runtime commonly runs in UTC.
SCHOOL_CALENDAR_TIMEZONE = timezone(timedelta(hours=1), "WAT")


@dataclass(frozen=True)
class TimetableImpact:
    exam_id: UUID
    title: str
    original_start_at: datetime
    proposed_start_at: datetime
    proposed_end_at: datetime


@dataclass(frozen=True)
class ActivationScheduleImpact:
    exam_id: UUID
    title: str
    status: ExamStatus
    scheduled_start_at: datetime | None
    scheduled_end_at: datetime | None
    suggested_start_at: datetime | None
    suggested_end_at: datetime | None
    delay_seconds: int | None
    blocked_by_exam_ids: tuple[UUID, ...]
    reason: str


@dataclass(frozen=True)
class ActivationPreflight:
    exam_id: UUID
    checked_at: datetime
    scheduled_start_at: datetime | None
    proposed_activation_at: datetime
    projected_end_at: datetime | None
    delay_seconds: int
    can_activate: bool
    blockers: tuple[str, ...]
    conflicting_operational_exam_ids: tuple[UUID, ...]
    affected_exams: tuple[ActivationScheduleImpact, ...]
    suggestion_valid_until_at: datetime | None = None


@dataclass(frozen=True)
class _ScopeWindow:
    exam_id: UUID
    title: str
    # Historically this field held class IDs. It now carries student audience
    # IDs for activation/recovery calculations so parallel elective sittings are
    # judged by actual candidate intersection. The name is retained to keep the
    # internal cascade structure stable.
    class_ids: frozenset[UUID]
    start_at: datetime
    end_at: datetime | None


@dataclass(frozen=True)
class _PlannedNode:
    exam_id: UUID
    title: str
    status: ExamStatus
    class_ids: frozenset[UUID]
    scheduled_start_at: datetime | None
    window_duration: timedelta


class ExamTimetableService:
    @staticmethod
    def intervals_overlap(
        a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
    ) -> bool:
        return a_start < b_end and b_start < a_end

    @staticmethod
    def planned_end_at(
        *,
        scheduled_start_at: datetime,
        latest_normal_start_at: datetime | None,
        duration_minutes: int,
    ) -> datetime:
        """Return the latest normal finish implied by the authoring schedule."""

        candidate_start = latest_normal_start_at or scheduled_start_at
        return candidate_start + timedelta(minutes=duration_minutes)

    @staticmethod
    def entry_grace(exam: Exam) -> timedelta:
        """Return the configured normal-entry grace window for one exam."""

        if exam.scheduled_start_at is None or exam.latest_normal_start_at is None:
            return timedelta(0)
        grace = exam.latest_normal_start_at - exam.scheduled_start_at
        return max(grace, timedelta(0))

    @classmethod
    def projected_end_for_actual_start(
        cls,
        exam: Exam,
        *,
        actual_start_at: datetime,
        completed_pause: timedelta = timedelta(0),
    ) -> datetime:
        """Project the last normal finish from a real operational start.

        The calculation preserves the configured late-entry window and adds any
        completed suspension time. It deliberately does not guess an end while
        an exam is currently suspended/finalizing.
        """

        return (
            actual_start_at
            + cls.entry_grace(exam)
            + timedelta(minutes=exam.duration_minutes)
            + completed_pause
        )

    @staticmethod
    async def level_id(db: AsyncSession, curriculum_subject_id: UUID) -> UUID:
        value = await db.scalar(
            select(Curriculum.academic_level_id)
            .join(CurriculumSubject, CurriculumSubject.curriculum_id == Curriculum.id)
            .where(CurriculumSubject.id == curriculum_subject_id)
        )
        if value is None:
            raise ValueError("Curriculum subject does not resolve to an academic level")
        return value

    @staticmethod
    async def acquire_level_lock(
        db: AsyncSession, *, session_id: UUID, term_id: UUID, level_id: UUID
    ) -> None:
        scope = f"exam-timetable:{session_id}:{term_id}:{level_id}"
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": scope},
        )

    @staticmethod
    async def acquire_operational_candidate_lock(db: AsyncSession) -> None:
        """Serialize mutations that can create cross-exam candidate occupancy.

        Level locks protect timetable races inside a normal academic scope. This
        short global lock closes the pathological cross-level race too, so even
        inconsistent projection data cannot make one student operationally
        eligible in two exams at the same instant.
        """

        scope = "exam-operational-candidate-scope"
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": scope},
        )

    @classmethod
    async def list_leaf_exams(
        cls,
        db: AsyncSession,
        *,
        session_id: UUID,
        term_id: UUID,
        level_id: UUID,
        statuses: tuple[ExamStatus, ...],
        exclude_exam_id: UUID | None = None,
    ) -> list[Exam]:
        child = aliased(Exam)
        has_child = (
            select(child.id).where(child.revision_of_exam_id == Exam.id).exists()
        )
        query = (
            select(Exam)
            .join(CurriculumSubject, CurriculumSubject.id == Exam.curriculum_subject_id)
            .join(Curriculum, Curriculum.id == CurriculumSubject.curriculum_id)
            .where(
                Exam.session_id == session_id,
                Exam.term_id == term_id,
                Curriculum.academic_level_id == level_id,
                Exam.status.in_(statuses),
                ~has_child,
            )
        )
        if exclude_exam_id is not None:
            query = query.where(Exam.id != exclude_exam_id)
        result = await db.execute(
            query.order_by(Exam.scheduled_start_at.asc().nulls_last(), Exam.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def _derived_delivery_class_ids(
        db: AsyncSession,
        *,
        curriculum_subject_id: UUID,
        term_id: UUID,
    ) -> set[UUID]:
        """Resolve the current academic delivery scope before an exam is sealed."""

        classes = await AcademicEligibilityService.list_eligible_classes(
            db,
            curriculum_subject_id=curriculum_subject_id,
            academic_term_id=term_id,
        )
        return {classroom.id for classroom in classes}

    @classmethod
    async def _exam_delivery_class_ids(
        cls,
        db: AsyncSession,
        *,
        exam: Exam,
    ) -> set[UUID]:
        """Return mutable academic scope pre-seal or frozen scope after sealing."""

        if exam.status in {ExamStatus.DRAFT, ExamStatus.SUBMITTED}:
            return await cls._derived_delivery_class_ids(
                db,
                curriculum_subject_id=exam.curriculum_subject_id,
                term_id=exam.term_id,
            )

        targets = await ExamRepository.list_target_classes_for_exam(db, exam.id)
        return {target.class_id for target in targets}

    @staticmethod
    def _uses_materialized_candidate_audience(exam: Exam) -> bool:
        """Return whether frozen candidate rows are authoritative for conflicts.

        Operational exams always use their frozen roster. A sealed exam may use
        candidate rows only while its roster is READY. Selection/enrollment sync
        moves READY rosters to STALE, at which point current Weave projections
        become the source for pre-activation conflict checks until reconciliation.

        The READY fallback keeps historical unit-test fixtures that predate the
        explicit roster-status field equivalent to the old sealed-roster behavior;
        real persisted Exam rows always carry a roster status.
        """

        if exam.status in OPERATIONAL_EXAM_STATUSES:
            return True
        if exam.status != ExamStatus.SEALED:
            return False
        roster_status = getattr(exam, "roster_status", ExamRosterStatus.READY)
        return roster_status == ExamRosterStatus.READY

    @classmethod
    async def _projected_audience_ids(
        cls,
        db: AsyncSession,
        *,
        exam: Exam,
    ) -> set[UUID]:
        """Return the authoritative audience for one timetable conflict check."""

        if cls._uses_materialized_candidate_audience(exam):
            rows = await db.execute(
                select(ExamCandidate.student_id).where(
                    ExamCandidate.exam_id == exam.id,
                    ExamCandidate.status == CandidateStatus.ELIGIBLE,
                )
            )
            return set(rows.scalars().all())

        class_ids = await cls._exam_delivery_class_ids(db, exam=exam)
        return await ElectiveEligibilityService.projected_student_ids_for_classes(
            db,
            curriculum_subject_id=exam.curriculum_subject_id,
            class_ids=tuple(class_ids),
            academic_session_id=exam.session_id,
        )

    @classmethod
    async def _scope_map_for_exams(
        cls,
        db: AsyncSession,
        exams: list[Exam],
    ) -> dict[UUID, frozenset[UUID]]:
        """Resolve current/frozen student audiences for activation and recovery.

        READY sealed and operational exams are frozen candidate evidence. Draft,
        submitted, and non-READY sealed exams are still pre-execution and are
        resolved from the current Weave projection. This makes an elective choice
        change visible immediately to activation preflight while preserving
        immutable execution evidence once an exam has begun.
        """

        result: dict[UUID, frozenset[UUID]] = {}
        materialized = [
            exam for exam in exams if cls._uses_materialized_candidate_audience(exam)
        ]
        if materialized:
            exam_ids = [exam.id for exam in materialized]
            rows = await db.execute(
                select(ExamCandidate.exam_id, ExamCandidate.student_id).where(
                    ExamCandidate.exam_id.in_(exam_ids),
                    ExamCandidate.status == CandidateStatus.ELIGIBLE,
                )
            )
            mutable: dict[UUID, set[UUID]] = {exam_id: set() for exam_id in exam_ids}
            for exam_id, student_id in rows.all():
                mutable[exam_id].add(student_id)
            result.update(
                {
                    exam_id: frozenset(student_ids)
                    for exam_id, student_ids in mutable.items()
                }
            )

        projected_cache: dict[
            tuple[UUID, UUID, UUID, tuple[UUID, ...]], frozenset[UUID]
        ] = {}
        for exam in exams:
            if cls._uses_materialized_candidate_audience(exam):
                continue
            class_ids = await cls._exam_delivery_class_ids(db, exam=exam)
            class_scope = tuple(sorted(class_ids, key=str))
            key = (
                exam.curriculum_subject_id,
                exam.term_id,
                exam.session_id,
                class_scope,
            )
            if key not in projected_cache:
                student_ids = (
                    await ElectiveEligibilityService.projected_student_ids_for_classes(
                        db,
                        curriculum_subject_id=exam.curriculum_subject_id,
                        class_ids=class_scope,
                        academic_session_id=exam.session_id,
                    )
                )
                projected_cache[key] = frozenset(student_ids)
            result[exam.id] = projected_cache[key]

        return result

    @staticmethod
    async def _suspension_state(
        db: AsyncSession,
        exam_ids: list[UUID],
    ) -> tuple[dict[UUID, timedelta], set[UUID]]:
        """Return completed pause duration and exams with an open suspension."""

        if not exam_ids:
            return {}, set()
        rows = await db.execute(
            select(
                ExamSuspension.exam_id,
                ExamSuspension.suspended_at,
                ExamSuspension.resumed_at,
            ).where(ExamSuspension.exam_id.in_(exam_ids))
        )
        completed: dict[UUID, timedelta] = {
            exam_id: timedelta(0) for exam_id in exam_ids
        }
        open_ids: set[UUID] = set()
        for exam_id, suspended_at, resumed_at in rows.all():
            if resumed_at is None:
                open_ids.add(exam_id)
                continue
            if resumed_at > suspended_at:
                completed[exam_id] += resumed_at - suspended_at
        return completed, open_ids

    @classmethod
    async def require_planned_slot_available(
        cls,
        db: AsyncSession,
        *,
        session_id: UUID,
        term_id: UUID,
        curriculum_subject_id: UUID,
        scheduled_start_at: datetime | None,
        latest_normal_start_at: datetime | None = None,
        duration_minutes: int,
        exclude_exam_id: UUID | None = None,
    ) -> None:
        if scheduled_start_at is None:
            return
        level_id = await cls.level_id(db, curriculum_subject_id)
        await cls.acquire_level_lock(
            db, session_id=session_id, term_id=term_id, level_id=level_id
        )
        proposed_end = cls.planned_end_at(
            scheduled_start_at=scheduled_start_at,
            latest_normal_start_at=latest_normal_start_at,
            duration_minutes=duration_minutes,
        )
        proposed_class_ids = await cls._derived_delivery_class_ids(
            db,
            curriculum_subject_id=curriculum_subject_id,
            term_id=term_id,
        )
        proposed_is_grouped_elective = (
            await ElectiveEligibilityService.subject_requires_selection(
                db,
                curriculum_subject_id,
            )
        )
        proposed_student_ids: set[UUID] | None = None
        rows = await cls.list_leaf_exams(
            db,
            session_id=session_id,
            term_id=term_id,
            level_id=level_id,
            exclude_exam_id=exclude_exam_id,
            statuses=(
                ExamStatus.DRAFT,
                ExamStatus.SUBMITTED,
                ExamStatus.SEALED,
                ExamStatus.ACTIVE,
                ExamStatus.SUSPENDED,
                ExamStatus.CLOSING,
                ExamStatus.CANCELLING,
            ),
        )
        for row in sorted(
            rows,
            key=lambda exam: (
                exam.scheduled_start_at or datetime.max.replace(tzinfo=UTC),
                str(exam.id),
            ),
        ):
            if row.scheduled_start_at is None:
                continue
            row_end = cls.planned_end_at(
                scheduled_start_at=row.scheduled_start_at,
                latest_normal_start_at=row.latest_normal_start_at,
                duration_minutes=row.duration_minutes,
            )
            if not cls.intervals_overlap(
                scheduled_start_at, proposed_end, row.scheduled_start_at, row_end
            ):
                continue

            row_class_ids = await cls._exam_delivery_class_ids(db, exam=row)
            if proposed_class_ids.isdisjoint(row_class_ids):
                continue

            # Preserve the existing conservative class-overlap rule for normal
            # subjects. The only exception is two grouped elective exams whose
            # authoritative student audiences do not intersect.
            row_is_grouped_elective = (
                await ElectiveEligibilityService.subject_requires_selection(
                    db,
                    row.curriculum_subject_id,
                )
            )
            if proposed_is_grouped_elective and row_is_grouped_elective:
                if proposed_student_ids is None:
                    proposed_student_ids = await ElectiveEligibilityService.projected_student_ids_for_classes(
                        db,
                        curriculum_subject_id=curriculum_subject_id,
                        class_ids=tuple(proposed_class_ids),
                        academic_session_id=session_id,
                    )
                row_student_ids = await cls._projected_audience_ids(db, exam=row)
                if proposed_student_ids.isdisjoint(row_student_ids):
                    continue

            def local_time(value: datetime) -> str:
                return value.astimezone(SCHOOL_CALENDAR_TIMEZONE).strftime(
                    "%d %b %Y, %I:%M %p WAT"
                )

            raise ExamStateError(
                f"Schedule clash: '{row.title}' reserves shared students from "
                f"{local_time(row.scheduled_start_at)} to {local_time(row_end)} "
                "(including the entry window). Start this exam at or after that "
                "window ends, or choose an earlier slot that finishes before it begins."
            )

    @staticmethod
    def _candidate_overlap_exists_statement(exam_id: UUID):
        current_candidate = aliased(ExamCandidate)
        busy_candidate = aliased(ExamCandidate)
        busy_exam = aliased(Exam)
        return (
            select(1)
            .select_from(current_candidate)
            .join(
                busy_candidate,
                and_(
                    busy_candidate.student_id == current_candidate.student_id,
                    busy_candidate.exam_id != current_candidate.exam_id,
                    busy_candidate.status == CandidateStatus.ELIGIBLE,
                ),
            )
            .join(busy_exam, busy_exam.id == busy_candidate.exam_id)
            .where(
                current_candidate.exam_id == exam_id,
                current_candidate.status == CandidateStatus.ELIGIBLE,
                busy_exam.status.in_(OPERATIONAL_EXAM_STATUSES),
            )
            .exists()
        )

    @classmethod
    async def _candidate_conflict_exam_ids(
        cls,
        db: AsyncSession,
        *,
        exam_id: UUID,
    ) -> tuple[UUID, ...]:
        current_candidate = aliased(ExamCandidate)
        busy_candidate = aliased(ExamCandidate)
        busy_exam = aliased(Exam)
        rows = await db.execute(
            select(busy_exam.id)
            .select_from(current_candidate)
            .join(
                busy_candidate,
                and_(
                    busy_candidate.student_id == current_candidate.student_id,
                    busy_candidate.exam_id != current_candidate.exam_id,
                    busy_candidate.status == CandidateStatus.ELIGIBLE,
                ),
            )
            .join(busy_exam, busy_exam.id == busy_candidate.exam_id)
            .where(
                current_candidate.exam_id == exam_id,
                current_candidate.status == CandidateStatus.ELIGIBLE,
                busy_exam.status.in_(OPERATIONAL_EXAM_STATUSES),
            )
            .distinct()
            .order_by(busy_exam.id.asc())
        )
        return tuple(rows.scalars().all())

    @classmethod
    async def require_level_free(cls, db: AsyncSession, *, exam_id: UUID) -> None:
        """Enforce candidate and timetable safety for activation/resume hooks."""

        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id)
        if exam is None:
            raise ExamNotFound("Examination does not exist")

        if exam.status == ExamStatus.SEALED:
            await cls.require_activation_clear(
                db,
                exam_id=exam.id,
                proposed_activation_at=datetime.now(UTC),
            )
            return

        level_id = await cls.level_id(db, exam.curriculum_subject_id)
        await cls.acquire_level_lock(
            db, session_id=exam.session_id, term_id=exam.term_id, level_id=level_id
        )
        await cls.acquire_operational_candidate_lock(db)
        overlap_exists = cls._candidate_overlap_exists_statement(exam.id)
        if bool(await db.scalar(select(overlap_exists))):
            raise ExamStateError(
                "One or more eligible candidates are already assigned to another "
                "active, suspended, or finalizing examination"
            )

    @staticmethod
    def _cascade_planned_windows(
        *,
        source_window: _ScopeWindow,
        fixed_windows: list[_ScopeWindow],
        planned_nodes: list[_PlannedNode],
        checked_at: datetime,
    ) -> tuple[ActivationScheduleImpact, ...]:
        """Resolve a scope-aware forward timetable without mutating exam rows.

        Every resolved planned exam becomes a blocker for later exams. That is
        what allows a delayed specialized subject to move a general subject and
        the delayed general subject to then propagate into another department.
        """

        blockers: list[_ScopeWindow] = [source_window, *fixed_windows]
        impacts: list[ActivationScheduleImpact] = []

        for node in sorted(
            planned_nodes,
            key=lambda item: (
                item.scheduled_start_at or datetime.max.replace(tzinfo=UTC),
                str(item.exam_id),
            ),
        ):
            scheduled = node.scheduled_start_at
            if scheduled is None:
                relevant = [
                    blocker.exam_id
                    for blocker in blockers
                    if not node.class_ids.isdisjoint(blocker.class_ids)
                ]
                if relevant:
                    impacts.append(
                        ActivationScheduleImpact(
                            exam_id=node.exam_id,
                            title=node.title,
                            status=node.status,
                            scheduled_start_at=None,
                            scheduled_end_at=None,
                            suggested_start_at=None,
                            suggested_end_at=None,
                            delay_seconds=None,
                            blocked_by_exam_ids=tuple(dict.fromkeys(relevant)),
                            reason="Affected sealed examination has no usable schedule",
                        )
                    )
                    blockers.append(
                        _ScopeWindow(
                            exam_id=node.exam_id,
                            title=node.title,
                            class_ids=node.class_ids,
                            start_at=checked_at,
                            end_at=None,
                        )
                    )
                continue

            scheduled_end = scheduled + node.window_duration
            proposed_start = scheduled
            causes: list[UUID] = []

            if scheduled < checked_at and not node.class_ids.isdisjoint(
                source_window.class_ids
            ):
                if source_window.end_at is None:
                    impacts.append(
                        ActivationScheduleImpact(
                            exam_id=node.exam_id,
                            title=node.title,
                            status=node.status,
                            scheduled_start_at=scheduled,
                            scheduled_end_at=scheduled_end,
                            suggested_start_at=None,
                            suggested_end_at=None,
                            delay_seconds=None,
                            blocked_by_exam_ids=(source_window.exam_id,),
                            reason="Overdue examination conflicts with an unresolved operational sitting",
                        )
                    )
                    blockers.append(
                        _ScopeWindow(
                            exam_id=node.exam_id,
                            title=node.title,
                            class_ids=node.class_ids,
                            start_at=scheduled,
                            end_at=None,
                        )
                    )
                    continue
                proposed_start = max(proposed_start, source_window.end_at)
                causes.append(source_window.exam_id)

            while True:
                proposed_end = proposed_start + node.window_duration
                unresolved = [
                    blocker
                    for blocker in blockers
                    if blocker.end_at is None
                    and not node.class_ids.isdisjoint(blocker.class_ids)
                    and proposed_end > blocker.start_at
                ]
                if unresolved:
                    causes.extend(blocker.exam_id for blocker in unresolved)
                    unique_causes = tuple(dict.fromkeys(causes))
                    impacts.append(
                        ActivationScheduleImpact(
                            exam_id=node.exam_id,
                            title=node.title,
                            status=node.status,
                            scheduled_start_at=scheduled,
                            scheduled_end_at=scheduled_end,
                            suggested_start_at=None,
                            suggested_end_at=None,
                            delay_seconds=None,
                            blocked_by_exam_ids=unique_causes,
                            reason="A conflicting operational examination has no reliable finish time yet, so no safe start can be calculated",
                        )
                    )
                    blockers.append(
                        _ScopeWindow(
                            exam_id=node.exam_id,
                            title=node.title,
                            class_ids=node.class_ids,
                            start_at=proposed_start,
                            end_at=None,
                        )
                    )
                    break

                finite_conflicts = [
                    blocker
                    for blocker in blockers
                    if blocker.end_at is not None
                    and not node.class_ids.isdisjoint(blocker.class_ids)
                    and ExamTimetableService.intervals_overlap(
                        proposed_start,
                        proposed_end,
                        blocker.start_at,
                        blocker.end_at,
                    )
                ]
                if not finite_conflicts:
                    if proposed_start > scheduled:
                        unique_causes = tuple(dict.fromkeys(causes))
                        impacts.append(
                            ActivationScheduleImpact(
                                exam_id=node.exam_id,
                                title=node.title,
                                status=node.status,
                                scheduled_start_at=scheduled,
                                scheduled_end_at=scheduled_end,
                                suggested_start_at=proposed_start,
                                suggested_end_at=proposed_end,
                                delay_seconds=int(
                                    (proposed_start - scheduled).total_seconds()
                                ),
                                blocked_by_exam_ids=unique_causes,
                                reason="Scheduled students are still occupied by an earlier operational or displaced examination",
                            )
                        )
                    blockers.append(
                        _ScopeWindow(
                            exam_id=node.exam_id,
                            title=node.title,
                            class_ids=node.class_ids,
                            start_at=proposed_start,
                            end_at=proposed_end,
                        )
                    )
                    break

                causes.extend(blocker.exam_id for blocker in finite_conflicts)
                proposed_start = max(
                    blocker.end_at
                    for blocker in finite_conflicts
                    if blocker.end_at is not None
                )

        return tuple(impacts)

    @classmethod
    async def activation_preflight(
        cls,
        db: AsyncSession,
        *,
        exam_id: UUID,
        proposed_activation_at: datetime | None = None,
        schedule_overrides: dict[UUID, datetime] | None = None,
        include_conflict_details: bool = True,
        apply_recovery_buffer: bool = True,
    ) -> ActivationPreflight:
        """Calculate whether a SEALED exam can start without timetable damage.

        This method never mutates a schedule. ``schedule_overrides`` lets the
        operational reschedule endpoint validate an entire admin-proposed batch
        against the exact same logic before saving any row. Late-exam recovery
        suggestions reserve a five-minute activation window by default so a
        suggestion does not become invalid while the admin is applying it.
        """

        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id)
        if exam is None:
            raise ExamNotFound("Examination does not exist")

        checked_at = proposed_activation_at or datetime.now(UTC)
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("proposed_activation_at must include a timezone")
        checked_at = checked_at.astimezone(UTC)

        level_id = await cls.level_id(db, exam.curriculum_subject_id)
        await cls.acquire_level_lock(
            db,
            session_id=exam.session_id,
            term_id=exam.term_id,
            level_id=level_id,
        )
        await cls.acquire_operational_candidate_lock(db)

        blockers: list[str] = []
        scheduled = exam.scheduled_start_at
        delay_seconds = 0
        schedule_date_expired = False
        if scheduled is None:
            blockers.append("missing_schedule")
        else:
            scheduled = scheduled.astimezone(UTC)
            scheduled_date = scheduled.astimezone(SCHOOL_CALENDAR_TIMEZONE).date()
            checked_date = checked_at.astimezone(SCHOOL_CALENDAR_TIMEZONE).date()
            if scheduled_date < checked_date:
                schedule_date_expired = True
                blockers.append("schedule_date_expired")
                delay_seconds = int((checked_at - scheduled).total_seconds())
            elif checked_at < scheduled:
                blockers.append("too_early")
            else:
                delay_seconds = int((checked_at - scheduled).total_seconds())

        overlap_exists = cls._candidate_overlap_exists_statement(exam.id)
        has_candidate_conflict = bool(await db.scalar(select(overlap_exists)))
        conflicting_ids: tuple[UUID, ...] = ()
        if has_candidate_conflict:
            blockers.append("candidate_scope_conflict")
            if include_conflict_details:
                conflicting_ids = await cls._candidate_conflict_exam_ids(
                    db,
                    exam_id=exam.id,
                )

        rows = await cls.list_leaf_exams(
            db,
            session_id=exam.session_id,
            term_id=exam.term_id,
            level_id=level_id,
            exclude_exam_id=exam.id,
            statuses=(
                ExamStatus.SEALED,
                ExamStatus.ACTIVE,
                ExamStatus.SUSPENDED,
                ExamStatus.CLOSING,
                ExamStatus.CANCELLING,
            ),
        )
        all_exams = [exam, *rows]
        scope_map = await cls._scope_map_for_exams(db, all_exams)
        source_scope = scope_map.get(exam.id, frozenset())
        if not source_scope:
            blockers.append("missing_delivery_scope")

        actual_projected_end: datetime | None = None
        impact_start = checked_at
        suggestion_valid_until_at: datetime | None = None
        source_is_due = (
            scheduled is not None
            and checked_at >= scheduled
            and not schedule_date_expired
        )
        if scheduled is not None and not schedule_date_expired:
            actual_projected_end = cls.projected_end_for_actual_start(
                exam,
                actual_start_at=checked_at,
            )
            lateness = checked_at - scheduled
            if timedelta(0) <= lateness <= ACTIVATION_IMPACT_TOLERANCE:
                impact_start = scheduled
            elif lateness > ACTIVATION_IMPACT_TOLERANCE and apply_recovery_buffer:
                impact_start = checked_at + ACTIVATION_RECOVERY_BUFFER
                suggestion_valid_until_at = impact_start
        elif scheduled is None and source_scope:
            actual_projected_end = cls.projected_end_for_actual_start(
                exam,
                actual_start_at=checked_at,
            )

        source_end = (
            cls.projected_end_for_actual_start(exam, actual_start_at=impact_start)
            if source_scope and source_is_due
            else None
        )
        source_window = _ScopeWindow(
            exam_id=exam.id,
            title=exam.title,
            class_ids=source_scope,
            start_at=impact_start,
            end_at=source_end,
        )

        operational = [row for row in rows if row.status in OPERATIONAL_EXAM_STATUSES]
        completed_pause, open_suspensions = await cls._suspension_state(
            db,
            [row.id for row in operational],
        )

        fixed_windows: list[_ScopeWindow] = []
        for row in operational:
            row_scope = scope_map.get(row.id, frozenset())
            actual_start = row.activated_at or row.scheduled_start_at or checked_at
            actual_start = actual_start.astimezone(UTC)
            unresolved = (
                row.status
                in {
                    ExamStatus.SUSPENDED,
                    ExamStatus.CLOSING,
                    ExamStatus.CANCELLING,
                }
                or row.id in open_suspensions
                or row.activated_at is None
            )
            end_at = None
            if not unresolved:
                projected_end = cls.projected_end_for_actual_start(
                    row,
                    actual_start_at=actual_start,
                    completed_pause=completed_pause.get(row.id, timedelta(0)),
                )
                if projected_end <= checked_at:
                    unresolved = True
                else:
                    end_at = projected_end
            fixed_windows.append(
                _ScopeWindow(
                    exam_id=row.id,
                    title=row.title,
                    class_ids=row_scope,
                    start_at=actual_start,
                    end_at=end_at,
                )
            )

        overrides = schedule_overrides or {}
        projected_parallel_overdue_ids: set[UUID] = set()
        parallel_recovery_start = (
            checked_at + ACTIVATION_RECOVERY_BUFFER
            if apply_recovery_buffer
            else checked_at
        )

        for row in rows:
            if row.status != ExamStatus.SEALED:
                continue
            row_scope = scope_map.get(row.id, frozenset())
            base_start = overrides.get(row.id, row.scheduled_start_at)
            if (
                base_start is None
                or base_start >= checked_at
                or not source_scope
                or not row_scope
                or not source_scope.isdisjoint(row_scope)
            ):
                continue

            window_duration = timedelta(minutes=row.duration_minutes) + cls.entry_grace(
                row
            )
            fixed_windows.append(
                _ScopeWindow(
                    exam_id=row.id,
                    title=row.title,
                    class_ids=row_scope,
                    start_at=parallel_recovery_start,
                    end_at=parallel_recovery_start + window_duration,
                )
            )
            projected_parallel_overdue_ids.add(row.id)

        planned_nodes: list[_PlannedNode] = []
        for row in rows:
            if row.status != ExamStatus.SEALED:
                continue
            if row.id in projected_parallel_overdue_ids:
                continue
            base_start = overrides.get(row.id, row.scheduled_start_at)
            window_duration = timedelta(minutes=row.duration_minutes) + cls.entry_grace(
                row
            )
            planned_nodes.append(
                _PlannedNode(
                    exam_id=row.id,
                    title=row.title,
                    status=row.status,
                    class_ids=scope_map.get(row.id, frozenset()),
                    scheduled_start_at=base_start,
                    window_duration=window_duration,
                )
            )

        impacts: tuple[ActivationScheduleImpact, ...] = ()
        if source_scope and source_end is not None:
            impacts = cls._cascade_planned_windows(
                source_window=source_window,
                fixed_windows=fixed_windows,
                planned_nodes=planned_nodes,
                checked_at=checked_at,
            )
        if impacts:
            blockers.append("schedule_reschedule_required")

        return ActivationPreflight(
            exam_id=exam.id,
            checked_at=checked_at,
            scheduled_start_at=scheduled,
            proposed_activation_at=checked_at,
            projected_end_at=actual_projected_end,
            delay_seconds=delay_seconds,
            can_activate=not blockers,
            blockers=tuple(dict.fromkeys(blockers)),
            conflicting_operational_exam_ids=conflicting_ids,
            affected_exams=impacts,
            suggestion_valid_until_at=suggestion_valid_until_at,
        )

    @classmethod
    async def require_activation_clear(
        cls,
        db: AsyncSession,
        *,
        exam_id: UUID,
        proposed_activation_at: datetime,
    ) -> ActivationPreflight:
        """Enforce the preflight again inside the activation transaction."""

        preflight = await cls.activation_preflight(
            db,
            exam_id=exam_id,
            proposed_activation_at=proposed_activation_at,
            include_conflict_details=False,
            apply_recovery_buffer=False,
        )
        if "missing_schedule" in preflight.blockers:
            raise ExamStateError("Examination is missing a scheduled start time")
        if "schedule_date_expired" in preflight.blockers:
            raise ExamStateError(
                "Examination scheduled date has passed; reschedule the examination "
                "before activation"
            )
        if "too_early" in preflight.blockers:
            raise ExamStateError(
                "Examination cannot be activated before its scheduled start time"
            )
        if "missing_delivery_scope" in preflight.blockers:
            raise ExamStateError("Examination has no frozen delivery scope")
        if "candidate_scope_conflict" in preflight.blockers:
            raise ExamStateError(
                "One or more eligible candidates are already assigned to another "
                "active, suspended, or finalizing examination"
            )
        if preflight.affected_exams:
            raise ExamScheduleImpactError(
                "Activation would disrupt one or more downstream examinations; "
                "reschedule the affected chain before activating",
                preflight=preflight,
            )
        return preflight

    @classmethod
    async def impact_after_start(
        cls, db: AsyncSession, *, exam_id: UUID
    ) -> list[TimetableImpact]:
        """Backward-compatible simplified view of the current impact chain."""

        exam = await ExamRepository.get_exam_by_id(db, exam_id=exam_id)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.activated_at is None:
            return []
        preflight = await cls.activation_preflight(
            db,
            exam_id=exam.id,
            proposed_activation_at=exam.activated_at,
            apply_recovery_buffer=False,
        )
        return [
            TimetableImpact(
                exam_id=impact.exam_id,
                title=impact.title,
                original_start_at=impact.scheduled_start_at,
                proposed_start_at=impact.suggested_start_at,
                proposed_end_at=impact.suggested_end_at,
            )
            for impact in preflight.affected_exams
            if impact.scheduled_start_at is not None
            and impact.suggested_start_at is not None
            and impact.suggested_end_at is not None
        ]
