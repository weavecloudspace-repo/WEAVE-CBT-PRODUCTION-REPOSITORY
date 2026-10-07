import os
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.core.exceptions import AcademicAuthorizationError
from app.domains.attempts.models import AttemptStatus
from app.domains.results.models import ResultSyncStatus
from app.domains.results.service import ResultService


class ResultScoringTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_choice_uses_exact_set_matching_and_component_normalization(
        self,
    ):
        attempt_id = uuid4()
        candidate_id = uuid4()
        exam_id = uuid4()
        q1, q2 = uuid4(), uuid4()
        a1, a2 = uuid4(), uuid4()
        q1a, q1b, q2a, q2b, q2c = [uuid4() for _ in range(5)]

        attempt = SimpleNamespace(id=attempt_id, status=AttemptStatus.SUBMITTED)
        candidate = SimpleNamespace(id=candidate_id)
        exam = SimpleNamespace(
            id=exam_id,
            assessment_component_id=uuid4(),
            component_maximum_score=Decimal("10.00"),
            status="active",
            activated_at=datetime.now(UTC),
        )
        questions = [SimpleNamespace(id=q1), SimpleNamespace(id=q2)]
        options = [
            SimpleNamespace(id=q1a, attempt_question_id=q1, is_correct=True),
            SimpleNamespace(id=q1b, attempt_question_id=q1, is_correct=False),
            SimpleNamespace(id=q2a, attempt_question_id=q2, is_correct=True),
            SimpleNamespace(id=q2b, attempt_question_id=q2, is_correct=True),
            SimpleNamespace(id=q2c, attempt_question_id=q2, is_correct=False),
        ]
        answers = [
            SimpleNamespace(id=a1, attempt_question_id=q1),
            SimpleNamespace(id=a2, attempt_question_id=q2),
        ]
        selections = [
            SimpleNamespace(answer_id=a1, attempt_option_id=q1a),
            SimpleNamespace(answer_id=a2, attempt_option_id=q2a),
            SimpleNamespace(answer_id=a2, attempt_option_id=q2c),
        ]

        async def add_result(_db, result):
            result.id = uuid4()
            return result

        with (
            patch(
                "app.domains.results.service.ResultRepository.get_result_by_attempt_id",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.domains.results.service.AttemptRepository.list_question_allocations",
                AsyncMock(return_value=questions),
            ),
            patch(
                "app.domains.results.service.AttemptRepository.list_option_allocations_for_questions",
                AsyncMock(return_value=options),
            ),
            patch(
                "app.domains.results.service.AttemptRepository.list_answers_for_attempt",
                AsyncMock(return_value=answers),
            ),
            patch(
                "app.domains.results.service.AttemptRepository.list_selections_for_answers",
                AsyncMock(return_value=selections),
            ),
            patch(
                "app.domains.results.service.ResultRepository.add_result",
                AsyncMock(side_effect=add_result),
            ),
        ):
            result = await ResultService.calculate_for_submitted_attempt(
                AsyncMock(),
                attempt=attempt,
                candidate=candidate,
                exam=exam,
            )

        self.assertEqual(result.raw_score, 1)
        self.assertEqual(result.raw_max_score, 2)
        self.assertEqual(result.percentage, Decimal("50.00"))
        self.assertEqual(result.component_score, Decimal("5.00"))
        self.assertEqual(result.component_maximum_score, Decimal("10.00"))

    async def test_result_review_rows_delegate_server_search_and_sync_filter(self):
        exam_id = uuid4()
        exam = SimpleNamespace(id=exam_id)
        result = SimpleNamespace(id=uuid4())
        candidate = SimpleNamespace(
            id=uuid4(),
            display_name="David Obi",
            admission_number="JSS2/014",
        )
        actor = SimpleNamespace(is_active=True, role="admin", weave_membership_id=None)
        db = AsyncMock()

        with (
            patch(
                "app.domains.results.service.ExamRepository.get_exam_by_id",
                AsyncMock(return_value=exam),
            ),
            patch(
                "app.domains.results.service.ResultQueryRepository.list_exam_result_rows",
                AsyncMock(return_value=[(result, candidate)]),
            ) as list_rows,
            patch(
                "app.domains.results.service.ResultQueryRepository.count_exam_result_rows",
                AsyncMock(return_value=1),
            ) as count_rows,
        ):
            rows, total = await ResultService.list_exam_result_review_rows(
                db,
                actor=actor,
                exam_id=exam_id,
                search="JSS2/014",
                sync_status=ResultSyncStatus.FAILED,
                offset=50,
                limit=50,
            )

        self.assertEqual(rows, [(result, candidate)])
        self.assertEqual(total, 1)
        list_rows.assert_awaited_once_with(
            db,
            exam_id=exam_id,
            search="JSS2/014",
            sync_status=ResultSyncStatus.FAILED,
            offset=50,
            limit=50,
        )
        count_rows.assert_awaited_once_with(
            db,
            exam_id=exam_id,
            search="JSS2/014",
            sync_status=ResultSyncStatus.FAILED,
        )

    async def test_review_set_feed_is_admin_only(self):
        db = AsyncMock()
        admin = SimpleNamespace(is_active=True, role="admin")
        teacher = SimpleNamespace(is_active=True, role="teacher")
        expected = [{"exam_id": uuid4(), "result_count": 12}]

        with patch(
            "app.domains.results.service.ResultQueryRepository.list_review_sets",
            AsyncMock(return_value=expected),
        ) as list_reviews:
            rows = await ResultService.list_result_review_sets(db, actor=admin)

        self.assertEqual(rows, expected)
        list_reviews.assert_awaited_once_with(db)

        with self.assertRaises(AcademicAuthorizationError):
            await ResultService.list_result_review_sets(db, actor=teacher)


if __name__ == "__main__":
    unittest.main()
