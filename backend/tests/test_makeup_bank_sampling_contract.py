"""Makeup readiness uses the full active bank, not only unseen source questions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.domains.candidates.makeup_review_repository import MakeupReviewRepository
from sqlalchemy.dialects import postgresql


@pytest.mark.asyncio
async def test_makeup_availability_counts_all_active_bank_questions():
    db = SimpleNamespace(scalar=AsyncMock(return_value=20))
    exam = SimpleNamespace(question_bank_id=uuid4())
    total = await MakeupReviewRepository.active_question_count(db, exam)
    assert total == 20
    query = db.scalar.await_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "questions.is_active" in sql
    assert "questions.bank_id" in sql
    assert "exam_questions" not in sql.lower()


def test_makeup_bank_sampling_no_longer_excludes_exam_questions():
    import inspect

    from app.domains.attempts.service import AttemptService

    code = inspect.getsource(AttemptService._allocate_makeup_paper)
    assert "question.id for question in available" in code
    assert "original_source_ids" not in code
