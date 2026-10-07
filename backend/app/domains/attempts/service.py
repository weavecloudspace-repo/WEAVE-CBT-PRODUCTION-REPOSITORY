"""Application service for candidate examination attempts."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from secrets import SystemRandom
from typing import cast
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicAuthorizationError
from app.domains.academics.repository import AcademicRepository
from app.domains.attempts.models import (
    AttemptAnswer,
    AttemptAnswerSelection,
    AttemptEndReason,
    AttemptInterruption,
    AttemptOptionAllocation,
    AttemptQuestionAllocation,
    AttemptStatus,
    ExamAttempt,
)
from app.domains.attempts.repository import AttemptRepository
from app.domains.attempts.runtime_repository import AttemptRuntimeRepository
from app.domains.attempts.schemas import (
    AttemptAnswerResponse,
    AttemptOperatorResponse,
    AttemptOptionResponse,
    AttemptQuestionResponse,
    AttemptResponse,
    AttemptSubmissionResponse,
)
from app.domains.auth.models import LocalActor
from app.domains.auth.student_repository import StudentAuthRepository
from app.domains.auth.student_service import StudentSessionContext
from app.domains.candidates.makeup_service import CandidateMakeupService
from app.domains.candidates.models import (
    CandidateLateStartAuthorization,
    CandidateMakeupAuthorization,
    CandidateStatus,
    ExamCandidate,
)
from app.domains.candidates.repository import CandidateRepository
from app.domains.exams.exceptions import ExamNotFound
from app.domains.exams.models import Exam, ExamStatus
from app.domains.exams.repository import ExamRepository
from app.domains.questions.models import QuestionType
from app.domains.questions.repository import QuestionRepository
from app.domains.results.service import ResultService


class AttemptStateError(ValueError):
    """Raised when an attempt transition is not legal."""


class AttemptService:
    @staticmethod
    async def _get_candidate_and_exam(
        db: AsyncSession,
        *,
        context: StudentSessionContext,
        lock: bool = False,
    ) -> tuple[ExamCandidate, Exam]:
        candidate = await CandidateRepository.get_candidate_by_id(
            db,
            context.candidate_id,
            lock=lock,
        )
        if candidate is None:
            raise AttemptStateError("Candidate does not exist")
        if (
            candidate.student_id != context.student_id
            or candidate.exam_id != context.exam_id
        ):
            raise AttemptStateError("Student session candidate identity mismatch")

        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=context.exam_id,
            lock=lock,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        return candidate, exam

    @staticmethod
    async def _is_makeup_candidate(
        db: AsyncSession,
        candidate_id: UUID,
    ) -> bool:
        authorization = await CandidateRepository.get_active_makeup_authorization(
            db,
            candidate_id,
        )
        return (
            authorization is not None
            and authorization.consumed_at is not None
            and authorization.revoked_at is None
        )

    @staticmethod
    async def _effective_late_start_deadline(exam: Exam) -> datetime | None:
        deadline = exam.latest_normal_start_at
        if deadline is None:
            return None

        # Preserve the configured entry-grace window when the administrator
        # deliberately/operationally activates a paper later than planned.
        if (
            exam.scheduled_start_at is not None
            and exam.activated_at is not None
            and exam.activated_at > exam.scheduled_start_at
        ):
            deadline = deadline + (exam.activated_at - exam.scheduled_start_at)
        return deadline

    @staticmethod
    async def _validate_makeup_start(
        db: AsyncSession,
        *,
        context: StudentSessionContext,
        candidate,
        exam: Exam,
        now: datetime,
    ) -> CandidateMakeupAuthorization:
        if context.makeup_authorization_id is None:
            raise AttemptStateError("Student session is not a makeup session")
        if exam.status != ExamStatus.CLOSED:
            raise AttemptStateError(
                "Makeup examination can only use a closed original examination"
            )

        authorization = await CandidateRepository.get_makeup_authorization_by_id(
            db,
            context.makeup_authorization_id,
            lock=True,
        )
        if (
            authorization is None
            or authorization.candidate_id != candidate.id
            or authorization.revoked_at is not None
        ):
            raise AttemptStateError("Makeup authorization is not active")
        if authorization.consumed_at is not None:
            raise AttemptStateError("Makeup authorization has already been consumed")

        queue = await CandidateMakeupService.resolve_queue(
            db,
            student_id=candidate.student_id,
            session_id=exam.session_id,
            term_id=exam.term_id,
        )
        if not queue.available or queue.next_candidate_id != candidate.id:
            raise AttemptStateError(
                queue.blocked_reason
                or "This is not the student's next available makeup examination"
            )

        return authorization

    @staticmethod
    async def _validate_normal_start(
        db: AsyncSession,
        *,
        candidate,
        exam: Exam,
        now: datetime,
    ) -> None | CandidateLateStartAuthorization:
        if exam.status != ExamStatus.ACTIVE:
            raise AttemptStateError("Normal examination is not active")
        if candidate.status != CandidateStatus.ELIGIBLE:
            raise AttemptStateError(
                "Candidate is not eligible to start this examination"
            )

        deadline = await AttemptService._effective_late_start_deadline(exam)
        if deadline is None or now <= deadline:
            return None

        authorization = await CandidateRepository.get_usable_late_start_authorization(
            db,
            candidate.id,
            at=now,
            lock=True,
        )
        if authorization is None:
            raise AttemptStateError(
                "Candidate requires a valid late-start authorization"
            )
        return authorization

    @staticmethod
    def _validate_source_question_options(question, options: list) -> None:
        if len(options) < 2:
            raise AttemptStateError(
                "Every makeup question must contain at least two answer options"
            )
        correct_count = sum(1 for option in options if option.is_correct)
        if question.question_type == QuestionType.SINGLE_CHOICE:
            if correct_count != 1:
                raise AttemptStateError(
                    "Single-choice makeup question must have exactly one correct option"
                )
        elif question.question_type == QuestionType.MULTIPLE_CHOICE:
            if correct_count < 2 or correct_count == len(options):
                raise AttemptStateError(
                    "Multiple-choice makeup question has an invalid correct-option set"
                )
        else:
            raise AttemptStateError("Unsupported makeup question type")

    @classmethod
    async def _allocate_normal_paper(
        cls,
        db: AsyncSession,
        *,
        attempt: ExamAttempt,
        exam: Exam,
    ) -> None:
        questions = await ExamRepository.list_exam_questions(db, exam.id)
        if len(questions) != exam.question_count:
            raise AttemptStateError(
                "Frozen question count does not match examination configuration"
            )

        ordered_questions = list(questions)
        if exam.shuffle_questions:
            SystemRandom().shuffle(ordered_questions)

        allocations = [
            AttemptQuestionAllocation(
                attempt_id=attempt.id,
                exam_question_id=question.id,
                source_question_id=question.source_question_id,
                source_question_version=question.source_question_version,
                question_type=question.question_type,
                position=position,
                prompt=question.prompt,
                instruction=question.instruction,
                image_asset_id=question.image_asset_id,
            )
            for position, question in enumerate(ordered_questions, start=1)
        ]
        allocations = await AttemptRepository.add_question_allocations(
            db,
            allocations,
        )
        allocation_by_exam_question = {
            allocation.exam_question_id: allocation for allocation in allocations
        }

        all_options = await ExamRepository.list_exam_question_options_for_exam(
            db,
            exam.id,
        )
        options_by_question: dict[UUID, list] = defaultdict(list)
        for option in all_options:
            options_by_question[option.exam_question_id].append(option)

        option_allocations: list[AttemptOptionAllocation] = []
        for question in ordered_questions:
            source_options = list(options_by_question.get(question.id, []))
            if len(source_options) < 2:
                raise AttemptStateError(
                    "Frozen examination question has insufficient options"
                )
            if exam.shuffle_options:
                SystemRandom().shuffle(source_options)

            attempt_question = allocation_by_exam_question[question.id]
            for position, option in enumerate(source_options, start=1):
                option_allocations.append(
                    AttemptOptionAllocation(
                        attempt_question_id=attempt_question.id,
                        exam_question_option_id=option.id,
                        source_question_option_id=None,
                        position=position,
                        text=option.text,
                        is_correct=option.is_correct,
                    )
                )

        await AttemptRepository.add_option_allocations(db, option_allocations)
        await AttemptRepository.add_answers(
            db,
            [
                AttemptAnswer(
                    attempt_question_id=allocation.id,
                    is_flagged=False,
                    mutation_sequence=0,
                    answered_at=None,
                )
                for allocation in allocations
            ],
        )

    @classmethod
    async def _allocate_makeup_paper(
        cls,
        db: AsyncSession,
        *,
        attempt: ExamAttempt,
        exam: Exam,
    ) -> None:
        available = await QuestionRepository.list_questions_for_bank(
            db,
            exam.question_bank_id,
            active_only=True,
        )
        original_questions = await ExamRepository.list_exam_questions(db, exam.id)
        original_source_ids = {
            question.source_question_id for question in original_questions
        }

        fresh = [
            question for question in available if question.id not in original_source_ids
        ]
        if len(fresh) < exam.question_count:
            raise AttemptStateError(
                "Question bank does not contain enough unused questions "
                "to generate a fresh makeup paper"
            )

        selected_ids = SystemRandom().sample(
            [question.id for question in fresh],
            exam.question_count,
        )
        selected = await QuestionRepository.list_questions_by_ids(
            db,
            selected_ids,
            active_only=True,
            lock=True,
        )
        by_id = {question.id: question for question in selected}
        if len(by_id) != exam.question_count:
            raise AttemptStateError("One or more makeup questions became unavailable")
        questions = [by_id[question_id] for question_id in selected_ids]

        source_options = await QuestionRepository.list_options_for_questions(
            db,
            selected_ids,
        )
        options_by_question: dict[UUID, list] = defaultdict(list)
        for option in source_options:
            options_by_question[option.question_id].append(option)

        for question in questions:
            cls._validate_source_question_options(
                question,
                options_by_question.get(question.id, []),
            )

        allocations = await AttemptRepository.add_question_allocations(
            db,
            [
                AttemptQuestionAllocation(
                    attempt_id=attempt.id,
                    exam_question_id=None,
                    source_question_id=question.id,
                    source_question_version=question.version,
                    question_type=question.question_type,
                    position=position,
                    prompt=question.prompt,
                    instruction=question.instruction,
                    image_asset_id=question.image_asset_id,
                )
                for position, question in enumerate(questions, start=1)
            ],
        )
        allocation_by_source = {
            allocation.source_question_id: allocation for allocation in allocations
        }

        option_allocations: list[AttemptOptionAllocation] = []
        for question in questions:
            question_options = list(options_by_question[question.id])
            if exam.shuffle_options:
                SystemRandom().shuffle(question_options)
            allocation = allocation_by_source[question.id]
            for position, option in enumerate(question_options, start=1):
                option_allocations.append(
                    AttemptOptionAllocation(
                        attempt_question_id=allocation.id,
                        exam_question_option_id=None,
                        source_question_option_id=option.id,
                        position=position,
                        text=option.text,
                        is_correct=option.is_correct,
                    )
                )

        await AttemptRepository.add_option_allocations(db, option_allocations)
        await AttemptRepository.add_answers(
            db,
            [
                AttemptAnswer(
                    attempt_question_id=allocation.id,
                    is_flagged=False,
                    mutation_sequence=0,
                    answered_at=None,
                )
                for allocation in allocations
            ],
        )

    @classmethod
    async def start_current(
        cls,
        db: AsyncSession,
        *,
        context: StudentSessionContext,
    ) -> AttemptResponse:
        candidate, exam = await cls._get_candidate_and_exam(
            db,
            context=context,
            lock=True,
        )

        existing = await AttemptRepository.get_attempt_by_candidate_id(
            db,
            candidate.id,
            lock=True,
        )
        if existing is not None:
            if existing.status in {
                AttemptStatus.IN_PROGRESS,
                AttemptStatus.INTERRUPTED,
            }:
                return await cls._build_attempt_response(
                    db,
                    attempt=existing,
                    candidate=candidate,
                    exam=exam,
                    is_makeup=context.is_makeup,
                )
            raise AttemptStateError("Candidate examination attempt has already ended")

        now = datetime.now(UTC)
        if context.is_makeup:
            authorization = await cls._validate_makeup_start(
                db,
                context=context,
                candidate=candidate,
                exam=exam,
                now=now,
            )
            late_start_authorization = None
        else:
            authorization = None
            late_start_authorization = await cls._validate_normal_start(
                db,
                candidate=candidate,
                exam=exam,
                now=now,
            )

        attempt = ExamAttempt(
            candidate_id=candidate.id,
            status=AttemptStatus.IN_PROGRESS,
            started_at=now,
            time_limit_seconds=exam.duration_minutes * 60,
            elapsed_seconds=0,
            active_since=now,
            last_heartbeat_at=now,
            last_activity_at=now,
        )

        try:
            attempt = await AttemptRepository.add_attempt(db, attempt)
            if context.is_makeup:
                await cls._allocate_makeup_paper(
                    db,
                    attempt=attempt,
                    exam=exam,
                )
                makeup_authorization = cast(
                    CandidateMakeupAuthorization,
                    authorization,
                )
                makeup_authorization.consumed_at = now
                await CandidateRepository.save_makeup_authorization(
                    db,
                    makeup_authorization,
                )
            else:
                await cls._allocate_normal_paper(
                    db,
                    attempt=attempt,
                    exam=exam,
                )
                if late_start_authorization is not None:
                    late_start_authorization.consumed_at = now
                    await CandidateRepository.save_late_start_authorization(
                        db,
                        late_start_authorization,
                    )

            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise AttemptStateError(
                "Candidate examination attempt could not be started"
            ) from exc
        except Exception:
            await db.rollback()
            raise

        return await cls._build_attempt_response(
            db,
            attempt=attempt,
            candidate=candidate,
            exam=exam,
            is_makeup=context.is_makeup,
        )

    @staticmethod
    async def _active_segment_seconds(
        db: AsyncSession,
        *,
        exam_id: UUID,
        active_since: datetime,
        at: datetime,
    ) -> int:
        total = max(0, int((at - active_since).total_seconds()))
        suspensions = await AttemptRuntimeRepository.list_exam_suspensions(
            db,
            exam_id,
        )
        suspended = 0
        for suspension in suspensions:
            end = suspension.resumed_at or at
            overlap_start = max(active_since, suspension.suspended_at)
            overlap_end = min(at, end)
            if overlap_end > overlap_start:
                suspended += int((overlap_end - overlap_start).total_seconds())
        return max(0, total - suspended)

    @classmethod
    async def remaining_seconds(
        cls,
        db: AsyncSession,
        *,
        attempt: ExamAttempt,
        exam_id: UUID,
        at: datetime | None = None,
    ) -> int:
        at = at or datetime.now(UTC)
        consumed = attempt.elapsed_seconds
        if (
            attempt.status == AttemptStatus.IN_PROGRESS
            and attempt.active_since is not None
        ):
            consumed += await cls._active_segment_seconds(
                db,
                exam_id=exam_id,
                active_since=attempt.active_since,
                at=at,
            )
        return max(0, attempt.time_limit_seconds - consumed)

    @classmethod
    async def _checkpoint_active_segment(
        cls,
        db: AsyncSession,
        *,
        attempt: ExamAttempt,
        exam_id: UUID,
        at: datetime,
    ) -> None:
        if attempt.active_since is None:
            return
        segment = await cls._active_segment_seconds(
            db,
            exam_id=exam_id,
            active_since=attempt.active_since,
            at=at,
        )
        attempt.elapsed_seconds = min(
            attempt.time_limit_seconds,
            attempt.elapsed_seconds + segment,
        )
        attempt.active_since = None

    @classmethod
    async def _build_attempt_response(
        cls,
        db: AsyncSession,
        *,
        attempt: ExamAttempt,
        candidate,
        exam: Exam,
        is_makeup: bool,
    ) -> AttemptResponse:
        questions = await AttemptRepository.list_question_allocations(
            db,
            attempt.id,
        )
        options = await AttemptRepository.list_option_allocations_for_questions(
            db,
            [question.id for question in questions],
        )
        answers = await AttemptRepository.list_answers_for_attempt(db, attempt.id)
        selections = await AttemptRepository.list_selections_for_answers(
            db,
            [answer.id for answer in answers],
        )

        options_by_question: dict[UUID, list] = defaultdict(list)
        for option in options:
            options_by_question[option.attempt_question_id].append(option)
        answer_by_question = {answer.attempt_question_id: answer for answer in answers}
        selected_by_answer: dict[UUID, list[UUID]] = defaultdict(list)
        for selection in selections:
            selected_by_answer[selection.answer_id].append(selection.attempt_option_id)

        remaining = await cls.remaining_seconds(
            db,
            attempt=attempt,
            exam_id=exam.id,
        )

        return AttemptResponse(
            id=attempt.id,
            candidate_id=candidate.id,
            exam_id=exam.id,
            exam_title=exam.title,
            status=attempt.status,
            started_at=attempt.started_at,
            ended_at=attempt.ended_at,
            end_reason=attempt.end_reason,
            time_limit_seconds=attempt.time_limit_seconds,
            remaining_seconds=remaining,
            is_makeup=is_makeup,
            exam_suspended=(exam.status == ExamStatus.SUSPENDED and not is_makeup),
            questions=[
                AttemptQuestionResponse(
                    id=question.id,
                    position=question.position,
                    question_type=question.question_type,
                    prompt=question.prompt,
                    instruction=question.instruction,
                    image_asset_id=question.image_asset_id,
                    options=[
                        AttemptOptionResponse(
                            id=option.id,
                            position=option.position,
                            text=option.text,
                        )
                        for option in options_by_question.get(question.id, [])
                    ],
                    selected_option_ids=(
                        selected_by_answer.get(
                            answer_by_question[question.id].id,
                            [],
                        )
                        if question.id in answer_by_question
                        else []
                    ),
                    is_flagged=(
                        answer_by_question[question.id].is_flagged
                        if question.id in answer_by_question
                        else False
                    ),
                    mutation_sequence=(
                        answer_by_question[question.id].mutation_sequence
                        if question.id in answer_by_question
                        else 0
                    ),
                )
                for question in questions
            ],
        )

    @classmethod
    async def _get_current_attempt(
        cls,
        db: AsyncSession,
        *,
        context: StudentSessionContext,
        lock: bool = False,
    ):
        candidate, exam = await cls._get_candidate_and_exam(
            db,
            context=context,
            lock=lock,
        )
        attempt = await AttemptRepository.get_attempt_by_candidate_id(
            db,
            candidate.id,
            lock=lock,
        )
        if attempt is None:
            raise AttemptStateError("Candidate has not started this examination")
        return attempt, candidate, exam

    @classmethod
    async def get_current(
        cls,
        db: AsyncSession,
        *,
        context: StudentSessionContext,
    ) -> AttemptResponse:
        attempt, candidate, exam = await cls._get_current_attempt(
            db,
            context=context,
            lock=True,
        )

        if attempt.status == AttemptStatus.IN_PROGRESS:
            if not context.is_makeup and exam.status == ExamStatus.CLOSED:
                await cls._submit_locked(
                    db,
                    attempt=attempt,
                    candidate=candidate,
                    exam=exam,
                    end_reason=AttemptEndReason.EXAM_CLOSED,
                    revoke_reason="Examination closed",
                )
            elif (
                await cls.remaining_seconds(
                    db,
                    attempt=attempt,
                    exam_id=exam.id,
                )
                <= 0
            ):
                await cls._submit_locked(
                    db,
                    attempt=attempt,
                    candidate=candidate,
                    exam=exam,
                    end_reason=AttemptEndReason.TIME_EXPIRED,
                    revoke_reason="Examination time expired",
                )

        return await cls._build_attempt_response(
            db,
            attempt=attempt,
            candidate=candidate,
            exam=exam,
            is_makeup=context.is_makeup,
        )

    @classmethod
    async def mutate_answer(
        cls,
        db: AsyncSession,
        *,
        context: StudentSessionContext,
        attempt_question_id: UUID,
        mutation_sequence: int,
        selected_option_ids: list[UUID],
        is_flagged: bool,
    ) -> AttemptAnswerResponse:
        attempt, candidate, exam = await cls._get_current_attempt(
            db,
            context=context,
            lock=True,
        )
        if attempt.status != AttemptStatus.IN_PROGRESS:
            raise AttemptStateError("Attempt is not accepting answers")
        if not context.is_makeup and exam.status == ExamStatus.SUSPENDED:
            raise AttemptStateError("Examination is currently suspended")
        if not context.is_makeup and exam.status != ExamStatus.ACTIVE:
            raise AttemptStateError("Examination is no longer active")

        remaining = await cls.remaining_seconds(
            db,
            attempt=attempt,
            exam_id=exam.id,
        )
        if remaining <= 0:
            await cls._submit_locked(
                db,
                attempt=attempt,
                candidate=candidate,
                exam=exam,
                end_reason=AttemptEndReason.TIME_EXPIRED,
                revoke_reason="Examination time expired",
            )
            raise AttemptStateError("Examination time has expired")

        question = await AttemptRepository.get_question_allocation_by_id(
            db,
            attempt_question_id,
            lock=True,
        )
        if question is None or question.attempt_id != attempt.id:
            raise AttemptStateError("Question does not belong to this attempt")

        answer = await AttemptRepository.get_answer_for_question(
            db,
            question.id,
            lock=True,
        )
        if answer is None:
            raise AttemptStateError("Attempt answer state is missing")

        if mutation_sequence < answer.mutation_sequence:
            raise AttemptStateError("Answer mutation is older than the stored state")

        if mutation_sequence == answer.mutation_sequence:
            current = await AttemptRepository.list_selections_for_answer(
                db,
                answer.id,
            )
            return AttemptAnswerResponse(
                attempt_id=attempt.id,
                attempt_question_id=question.id,
                mutation_sequence=answer.mutation_sequence,
                selected_option_ids=[
                    selection.attempt_option_id for selection in current
                ],
                is_flagged=answer.is_flagged,
                remaining_seconds=remaining,
            )

        options = await AttemptRepository.list_option_allocations(
            db,
            question.id,
        )
        options_by_id = {option.id: option for option in options}
        selected_ids = list(dict.fromkeys(selected_option_ids))
        if any(option_id not in options_by_id for option_id in selected_ids):
            raise AttemptStateError("Selected option does not belong to this question")
        if (
            question.question_type == QuestionType.SINGLE_CHOICE
            and len(selected_ids) > 1
        ):
            raise AttemptStateError(
                "Single-choice question accepts at most one selected option"
            )

        now = datetime.now(UTC)
        try:
            await AttemptRepository.clear_selections_for_answer(db, answer.id)
            if selected_ids:
                await AttemptRepository.add_selections(
                    db,
                    [
                        AttemptAnswerSelection(
                            answer_id=answer.id,
                            attempt_option_id=option_id,
                        )
                        for option_id in selected_ids
                    ],
                )

            answer.is_flagged = is_flagged
            answer.mutation_sequence = mutation_sequence
            answer.answered_at = now if selected_ids else None
            answer.updated_at = now
            attempt.last_activity_at = now

            await AttemptRepository.save_answer(db, answer)
            await AttemptRepository.save_attempt(db, attempt)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise AttemptStateError("Answer could not be saved") from exc

        return AttemptAnswerResponse(
            attempt_id=attempt.id,
            attempt_question_id=question.id,
            mutation_sequence=mutation_sequence,
            selected_option_ids=selected_ids,
            is_flagged=is_flagged,
            remaining_seconds=remaining,
        )

    @classmethod
    async def _revoke_student_sessions(
        cls,
        db: AsyncSession,
        *,
        candidate_id: UUID,
        at: datetime,
        reason: str,
    ) -> None:
        sessions = await StudentAuthRepository.list_unrevoked_sessions_for_candidate(
            db,
            candidate_id,
            lock=True,
        )
        for session in sessions:
            session.revoked_at = at
            session.revocation_reason = reason
            await StudentAuthRepository.save_session(db, session)

    @classmethod
    async def _submit_locked(
        cls,
        db: AsyncSession,
        *,
        attempt: ExamAttempt,
        candidate,
        exam: Exam,
        end_reason: AttemptEndReason,
        revoke_reason: str,
    ):
        if attempt.status == AttemptStatus.SUBMITTED:
            from app.domains.results.repository import ResultRepository

            existing = await ResultRepository.get_result_by_attempt_id(
                db,
                attempt.id,
            )
            if existing is None:
                raise AttemptStateError("Submitted attempt is missing its result")
            return existing
        if attempt.status == AttemptStatus.TERMINATED:
            raise AttemptStateError("Terminated attempt cannot be submitted")

        now = datetime.now(UTC)
        if attempt.status == AttemptStatus.IN_PROGRESS:
            await cls._checkpoint_active_segment(
                db,
                attempt=attempt,
                exam_id=exam.id,
                at=now,
            )

        attempt.status = AttemptStatus.SUBMITTED
        attempt.ended_at = now
        attempt.end_reason = end_reason
        attempt.termination_reason = None
        attempt.active_since = None

        await AttemptRepository.save_attempt(db, attempt)
        result = await ResultService.calculate_for_submitted_attempt(
            db,
            attempt=attempt,
            candidate=candidate,
            exam=exam,
        )
        # A makeup session can advance through approved papers using the
        # waiting-room resolver. Submitted attempts still reject answer changes.
        if not await cls._is_makeup_candidate(db, candidate.id):
            await cls._revoke_student_sessions(
                db,
                candidate_id=candidate.id,
                at=now,
                reason=revoke_reason,
            )
        await db.commit()
        return result

    @classmethod
    async def submit_current(
        cls,
        db: AsyncSession,
        *,
        context: StudentSessionContext,
    ) -> AttemptSubmissionResponse:
        attempt, candidate, exam = await cls._get_current_attempt(
            db,
            context=context,
            lock=True,
        )

        if not context.is_makeup and exam.status == ExamStatus.SUSPENDED:
            raise AttemptStateError(
                "Examination is suspended and cannot be submitted yet"
            )

        subject_name = await cls._exam_subject_name(db, exam)

        end_reason = AttemptEndReason.CANDIDATE_SUBMITTED
        if (
            attempt.status == AttemptStatus.IN_PROGRESS
            and await cls.remaining_seconds(
                db,
                attempt=attempt,
                exam_id=exam.id,
            )
            <= 0
        ):
            end_reason = AttemptEndReason.TIME_EXPIRED
        elif not context.is_makeup and exam.status == ExamStatus.CLOSED:
            end_reason = AttemptEndReason.EXAM_CLOSED

        result = await cls._submit_locked(
            db,
            attempt=attempt,
            candidate=candidate,
            exam=exam,
            end_reason=end_reason,
            revoke_reason="Examination submitted",
        )

        return AttemptSubmissionResponse(
            voided_at=result.voided_at,
            subject_name=subject_name,
            attempt_id=attempt.id,
            status=attempt.status,
            end_reason=attempt.end_reason,
            ended_at=attempt.ended_at,
            result_id=result.id,
            raw_score=result.raw_score,
            raw_max_score=result.raw_max_score,
            percentage=str(result.percentage),
            component_score=str(result.component_score),
            component_maximum_score=str(result.component_maximum_score),
        )

    @staticmethod
    async def _exam_subject_name(db: AsyncSession, exam: Exam) -> str:
        curriculum_subject = await AcademicRepository.get_curriculum_subject_by_id(
            db, exam.curriculum_subject_id
        )
        if curriculum_subject is None:
            raise AttemptStateError("Examination curriculum subject is unavailable")
        subject = await AcademicRepository.get_subject_by_id(
            db, curriculum_subject.subject_id
        )
        if subject is None:
            raise AttemptStateError("Examination subject is unavailable")
        return subject.name

    @staticmethod
    async def _require_operator(
        db: AsyncSession,
        *,
        actor: LocalActor,
        exam_id: UUID,
        admin_only: bool = False,
    ) -> None:
        if not actor.is_active:
            raise AcademicAuthorizationError("Active local actor is required")
        if actor.role == "admin":
            return
        if admin_only or actor.role != "teacher" or actor.weave_membership_id is None:
            raise AcademicAuthorizationError(
                "Administrator access is required for this attempt operation"
            )
        try:
            teacher_id = UUID(actor.weave_membership_id)
        except ValueError as exc:
            raise AcademicAuthorizationError(
                "Teacher has an invalid Weave membership identity"
            ) from exc
        invigilator = await ExamRepository.get_invigilator(
            db,
            exam_id,
            teacher_id,
        )
        if invigilator is None:
            raise AcademicAuthorizationError(
                "Only assigned invigilators may perform this attempt operation"
            )

    @classmethod
    async def interrupt_attempt(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        attempt_id: UUID,
        reason: str,
    ) -> AttemptOperatorResponse:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("reason is required")

        attempt = await AttemptRepository.get_attempt_by_id(db, attempt_id, lock=True)
        if attempt is None:
            raise AttemptStateError("Attempt does not exist")
        candidate = await CandidateRepository.get_candidate_by_id(
            db,
            attempt.candidate_id,
            lock=True,
        )
        if candidate is None:
            raise AttemptStateError("Attempt candidate does not exist")
        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=candidate.exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        await cls._require_operator(db, actor=actor, exam_id=exam.id)

        if attempt.status != AttemptStatus.IN_PROGRESS:
            raise AttemptStateError("Only in-progress attempts can be interrupted")

        now = datetime.now(UTC)
        await cls._checkpoint_active_segment(
            db,
            attempt=attempt,
            exam_id=exam.id,
            at=now,
        )
        attempt.status = AttemptStatus.INTERRUPTED
        remaining = max(0, attempt.time_limit_seconds - attempt.elapsed_seconds)

        interruption = AttemptInterruption(
            attempt_id=attempt.id,
            interrupted_at=now,
            remaining_seconds=remaining,
            reason=normalized_reason,
        )

        try:
            await AttemptRepository.add_interruption(db, interruption)
            await AttemptRepository.save_attempt(db, attempt)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise AttemptStateError("Attempt could not be interrupted") from exc

        return AttemptOperatorResponse(
            attempt_id=attempt.id,
            status=attempt.status,
            remaining_seconds=remaining,
            ended_at=attempt.ended_at,
            end_reason=attempt.end_reason,
        )

    @classmethod
    async def resume_attempt(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        attempt_id: UUID,
        reason: str,
    ) -> AttemptOperatorResponse:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("reason is required")

        attempt = await AttemptRepository.get_attempt_by_id(db, attempt_id, lock=True)
        if attempt is None:
            raise AttemptStateError("Attempt does not exist")
        candidate = await CandidateRepository.get_candidate_by_id(
            db,
            attempt.candidate_id,
            lock=True,
        )
        if candidate is None:
            raise AttemptStateError("Attempt candidate does not exist")
        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=candidate.exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        await cls._require_operator(db, actor=actor, exam_id=exam.id)

        if attempt.status != AttemptStatus.INTERRUPTED:
            raise AttemptStateError("Only interrupted attempts can be resumed")

        is_makeup = await cls._is_makeup_candidate(db, candidate.id)
        if not is_makeup and exam.status != ExamStatus.ACTIVE:
            raise AttemptStateError(
                "Normal examination must be active before attempt resume"
            )

        interruption = await AttemptRepository.get_open_interruption_for_attempt(
            db,
            attempt.id,
            lock=True,
        )
        if interruption is None:
            raise AttemptStateError("Interrupted attempt has no open interruption")

        remaining = max(0, attempt.time_limit_seconds - attempt.elapsed_seconds)
        if remaining <= 0:
            raise AttemptStateError("Attempt has no remaining writing time")

        now = datetime.now(UTC)
        interruption.resumed_at = now
        interruption.resumed_by_actor_id = actor.id
        interruption.resume_reason = normalized_reason
        attempt.status = AttemptStatus.IN_PROGRESS
        attempt.active_since = now
        attempt.last_heartbeat_at = now
        attempt.last_activity_at = now

        try:
            await AttemptRepository.save_interruption(db, interruption)
            await AttemptRepository.save_attempt(db, attempt)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise AttemptStateError("Attempt could not be resumed") from exc

        return AttemptOperatorResponse(
            attempt_id=attempt.id,
            status=attempt.status,
            remaining_seconds=remaining,
            ended_at=attempt.ended_at,
            end_reason=attempt.end_reason,
        )

    @classmethod
    async def terminate_attempt(
        cls,
        db: AsyncSession,
        *,
        actor: LocalActor,
        attempt_id: UUID,
        reason: str,
    ) -> AttemptOperatorResponse:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("reason is required")

        attempt = await AttemptRepository.get_attempt_by_id(db, attempt_id, lock=True)
        if attempt is None:
            raise AttemptStateError("Attempt does not exist")
        candidate = await CandidateRepository.get_candidate_by_id(
            db,
            attempt.candidate_id,
            lock=True,
        )
        if candidate is None:
            raise AttemptStateError("Attempt candidate does not exist")
        exam = await ExamRepository.get_exam_by_id(
            db,
            exam_id=candidate.exam_id,
            lock=True,
        )
        if exam is None:
            raise ExamNotFound("Examination does not exist")

        await cls._require_operator(
            db,
            actor=actor,
            exam_id=exam.id,
            admin_only=True,
        )
        if attempt.status in {AttemptStatus.SUBMITTED, AttemptStatus.TERMINATED}:
            raise AttemptStateError("Attempt has already ended")

        now = datetime.now(UTC)
        if attempt.status == AttemptStatus.IN_PROGRESS:
            await cls._checkpoint_active_segment(
                db,
                attempt=attempt,
                exam_id=exam.id,
                at=now,
            )

        attempt.status = AttemptStatus.TERMINATED
        attempt.active_since = None
        attempt.ended_at = now
        attempt.end_reason = AttemptEndReason.ADMIN_TERMINATED
        attempt.termination_reason = normalized_reason

        interruption = await AttemptRepository.get_open_interruption_for_attempt(
            db,
            attempt.id,
            lock=True,
        )
        if interruption is not None:
            interruption.resumed_at = now
            interruption.resumed_by_actor_id = actor.id
            interruption.resume_reason = "Attempt terminated"
            await AttemptRepository.save_interruption(db, interruption)

        await AttemptRepository.save_attempt(db, attempt)
        await cls._revoke_student_sessions(
            db,
            candidate_id=candidate.id,
            at=now,
            reason="Attempt terminated by administrator",
        )
        await db.commit()

        return AttemptOperatorResponse(
            attempt_id=attempt.id,
            status=attempt.status,
            remaining_seconds=max(
                0,
                attempt.time_limit_seconds - attempt.elapsed_seconds,
            ),
            ended_at=attempt.ended_at,
            end_reason=attempt.end_reason,
        )
