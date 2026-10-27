"""Regressions for second and successive authorized CBT examination sittings."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.domains.attempts.models import AttemptStatus
from app.domains.attempts.repository import AttemptRepository
from app.domains.attempts.service import AttemptService, AttemptStateError
from app.domains.candidates.repository import CandidateRepository
from app.domains.results.repository import ResultRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("previous_number", [1, 2])
async def test_voided_historical_attempt_starts_new_authorized_sitting(previous_number):
    db = AsyncMock()
    candidate = SimpleNamespace(id=uuid4())
    exam = SimpleNamespace(duration_minutes=60)
    original = SimpleNamespace(
        id=uuid4(),
        candidate_id=candidate.id,
        attempt_number=previous_number,
        status=AttemptStatus.SUBMITTED,
        ended_at=datetime.now(UTC),
    )
    authorization = SimpleNamespace(id=uuid4(), consumed_at=None)
    context = SimpleNamespace(
        is_makeup=True,
        makeup_authorization_id=authorization.id,
    )
    new_attempts = []

    async def save_attempt(_db, attempt):
        attempt.id = uuid4()
        new_attempts.append(attempt)
        return attempt

    response = object()
    with (
        patch.object(
            AttemptService,
            "_get_candidate_and_exam",
            AsyncMock(return_value=(candidate, exam)),
        ),
        patch.object(
            AttemptRepository,
            "get_attempt_by_candidate_id",
            AsyncMock(return_value=original),
        ),
        patch.object(
            ResultRepository,
            "get_result_by_attempt_id",
            AsyncMock(return_value=SimpleNamespace(voided_at=datetime.now(UTC))),
        ),
        patch.object(
            AttemptService,
            "_validate_makeup_start",
            AsyncMock(return_value=authorization),
        ),
        patch.object(
            AttemptRepository,
            "add_attempt",
            AsyncMock(side_effect=save_attempt),
        ),
        patch.object(AttemptService, "_allocate_makeup_paper", AsyncMock()) as allocate,
        patch.object(
            CandidateRepository, "save_makeup_authorization", AsyncMock()
        ) as save_authorization,
        patch.object(
            AttemptService,
            "_build_attempt_response",
            AsyncMock(return_value=response),
        ),
    ):
        actual = await AttemptService.start_current(db, context=context)

    assert actual is response
    assert len(new_attempts) == 1
    assert new_attempts[0].candidate_id == candidate.id
    assert new_attempts[0].attempt_number == previous_number + 1
    assert new_attempts[0].makeup_authorization_id == authorization.id
    assert new_attempts[0].status == AttemptStatus.IN_PROGRESS
    assert original.status == AttemptStatus.SUBMITTED
    assert original.attempt_number == previous_number
    assert authorization.consumed_at is not None
    allocate.assert_awaited_once()
    save_authorization.assert_awaited_once()
    db.commit.assert_awaited_once()


async def test_unvoided_historical_result_rejects_another_sitting():
    db = AsyncMock()
    candidate = SimpleNamespace(id=uuid4())
    original = SimpleNamespace(
        id=uuid4(),
        attempt_number=1,
        status=AttemptStatus.SUBMITTED,
    )
    with (
        patch.object(
            AttemptService,
            "_get_candidate_and_exam",
            AsyncMock(return_value=(candidate, SimpleNamespace(duration_minutes=60))),
        ),
        patch.object(
            AttemptRepository,
            "get_attempt_by_candidate_id",
            AsyncMock(return_value=original),
        ),
        patch.object(
            ResultRepository,
            "get_result_by_attempt_id",
            AsyncMock(return_value=SimpleNamespace(voided_at=None)),
        ),
        patch.object(AttemptRepository, "add_attempt", AsyncMock()) as add,
        pytest.raises(AttemptStateError, match="individually voided previous result"),
    ):
        await AttemptService.start_current(
            db,
            context=SimpleNamespace(is_makeup=True, makeup_authorization_id=uuid4()),
        )
    add.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("is_makeup", [True, False])
async def test_replacement_attempt_rejects_original_or_stale_student_session(is_makeup):
    db = AsyncMock()
    candidate = SimpleNamespace(id=uuid4())
    attempt = SimpleNamespace(id=uuid4(), makeup_authorization_id=uuid4())
    context = SimpleNamespace(
        is_makeup=is_makeup,
        makeup_authorization_id=uuid4() if is_makeup else None,
    )
    with (
        patch.object(
            AttemptService,
            "_get_candidate_and_exam",
            AsyncMock(return_value=(candidate, SimpleNamespace())),
        ),
        patch.object(
            AttemptRepository,
            "get_attempt_by_candidate_id",
            AsyncMock(return_value=attempt),
        ),
        pytest.raises(AttemptStateError, match="[Mm]akeup"),
    ):
        await AttemptService._get_current_attempt(db, context=context)


async def test_replacement_attempt_accepts_exact_makeup_authorization():
    db = AsyncMock()
    candidate = SimpleNamespace(id=uuid4())
    exam = SimpleNamespace(id=uuid4())
    authorization_id = uuid4()
    attempt = SimpleNamespace(id=uuid4(), makeup_authorization_id=authorization_id)
    context = SimpleNamespace(is_makeup=True, makeup_authorization_id=authorization_id)
    with (
        patch.object(
            AttemptService,
            "_get_candidate_and_exam",
            AsyncMock(return_value=(candidate, exam)),
        ),
        patch.object(
            AttemptRepository,
            "get_attempt_by_candidate_id",
            AsyncMock(return_value=attempt),
        ),
    ):
        (
            found_attempt,
            found_candidate,
            found_exam,
        ) = await AttemptService._get_current_attempt(db, context=context)
    assert found_attempt is attempt
    assert found_candidate is candidate
    assert found_exam is exam
