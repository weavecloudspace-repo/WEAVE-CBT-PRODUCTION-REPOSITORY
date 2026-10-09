"""Offline student authentication and waiting-room/exam-scoped sessions."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.academics.models import StudentEnrollment
from app.domains.academics.repository import AcademicRepository
from app.domains.auth.student_models import StudentExamSession
from app.domains.auth.student_repository import StudentAuthRepository
from app.domains.auth.student_schemas import (
    StudentExamAvailability,
    StudentLoginResponse,
    StudentSessionResponse,
)
from app.domains.candidates.makeup_service import CandidateMakeupService
from app.domains.candidates.models import CandidateStatus, ExamCandidate
from app.domains.candidates.repository import CandidateRepository
from app.domains.exams.lineage import latest_exam_revision_clause
from app.domains.exams.models import Exam, ExamRosterStatus, ExamStatus

STUDENT_SESSION_TOKEN_BYTES = 48
STUDENT_SESSION_LIFETIME_HOURS = 8
INVALID_STUDENT_LOGIN = "Invalid admission number or password"
NO_EXAM_MESSAGE = "No examination is currently available for you."
WAITING_MESSAGE = "Your examination is scheduled and waiting for activation."
READY_MESSAGE = "Your examination is ready to begin."
SUSPENDED_MESSAGE = (
    "Your examination has been suspended. Stay in the waiting room until it is resumed."
)
MAKEUP_MESSAGE = "Your approved makeup examination is ready to begin."


class StudentAuthenticationError(ValueError):
    """Raised when local student authentication/session resolution fails."""


@dataclass(frozen=True)
class StudentSessionContext:
    session_id: UUID
    student_id: UUID
    candidate_id: UUID | None
    exam_id: UUID | None
    makeup_authorization_id: UUID | None

    @property
    def is_makeup(self) -> bool:
        return self.makeup_authorization_id is not None

    @property
    def is_exam_bound(self) -> bool:
        return self.candidate_id is not None and self.exam_id is not None


@dataclass(frozen=True)
class StudentExamResolution:
    candidate: ExamCandidate | None
    exam: Exam | None
    makeup_authorization_id: UUID | None
    availability: StudentExamAvailability
    status_message: str
    has_unfinished_attempt: bool = False


@dataclass(frozen=True)
class StudentLoginResult:
    raw_token: str
    expires_at: datetime
    response: StudentLoginResponse


def hash_student_session_token(token: str) -> str:
    if not isinstance(token, str) or not token:
        raise StudentAuthenticationError("Student session token is missing")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class StudentAuthService:
    @staticmethod
    async def _get_current_enrollment(
        db: AsyncSession,
        admission_number: str,
    ) -> StudentEnrollment | None:
        normalized = admission_number.strip().lower()
        result = await db.execute(
            select(StudentEnrollment)
            .where(
                func.lower(StudentEnrollment.admission_number) == normalized,
                StudentEnrollment.is_current.is_(True),
                StudentEnrollment.source_deleted_at.is_(None),
                StudentEnrollment.student_status == "active",
            )
            .order_by(StudentEnrollment.updated_at.desc())
            .limit(2)
        )
        matches = list(result.scalars().all())
        if len(matches) > 1:
            raise StudentAuthenticationError(
                "Admission number resolves to multiple current enrollments"
            )
        return matches[0] if matches else None

    @staticmethod
    async def _get_current_enrollment_for_student(
        db: AsyncSession,
        student_id: UUID,
    ) -> StudentEnrollment | None:
        result = await db.execute(
            select(StudentEnrollment)
            .where(
                StudentEnrollment.student_id == student_id,
                StudentEnrollment.is_current.is_(True),
                StudentEnrollment.source_deleted_at.is_(None),
                StudentEnrollment.student_status == "active",
            )
            .order_by(StudentEnrollment.updated_at.desc())
            .limit(2)
        )
        matches = list(result.scalars().all())
        if len(matches) > 1:
            raise StudentAuthenticationError(
                "Student resolves to multiple current enrollments"
            )
        return matches[0] if matches else None

    @staticmethod
    async def _normal_candidate_rows(
        db: AsyncSession,
        *,
        student_id: UUID,
        statuses: tuple[ExamStatus, ...],
    ) -> list[tuple[ExamCandidate, Exam]]:
        query = (
            select(ExamCandidate, Exam)
            .join(Exam, Exam.id == ExamCandidate.exam_id)
            .where(
                ExamCandidate.student_id == student_id,
                ExamCandidate.status == CandidateStatus.ELIGIBLE,
                Exam.status.in_(statuses),
                Exam.roster_status == ExamRosterStatus.READY,
                latest_exam_revision_clause(),
            )
            .order_by(Exam.scheduled_start_at.asc().nulls_last(), Exam.id.asc())
        )
        result = await db.execute(query)
        return list(result.tuples().all())

    @classmethod
    async def _resolve_candidate(
        cls,
        db: AsyncSession,
        *,
        enrollment: StudentEnrollment,
    ) -> StudentExamResolution:
        active = await cls._normal_candidate_rows(
            db,
            student_id=enrollment.student_id,
            statuses=(ExamStatus.ACTIVE,),
        )
        if len(active) > 1:
            raise StudentAuthenticationError(
                "Multiple active examinations were found for this student"
            )
        if active:
            candidate, exam = active[0]
            return StudentExamResolution(
                candidate=candidate,
                exam=exam,
                makeup_authorization_id=None,
                availability=StudentExamAvailability.READY,
                status_message=READY_MESSAGE,
            )

        suspended = await cls._normal_candidate_rows(
            db,
            student_id=enrollment.student_id,
            statuses=(ExamStatus.SUSPENDED,),
        )
        if len(suspended) > 1:
            raise StudentAuthenticationError(
                "Multiple suspended examinations were found for this student"
            )
        if suspended:
            candidate, exam = suspended[0]
            return StudentExamResolution(
                candidate=candidate,
                exam=exam,
                makeup_authorization_id=None,
                availability=StudentExamAvailability.SUSPENDED,
                status_message=SUSPENDED_MESSAGE,
            )

        waiting = await cls._normal_candidate_rows(
            db,
            student_id=enrollment.student_id,
            statuses=(ExamStatus.SEALED,),
        )
        if waiting:
            candidate, exam = waiting[0]
            return StudentExamResolution(
                candidate=candidate,
                exam=exam,
                makeup_authorization_id=None,
                availability=StudentExamAvailability.WAITING_FOR_ACTIVATION,
                status_message=WAITING_MESSAGE,
            )

        academic_session = await AcademicRepository.get_current_session(db)
        if academic_session is None:
            return StudentExamResolution(
                candidate=None,
                exam=None,
                makeup_authorization_id=None,
                availability=StudentExamAvailability.NO_EXAM,
                status_message=NO_EXAM_MESSAGE,
            )
        term = await AcademicRepository.get_current_term(
            db, session_id=academic_session.id
        )
        if term is None:
            return StudentExamResolution(
                candidate=None,
                exam=None,
                makeup_authorization_id=None,
                availability=StudentExamAvailability.NO_EXAM,
                status_message=NO_EXAM_MESSAGE,
            )

        queue = await CandidateMakeupService.resolve_queue(
            db,
            student_id=enrollment.student_id,
            session_id=academic_session.id,
            term_id=term.id,
        )
        if (
            not queue.available
            or queue.next_candidate_id is None
            or queue.next_exam_id is None
        ):
            return StudentExamResolution(
                candidate=None,
                exam=None,
                makeup_authorization_id=None,
                availability=StudentExamAvailability.NO_EXAM,
                status_message=queue.blocked_reason
                if queue.pending_count
                else NO_EXAM_MESSAGE,
            )

        candidate = await CandidateRepository.get_candidate_by_id(
            db, queue.next_candidate_id
        )
        exam = await db.get(Exam, queue.next_exam_id)
        if candidate is None or exam is None:
            return StudentExamResolution(
                candidate=None,
                exam=None,
                makeup_authorization_id=None,
                availability=StudentExamAvailability.NO_EXAM,
                status_message=NO_EXAM_MESSAGE,
            )
        return StudentExamResolution(
            candidate=candidate,
            exam=exam,
            makeup_authorization_id=queue.authorization_id,
            availability=StudentExamAvailability.MAKEUP,
            status_message=MAKEUP_MESSAGE,
            has_unfinished_attempt=queue.resume_existing_attempt,
        )

    @staticmethod
    async def _revoke_existing_sessions(
        db: AsyncSession,
        *,
        student_id: UUID,
        now: datetime,
    ) -> None:
        sessions = await StudentAuthRepository.list_unrevoked_sessions_for_student(
            db, student_id, lock=True
        )
        for session in sessions:
            session.revoked_at = now
            session.revocation_reason = "Superseded by a new student login"
        await StudentAuthRepository.save_sessions(db, sessions)

    @staticmethod
    def _verify_admission_password(
        *,
        submitted_admission_number: str,
        submitted_password: str,
        stored_admission_number: str,
    ) -> None:
        admission_number = submitted_admission_number.strip()
        stored_admission = stored_admission_number.strip()

        if not admission_number or admission_number != admission_number.upper():
            raise StudentAuthenticationError(INVALID_STUDENT_LOGIN)

        expected_admission = stored_admission.upper()
        expected_password = stored_admission.lower()

        if not secrets.compare_digest(admission_number, expected_admission):
            raise StudentAuthenticationError(INVALID_STUDENT_LOGIN)
        if not secrets.compare_digest(submitted_password, expected_password):
            raise StudentAuthenticationError(INVALID_STUDENT_LOGIN)

    @staticmethod
    def _display_name(enrollment: StudentEnrollment) -> str:
        parts = [
            str(getattr(enrollment, "first_name", "") or "").strip(),
            str(getattr(enrollment, "last_name", "") or "").strip(),
        ]
        value = " ".join(part for part in parts if part)
        return value or enrollment.admission_number

    @classmethod
    def _build_response(
        cls,
        *,
        enrollment: StudentEnrollment,
        resolution: StudentExamResolution,
    ) -> StudentLoginResponse:
        candidate = resolution.candidate
        exam = resolution.exam
        return StudentLoginResponse(
            student_id=enrollment.student_id,
            candidate_id=candidate.id if candidate is not None else None,
            exam_id=exam.id if exam is not None else None,
            exam_title=exam.title if exam is not None else None,
            duration_minutes=exam.duration_minutes
            if exam is not None and resolution.makeup_authorization_id is not None
            else None,
            display_name=(
                candidate.display_name
                if candidate is not None
                else cls._display_name(enrollment)
            ),
            availability=resolution.availability,
            status_message=resolution.status_message,
            has_unfinished_attempt=resolution.has_unfinished_attempt,
            is_makeup=resolution.makeup_authorization_id is not None,
            scheduled_start_at=(exam.scheduled_start_at if exam is not None else None),
            activated_at=(exam.activated_at if exam is not None else None),
        )

    @staticmethod
    def _apply_resolution_to_session(
        session: StudentExamSession,
        resolution: StudentExamResolution,
    ) -> None:
        candidate = resolution.candidate
        exam = resolution.exam
        session.candidate_id = candidate.id if candidate is not None else None
        session.exam_id = exam.id if exam is not None else None
        session.makeup_authorization_id = resolution.makeup_authorization_id

    @classmethod
    async def login(
        cls,
        db: AsyncSession,
        *,
        admission_number: str,
        password: str,
    ) -> StudentLoginResult:
        submitted_admission = admission_number.strip()
        if (
            not submitted_admission
            or submitted_admission != submitted_admission.upper()
        ):
            raise StudentAuthenticationError(INVALID_STUDENT_LOGIN)

        enrollment = await cls._get_current_enrollment(db, submitted_admission)
        if enrollment is None:
            raise StudentAuthenticationError(INVALID_STUDENT_LOGIN)

        cls._verify_admission_password(
            submitted_admission_number=submitted_admission,
            submitted_password=password,
            stored_admission_number=enrollment.admission_number,
        )

        resolution = await cls._resolve_candidate(db, enrollment=enrollment)
        if (resolution.candidate is not None and resolution.exam is not None) and (
            resolution.candidate.student_id != enrollment.student_id
            or resolution.candidate.exam_id != resolution.exam.id
        ):
            raise StudentAuthenticationError(
                "Resolved examination candidate is inconsistent with student identity"
            )

        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=STUDENT_SESSION_LIFETIME_HOURS)
        raw_token = secrets.token_urlsafe(STUDENT_SESSION_TOKEN_BYTES)
        session_row = StudentExamSession(
            student_id=enrollment.student_id,
            candidate_id=(
                resolution.candidate.id if resolution.candidate is not None else None
            ),
            exam_id=resolution.exam.id if resolution.exam is not None else None,
            makeup_authorization_id=resolution.makeup_authorization_id,
            token_hash=hash_student_session_token(raw_token),
            expires_at=expires_at,
            last_seen_at=now,
        )

        try:
            await cls._revoke_existing_sessions(
                db, student_id=enrollment.student_id, now=now
            )
            await StudentAuthRepository.add_session(db, session_row)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise StudentAuthenticationError(
                "Student waiting-room session could not be created"
            ) from exc

        response = cls._build_response(enrollment=enrollment, resolution=resolution)
        await cls._add_subject_to_response(db, response=response, resolution=resolution)
        return StudentLoginResult(
            raw_token=raw_token,
            expires_at=expires_at,
            response=response,
        )

    @classmethod
    async def resolve_session(
        cls,
        db: AsyncSession,
        *,
        raw_token: str,
        touch: bool = True,
    ) -> StudentSessionContext:
        token_hash = hash_student_session_token(raw_token)
        session = await StudentAuthRepository.get_session_by_hash(db, token_hash)
        now = datetime.now(UTC)
        if (
            session is None
            or session.revoked_at is not None
            or session.expires_at <= now
        ):
            raise StudentAuthenticationError("Student session is not active")

        if (session.candidate_id is None) != (session.exam_id is None):
            raise StudentAuthenticationError("Student session is inconsistent")

        if session.candidate_id is not None and session.exam_id is not None:
            candidate = await CandidateRepository.get_candidate_by_id(
                db, session.candidate_id
            )
            if (
                candidate is None
                or candidate.id != session.candidate_id
                or candidate.student_id != session.student_id
                or candidate.exam_id != session.exam_id
            ):
                raise StudentAuthenticationError("Student session is inconsistent")
        elif session.makeup_authorization_id is not None:
            raise StudentAuthenticationError("Student session is inconsistent")

        if touch and (now - session.last_seen_at) >= timedelta(minutes=5):
            session.last_seen_at = now
            await StudentAuthRepository.save_session(db, session)
            await db.commit()

        return StudentSessionContext(
            session_id=session.id,
            student_id=session.student_id,
            candidate_id=session.candidate_id,
            exam_id=session.exam_id,
            makeup_authorization_id=session.makeup_authorization_id,
        )

    @classmethod
    async def get_waiting_room_status(
        cls,
        db: AsyncSession,
        *,
        raw_token: str,
    ) -> StudentSessionResponse:
        token_hash = hash_student_session_token(raw_token)
        session = await StudentAuthRepository.get_session_by_hash(
            db, token_hash, lock=True
        )
        now = datetime.now(UTC)
        if (
            session is None
            or session.revoked_at is not None
            or session.expires_at <= now
        ):
            raise StudentAuthenticationError("Student session is not active")

        enrollment = await cls._get_current_enrollment_for_student(
            db, session.student_id
        )
        if enrollment is None:
            raise StudentAuthenticationError("Student enrollment is no longer active")

        resolution = await cls._resolve_candidate(db, enrollment=enrollment)
        if (resolution.candidate is not None and resolution.exam is not None) and (
            resolution.candidate.student_id != enrollment.student_id
            or resolution.candidate.exam_id != resolution.exam.id
        ):
            raise StudentAuthenticationError(
                "Resolved examination candidate is inconsistent with student identity"
            )

        cls._apply_resolution_to_session(session, resolution)
        session.last_seen_at = now
        await StudentAuthRepository.save_session(db, session)
        await db.commit()

        response = cls._build_response(
            enrollment=enrollment,
            resolution=resolution,
        )
        await cls._add_subject_to_response(db, response=response, resolution=resolution)
        return StudentSessionResponse(
            **response.model_dump(),
            expires_at=session.expires_at,
        )

    @staticmethod
    async def _add_subject_to_response(db, *, response, resolution):
        if (
            resolution.exam is not None
            and resolution.makeup_authorization_id is not None
        ):
            subject = await AcademicRepository.get_curriculum_subject_by_id(
                db, resolution.exam.curriculum_subject_id
            )
            if subject is not None:
                academic_subject = await AcademicRepository.get_subject_by_id(
                    db, subject.subject_id
                )
                response.subject_name = (
                    academic_subject.name if academic_subject is not None else None
                )

    @classmethod
    async def logout(cls, db: AsyncSession, *, raw_token: str) -> None:
        session = await StudentAuthRepository.get_session_by_hash(
            db, hash_student_session_token(raw_token), lock=True
        )
        if session is None or session.revoked_at is not None:
            return
        session.revoked_at = datetime.now(UTC)
        session.revocation_reason = "Student logged out"
        await StudentAuthRepository.save_session(db, session)
        await db.commit()
