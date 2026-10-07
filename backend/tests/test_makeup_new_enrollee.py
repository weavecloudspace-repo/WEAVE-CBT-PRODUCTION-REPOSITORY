from contextlib import ExitStack
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from app.core.exceptions import AcademicAuthorizationError
from app.domains.candidates.makeup_policy import require_current_makeup_term
from app.domains.candidates.makeup_review_repository import MakeupReviewRepository
from app.domains.candidates.service import CandidateService
from app.domains.exams.execution_models import ExamResultDisposition
from app.domains.results.service import ResultService
from sqlalchemy.dialects import postgresql

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def context():
    session, term = uuid4(), uuid4()
    exam = SimpleNamespace(
        id=uuid4(), session_id=session, term_id=term, status="closed", roster_version=1
    )
    enrollment = SimpleNamespace(
        id=uuid4(),
        student_id=uuid4(),
        class_id=uuid4(),
        admission_number="NEW001",
        first_name="Ada",
        last_name="Obi",
    )
    actor = SimpleNamespace(id=uuid4(), role="admin", is_active=True)
    candidate = SimpleNamespace(id=uuid4(), exam_id=exam.id, status="eligible")

    async def add(db, row):
        row.id = candidate.id
        return row

    with ExitStack() as stack:
        mocks = {}
        for path, value in {
            "AcademicRepository.get_current_session": SimpleNamespace(id=session),
            "AcademicRepository.get_current_term": SimpleNamespace(id=term),
            "ExamRepository.get_exam_by_id": exam,
            "ExamRepository.list_target_classes_for_exam": [],
            "SyncRepository.acquire_apply_lock": None,
            "CandidateService._eligible_enrollments_for_frozen_classes": {
                enrollment.student_id: enrollment
            },
            "CandidateRepository.get_candidate_by_student_id": None,
            "CandidateRepository.get_candidate_by_id": candidate,
            "ExamExecutionRepository.get_control": None,
            "AttemptRepository.get_attempt_by_candidate_id": None,
            "CandidateRepository.get_active_makeup_authorization": None,
            "CandidateRepository.add_makeup_authorization": SimpleNamespace(id=uuid4()),
            "AuditRepository.add_event": None,
        }.items():
            mocks[path] = stack.enter_context(
                patch(
                    "app.domains.candidates.service." + path,
                    AsyncMock(return_value=value),
                )
            )
        mocks["add"] = stack.enter_context(
            patch(
                "app.domains.candidates.service.CandidateRepository.add_candidate",
                AsyncMock(side_effect=add),
            )
        )
        stack.enter_context(
            patch(
                "app.domains.candidates.service.CandidateMakeupAuthorizationResponse.model_validate",
                side_effect=lambda value: value,
            )
        )
        yield SimpleNamespace(db=AsyncMock(), exam=exam, actor=actor, mocks=mocks)


async def invoke(c):
    return await CandidateService.add_makeup_student(
        c.db,
        actor=c.actor,
        exam_id=c.exam.id,
        admission_number=" NEW001 ",
        reason="New enrollee",
    )


async def test_add_student_and_authorization_commit_together(context):
    c = context
    await invoke(c)
    added = c.mocks["add"].await_args.args[1]
    assert added.admission_number == "NEW001"
    assert added.display_name == "Ada Obi"
    assert added.exam_id == c.exam.id
    assert added.roster_version == 1
    c.mocks["CandidateRepository.add_makeup_authorization"].assert_awaited_once()
    c.db.commit.assert_awaited_once()
    c.mocks["AuditRepository.add_event"].assert_awaited_once()


@pytest.mark.parametrize(
    "failure",
    [
        "past_term",
        "active",
        "outside_scope",
        "existing",
        "teacher",
        "voided",
        "authorization_write",
    ],
)
async def test_invalid_add_never_commits(context, failure):
    c = context
    if failure == "past_term":
        c.exam.term_id = uuid4()
    if failure == "active":
        c.exam.status = "active"
    if failure == "outside_scope":
        c.mocks[
            "CandidateService._eligible_enrollments_for_frozen_classes"
        ].return_value = {}
    if failure == "existing":
        c.mocks[
            "CandidateRepository.get_candidate_by_student_id"
        ].return_value = object()
    if failure == "teacher":
        c.actor.role = "teacher"
    if failure == "voided":
        c.mocks["ExamExecutionRepository.get_control"].return_value = SimpleNamespace(
            operation=None, result_disposition="voided"
        )
    if failure == "authorization_write":
        c.mocks[
            "CandidateRepository.add_makeup_authorization"
        ].side_effect = ValueError("write failed")
    with pytest.raises((ValueError, AcademicAuthorizationError)):
        await invoke(c)
    c.db.commit.assert_not_awaited()
    if failure in {"voided", "authorization_write"}:
        c.db.rollback.assert_awaited_once()


async def test_existing_candidate_makeup_approval_also_rejects_past_term(context):
    c = context
    c.exam.term_id = uuid4()
    with pytest.raises(ValueError, match="current academic"):
        await CandidateService.approve_makeup(
            c.db, actor=c.actor, candidate_id=uuid4(), reason="Absent"
        )
    c.db.commit.assert_not_awaited()


async def test_no_current_term_fails_closed(context):
    context.mocks["AcademicRepository.get_current_term"].return_value = None
    with pytest.raises(ValueError, match="current academic"):
        await require_current_makeup_term(context.db, context.exam)


def test_current_period_list_predicate_uses_synchronized_flags():
    sql = str(
        MakeupReviewRepository.overview_query().compile(dialect=postgresql.dialect())
    )
    assert "academic_sessions.is_current IS true" in sql
    assert "academic_terms.is_current IS true" in sql


async def test_new_closed_exam_score_reopens_review_without_committing():
    db = AsyncMock()
    attempt = SimpleNamespace(
        id=uuid4(), status="submitted", started_at=datetime.now(UTC)
    )
    exam = SimpleNamespace(
        id=uuid4(),
        status="closed",
        assessment_component_id=uuid4(),
        component_maximum_score=Decimal(10),
    )
    candidate = SimpleNamespace(id=uuid4())
    control = SimpleNamespace(
        result_disposition=ExamResultDisposition.APPROVED,
        results_decided_at=datetime.now(UTC),
        results_decided_by_actor_id=uuid4(),
        results_decision_reason=None,
    )
    with ExitStack() as stack:
        for path, value in {
            "ResultRepository.get_result_by_attempt_id": None,
            "AttemptRepository.list_question_allocations": [
                SimpleNamespace(id=uuid4())
            ],
            "AttemptRepository.list_option_allocations_for_questions": [],
            "AttemptRepository.list_answers_for_attempt": [],
            "AttemptRepository.list_selections_for_answers": [],
            "ExamExecutionRepository.get_control": control,
            "ExamExecutionRepository.save_control": None,
            "AuditRepository.add_event": None,
        }.items():
            stack.enter_context(
                patch(
                    "app.domains.results.service." + path, AsyncMock(return_value=value)
                )
            )
        add = stack.enter_context(
            patch(
                "app.domains.results.service.ResultRepository.add_result",
                AsyncMock(side_effect=lambda db, row: row),
            )
        )
        await ResultService.calculate_for_submitted_attempt(
            db, attempt=attempt, candidate=candidate, exam=exam
        )
    assert control.result_disposition == ExamResultDisposition.PENDING_REVIEW
    assert control.results_decided_at is None
    assert add.await_args.args[1].sync_status == "pending"
    assert add.await_args.args[1].exam_date == attempt.started_at.date()
    db.commit.assert_not_awaited()
