from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.core.exceptions import AcademicAuthorizationError
from app.domains.attempts.models import AttemptStatus
from app.domains.attempts.service import AttemptService
from app.domains.candidates.makeup_review_repository import MakeupReviewRepository
from app.domains.candidates.makeup_review_service import MakeupReviewService
from app.domains.candidates.models import CandidateStatus
from app.domains.exams.models import ExamStatus

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize(
    "blockers,fresh,available",
    [([], 20, True), (["English"], 20, False), ([], 19, False)],
)
async def test_makeup_readiness_and_candidate_permissions(blockers, fresh, available):
    exam = SimpleNamespace(id=uuid4(), status=ExamStatus.CLOSED, question_count=20)
    candidate = SimpleNamespace(
        id=uuid4(),
        display_name="Ada",
        admission_number="001",
        status=CandidateStatus.ELIGIBLE,
    )
    approved = SimpleNamespace(
        id=uuid4(), reason="Absent", consumed_at=None, revoked_at=None
    )
    now = datetime.now(UTC)
    attempt = SimpleNamespace(
        status=AttemptStatus.IN_PROGRESS,
        elapsed_seconds=0,
        active_since=now - timedelta(minutes=10),
        time_limit_seconds=3600,
    )
    rows = [
        (candidate, None, None, None, "JSS1 A"),
        (candidate, approved, None, None, "JSS1 A"),
        (candidate, approved, attempt, None, "JSS1 A"),
    ]
    with (
        patch("app.domains.candidates.makeup_review_service.require_current_makeup_term", AsyncMock()),
        patch(
            "app.domains.candidates.makeup_review_service.ExamRepository.get_exam_by_id",
            AsyncMock(return_value=exam),
        ),
        patch.object(
            MakeupReviewRepository, "blockers", AsyncMock(return_value=blockers)
        ),
        patch.object(
            MakeupReviewRepository,
            "fresh_question_count",
            AsyncMock(return_value=fresh),
        ),
        patch.object(
            MakeupReviewRepository, "candidates", AsyncMock(return_value=(rows, 3))
        ),
        patch(
            "app.domains.candidates.makeup_review_service.AttemptRuntimeRepository.list_exam_suspensions",
            AsyncMock(return_value=[]),
        ),
    ):
        result = await MakeupReviewService.detail(
            AsyncMock(),
            actor=SimpleNamespace(role="admin", is_active=True),
            exam_id=exam.id,
            offset=0,
            limit=50,
        )
    assert result["available"] is available
    missed, authorized, writing = result["candidates"]
    assert missed["can_approve"] and not missed["can_revoke"]
    assert authorized["can_revoke"] and not authorized["can_approve"]
    assert writing["state"] == "writing"
    assert not writing["can_approve"] and not writing["can_revoke"]


async def test_makeup_review_is_admin_only():
    with pytest.raises(AcademicAuthorizationError):
        await MakeupReviewService.overview(
            AsyncMock(), actor=SimpleNamespace(role="teacher", is_active=True)
        )


def test_candidate_projection_compiles_for_postgres():
    sql = str(
        MakeupReviewRepository.candidate_query(uuid4()).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "academic_classes.display_name" in sql
    assert "ORDER BY" in sql
    assert "exam_attempts" in sql
    overview = str(
        MakeupReviewRepository.overview_query().compile(dialect=postgresql.dialect())
    )
    assert "GROUP BY" in overview
    assert "academic_classes.display_name" not in overview


@pytest.mark.parametrize("is_makeup", [True, False])
async def test_makeup_submission_preserves_session_for_next_approved_paper(is_makeup):
    db = AsyncMock()
    attempt = SimpleNamespace(
        id=uuid4(), status=AttemptStatus.IN_PROGRESS, active_since=datetime.now(UTC)
    )
    candidate = SimpleNamespace(id=uuid4())
    exam = SimpleNamespace(id=uuid4())
    with (
        patch.object(AttemptService, "_checkpoint_active_segment", AsyncMock()),
        patch.object(
            AttemptService, "_is_makeup_candidate", AsyncMock(return_value=is_makeup)
        ),
        patch.object(AttemptService, "_revoke_student_sessions", AsyncMock()) as revoke,
        patch(
            "app.domains.attempts.service.AttemptRepository.save_attempt", AsyncMock()
        ),
        patch(
            "app.domains.attempts.service.ResultService.calculate_for_submitted_attempt",
            AsyncMock(),
        ),
    ):
        await AttemptService._submit_locked(
            db,
            attempt=attempt,
            candidate=candidate,
            exam=exam,
            end_reason="candidate_submitted",
            revoke_reason="Submitted",
        )
    assert attempt.status == AttemptStatus.SUBMITTED
    if is_makeup:
        revoke.assert_not_awaited()
    else:
        revoke.assert_awaited_once()
