"""Local rollback safety and Cloud reconciliation contract regressions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.domains.exams.exceptions import ExamStateError
from app.domains.results.models import ResultSyncStatus
from app.domains.results.rollback_schemas import (
    CloudRollbackItem,
    CloudRollbackResponse,
)
from app.domains.results.rollback_service import ResultRollbackService

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_rollback_statuses_stay_distinct_from_sync_retries():
    assert ResultSyncStatus.ROLLBACK_PENDING not in {
        ResultSyncStatus.PENDING,
        ResultSyncStatus.FAILED,
    }
    assert ResultSyncStatus.ROLLED_BACK not in {
        ResultSyncStatus.PENDING,
        ResultSyncStatus.FAILED,
    }


def test_cloud_rollback_acknowledgment_validates_all_members():
    student = uuid4()
    response = CloudRollbackResponse(
        operation_id=uuid4(),
        source_batch_id=uuid4(),
        status="partially_completed",
        target_count=2,
        completed_count=1,
        rejected_count=1,
        items=[
            CloudRollbackItem(student_id=student, status="completed"),
            CloudRollbackItem(
                student_id=uuid4(), status="rejected", error_code="RESULT_NOT_DRAFT"
            ),
        ],
    )
    assert response.items[1].error_code == "RESULT_NOT_DRAFT"


@pytest.mark.parametrize("reason", ["", "a", "   "])
def test_rollback_requires_meaningful_reason(reason):
    with pytest.raises(ExamStateError):
        ResultRollbackService._reason(reason)


async def test_admin_only_rollback():
    with pytest.raises(Exception, match="administrator"):
        await ResultRollbackService.begin(
            AsyncMock(),
            actor=SimpleNamespace(role="teacher", is_active=True),
            reason="Wrong answer key",
            result_id=uuid4(),
        )
