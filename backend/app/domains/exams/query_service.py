"""Read-oriented examination query services."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicAuthorizationError
from app.domains.auth.models import LocalActor
from app.domains.exams.exceptions import ExamAuthorizationError
from app.domains.exams.models import Exam, ExamRosterStatus, ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.exams.service import ExamService


class ExamQueryService:
    """Provide actor-scoped examination collection reads."""

    _SCAN_BATCH_SIZE = 200

    @classmethod
    async def list_visible_exams(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        session_id: UUID | None = None,
        term_id: UUID | None = None,
        curriculum_subject_id: UUID | None = None,
        level_id: UUID | None = None,
        subject_id: UUID | None = None,
        target_class_id: UUID | None = None,
        assessment_scheme_id: UUID | None = None,
        assessment_component_id: UUID | None = None,
        created_by_actor_id: UUID | None = None,
        status: ExamStatus | None = None,
        roster_status: ExamRosterStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Exam], int]:
        filters = {
            "session_id": session_id,
            "term_id": term_id,
            "curriculum_subject_id": curriculum_subject_id,
            "level_id": level_id,
            "subject_id": subject_id,
            "target_class_id": target_class_id,
            "assessment_scheme_id": assessment_scheme_id,
            "assessment_component_id": assessment_component_id,
            "created_by_actor_id": created_by_actor_id,
            "status": status,
            "roster_status": roster_status,
        }

        if not actor.is_active:
            raise ExamAuthorizationError("Active local actor is required")

        if actor.role == "admin":
            rows = await ExamRepository.list_exams(
                db,
                **filters,
                offset=offset,
                limit=limit,
            )
            total = await ExamRepository.count_exams(db, **filters)
            return rows, total

        if actor.role != "teacher":
            raise ExamAuthorizationError("You are not allowed to view examinations")

        raw_total = await ExamRepository.count_exams(db, **filters)
        visible: list[Exam] = []

        scan_offset = 0
        while scan_offset < raw_total:
            batch = await ExamRepository.list_exams(
                db,
                **filters,
                offset=scan_offset,
                limit=cls._SCAN_BATCH_SIZE,
            )
            if not batch:
                break

            for exam in batch:
                try:
                    await ExamService.get_exam(
                        db,
                        actor=actor,
                        exam_id=exam.id,
                    )
                except (AcademicAuthorizationError, ExamAuthorizationError):
                    continue
                visible.append(exam)

            scan_offset += len(batch)

        total = len(visible)
        return visible[offset : offset + limit], total
