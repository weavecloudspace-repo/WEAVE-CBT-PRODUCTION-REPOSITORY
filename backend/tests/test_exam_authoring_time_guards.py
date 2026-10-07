from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.domains.exams.exceptions import ExamStateError
from app.domains.exams.service import ExamService


def require_schedule(
    scheduled_start_at,
    latest_normal_start_at=None,
    *,
    require_scheduled=False,
    action="saving changes to this draft",
):
    ExamService._require_authoring_schedule(
        scheduled_start_at=scheduled_start_at,
        latest_normal_start_at=latest_normal_start_at,
        require_scheduled=require_scheduled,
        action=action,
    )


def test_unscheduled_draft_remains_valid_while_authoring() -> None:
    require_schedule(None)


def test_submission_requires_a_schedule() -> None:
    with pytest.raises(
        ExamStateError, match="Schedule the examination before submitting"
    ):
        require_schedule(
            None,
            require_scheduled=True,
            action="submitting it for review",
        )


def test_elapsed_draft_schedule_blocks_save() -> None:
    with pytest.raises(ExamStateError, match="scheduled examination time has elapsed"):
        require_schedule(datetime.now(UTC) - timedelta(minutes=1))


def test_elapsed_submitted_schedule_blocks_seal() -> None:
    with pytest.raises(
        ExamStateError, match="Reschedule the examination before sealing"
    ):
        require_schedule(
            datetime.now(UTC) - timedelta(minutes=1),
            require_scheduled=True,
            action="sealing it",
        )


def test_future_authoring_schedule_is_valid() -> None:
    scheduled = datetime.now(UTC) + timedelta(hours=2)
    require_schedule(
        scheduled,
        scheduled + timedelta(minutes=20),
        require_scheduled=True,
        action="submitting it for review",
    )


def test_latest_normal_start_requires_scheduled_start() -> None:
    with pytest.raises(ExamStateError, match="cannot exist without a scheduled start"):
        require_schedule(None, datetime.now(UTC) + timedelta(hours=2))


def test_latest_normal_start_cannot_precede_scheduled_start() -> None:
    scheduled = datetime.now(UTC) + timedelta(hours=2)
    with pytest.raises(ExamStateError, match="must be later"):
        require_schedule(scheduled, scheduled - timedelta(minutes=10))


def test_persisted_equal_deadline_cannot_pass_authoring_boundaries() -> None:
    scheduled = datetime.now(UTC) + timedelta(hours=2)
    with pytest.raises(ExamStateError, match="Equal times leave no time"):
        require_schedule(scheduled, scheduled)
