from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.domains.questions.ai_repository import QuestionAIRepository
from app.domains.questions.ai_schemas import QuestionAIBulkSaveRequest
from app.domains.questions.ai_service import QuestionAIService
from app.domains.questions.exceptions import QuestionConflictError
from app.domains.questions.repository import QuestionRepository


def _payload(draft_id):
    return QuestionAIBulkSaveRequest.model_validate(
        {
            "draft_id": str(draft_id),
            "questions": [
                {
                    "question_type": "single_choice",
                    "prompt": "Capital of Nigeria?",
                    "options": [
                        {"text": "Abuja", "is_correct": True},
                        {"text": "Lagos", "is_correct": False},
                    ],
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_persist_reviewed_questions_replays_existing_draft_without_reinserting() -> (
    None
):
    service = QuestionAIService()
    actor = SimpleNamespace(id=uuid4(), role="teacher", is_active=True)
    bank_id = uuid4()
    draft_id = uuid4()
    payload = _payload(draft_id)
    request_hash = service._persistence_request_hash(bank_id=bank_id, payload=payload)
    batch = SimpleNamespace(
        id=uuid4(),
        draft_id=draft_id,
        actor_id=actor.id,
        bank_id=bank_id,
        request_hash=request_hash,
    )
    questions = [SimpleNamespace(id=uuid4())]

    with (
        patch.object(
            QuestionAIRepository,
            "get_import_batch_by_draft_id",
            new=AsyncMock(return_value=batch),
        ),
        patch.object(
            QuestionAIRepository,
            "list_questions_for_import_batch",
            new=AsyncMock(return_value=questions),
        ),
        patch.object(
            QuestionRepository,
            "add_question",
            new=AsyncMock(),
        ) as add_question,
    ):
        result = await service.persist_reviewed_questions(
            object(),
            actor=actor,
            bank_id=bank_id,
            payload=payload,
        )

    assert result == questions
    add_question.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_reviewed_questions_rejects_changed_payload_for_same_draft() -> (
    None
):
    service = QuestionAIService()
    actor = SimpleNamespace(id=uuid4(), role="admin", is_active=True)
    bank_id = uuid4()
    draft_id = uuid4()
    payload = _payload(draft_id)
    batch = SimpleNamespace(
        id=uuid4(),
        draft_id=draft_id,
        actor_id=actor.id,
        bank_id=bank_id,
        request_hash="0" * 64,
    )

    with (
        patch.object(
            QuestionAIRepository,
            "get_import_batch_by_draft_id",
            new=AsyncMock(return_value=batch),
        ),
        pytest.raises(QuestionConflictError, match="already persisted"),
    ):
        await service.persist_reviewed_questions(
            object(),
            actor=actor,
            bank_id=bank_id,
            payload=payload,
        )
