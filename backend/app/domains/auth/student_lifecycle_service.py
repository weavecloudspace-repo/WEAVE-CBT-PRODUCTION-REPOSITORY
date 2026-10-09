"""Student authentication facade that preserves exam lifecycle binding."""

from __future__ import annotations

from app.domains.attempts.models import AttemptStatus
from app.domains.attempts.repository import AttemptRepository
from app.domains.auth.student_schemas import StudentExamAvailability
from app.domains.auth.student_service import (
    INVALID_STUDENT_LOGIN,
    NO_EXAM_MESSAGE,
    READY_MESSAGE,
    StudentAuthenticationError,
    StudentExamResolution,
    StudentSessionContext,
)
from app.domains.auth.student_service import (
    StudentAuthService as _StudentAuthService,
)
from app.domains.exams.models import ExamStatus

SUSPENDED_MESSAGE = (
    "This examination is temporarily paused. Please wait for an administrator "
    "to resume it. Your saved work and remaining time are protected."
)
RESUME_MESSAGE = (
    "Your examination is ready to resume. Your saved answers are preserved."
)
COMPLETED_MESSAGE = (
    "You have already completed this examination. Your score is ready to view."
)

# A submitted score is candidate-facing only while that exact sitting is still
# live. Closing/cancelling/closed/cancelled exams deliberately fall out of this
# set so the student returns to normal waiting-room resolution for the next exam.
_LIVE_EXAM_STATUSES = (
    ExamStatus.ACTIVE,
    ExamStatus.SUSPENDED,
)
_UNFINISHED_ATTEMPT_STATUSES = {
    AttemptStatus.IN_PROGRESS,
    AttemptStatus.INTERRUPTED,
}


class StudentAuthService(_StudentAuthService):
    """Resolve one deterministic student-facing state across concurrent live exams."""

    @staticmethod
    def _no_live_exam_resolution() -> StudentExamResolution:
        return StudentExamResolution(
            candidate=None,
            exam=None,
            makeup_authorization_id=None,
            availability=StudentExamAvailability.NO_EXAM,
            status_message=NO_EXAM_MESSAGE,
        )

    @classmethod
    async def _resolve_candidate(cls, db, *, enrollment):
        live_rows = await cls._normal_candidate_rows(
            db,
            student_id=enrollment.student_id,
            statuses=_LIVE_EXAM_STATUSES,
        )

        classified = []
        for candidate, exam in live_rows:
            attempt = await AttemptRepository.get_attempt_by_candidate_id(
                db,
                candidate.id,
            )
            classified.append((candidate, exam, attempt))

        # Work that still needs the student's attention always wins over an
        # already-submitted live paper. This matters for legitimate concurrent
        # elective/departmental sittings where the same level has many live exams.
        unfinished = [
            row
            for row in classified
            if row[2] is None or row[2].status in _UNFINISHED_ATTEMPT_STATUSES
        ]
        if len(unfinished) > 1:
            raise StudentAuthenticationError(
                "Multiple unfinished live examinations were found for this student"
            )
        if unfinished:
            candidate, exam, attempt = unfinished[0]
            if exam.status == ExamStatus.SUSPENDED:
                return StudentExamResolution(
                    candidate=candidate,
                    exam=exam,
                    makeup_authorization_id=None,
                    availability=StudentExamAvailability.SUSPENDED,
                    status_message=SUSPENDED_MESSAGE,
                    has_unfinished_attempt=attempt is not None,
                )
            return StudentExamResolution(
                candidate=candidate,
                exam=exam,
                makeup_authorization_id=None,
                availability=StudentExamAvailability.READY,
                status_message=RESUME_MESSAGE if attempt is not None else READY_MESSAGE,
                has_unfinished_attempt=attempt is not None,
            )

        completed = [
            row
            for row in classified
            if row[2] is not None and row[2].status == AttemptStatus.SUBMITTED
        ]
        if len(completed) == 1:
            candidate, exam, _attempt = completed[0]
            return StudentExamResolution(
                candidate=candidate,
                exam=exam,
                makeup_authorization_id=None,
                availability=StudentExamAvailability.COMPLETED,
                status_message=COMPLETED_MESSAGE,
            )

        # Two simultaneously live submitted papers are an impossible/ambiguous
        # scheduling state for normal CBT use. Do not arbitrarily pick a score.
        # Likewise, a live candidate row whose attempt ended without submission
        # must never be offered as a fresh start.
        if live_rows:
            return cls._no_live_exam_resolution()

        # With no ACTIVE/SUSPENDED exam left, fall back to the normal resolver:
        # SEALED -> waiting for activation, approved makeup -> makeup, otherwise
        # the general waiting room. CLOSED/CANCELLED exams are therefore ignored.
        return await super()._resolve_candidate(db, enrollment=enrollment)


__all__ = [
    "COMPLETED_MESSAGE",
    "INVALID_STUDENT_LOGIN",
    "StudentAuthService",
    "StudentAuthenticationError",
    "StudentSessionContext",
]
