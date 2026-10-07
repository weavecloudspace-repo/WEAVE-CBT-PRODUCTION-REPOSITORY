from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.exams.schemas import ExamCreate, ExamUpdate


def create_payload(**overrides):
    payload = {
        "session_id": uuid4(),
        "term_id": uuid4(),
        "curriculum_subject_id": uuid4(),
        "assessment_scheme_id": uuid4(),
        "assessment_component_id": uuid4(),
        "question_bank_id": uuid4(),
        "question_selection_mode": "random",
        "question_count": 10,
        "title": "English CA1",
        "duration_minutes": 45,
    }
    payload.update(overrides)
    return payload


def test_create_rejects_past_scheduled_start() -> None:
    with pytest.raises(
        ValidationError, match="scheduled_start_at must be in the future"
    ):
        ExamCreate(
            **create_payload(scheduled_start_at=datetime.now(UTC) - timedelta(hours=1))
        )


def test_create_rejects_past_latest_normal_start() -> None:
    with pytest.raises(
        ValidationError, match="latest_normal_start_at must be in the future"
    ):
        ExamCreate(
            **create_payload(
                scheduled_start_at=datetime.now(UTC) + timedelta(hours=1),
                latest_normal_start_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )


def test_create_rejects_naive_schedule_timestamp() -> None:
    with pytest.raises(
        ValidationError, match="scheduled_start_at must include a timezone"
    ):
        ExamCreate(**create_payload(scheduled_start_at=datetime.now(UTC).replace(tzinfo=None)))


def test_create_rejects_latest_start_without_scheduled_start() -> None:
    with pytest.raises(
        ValidationError, match="latest_normal_start_at requires scheduled_start_at"
    ):
        ExamCreate(
            **create_payload(
                latest_normal_start_at=datetime.now(UTC) + timedelta(hours=2),
            )
        )


def test_create_allows_unscheduled_draft() -> None:
    exam = ExamCreate(**create_payload())
    assert exam.scheduled_start_at is None
    assert exam.latest_normal_start_at is None


def test_create_allows_future_schedule_window() -> None:
    scheduled = datetime.now(UTC) + timedelta(hours=2)
    latest = scheduled + timedelta(minutes=20)
    exam = ExamCreate(
        **create_payload(
            scheduled_start_at=scheduled,
            latest_normal_start_at=latest,
        )
    )
    assert exam.scheduled_start_at == scheduled
    assert exam.latest_normal_start_at == latest


def test_update_rejects_past_scheduled_start() -> None:
    with pytest.raises(
        ValidationError, match="scheduled_start_at must be in the future"
    ):
        ExamUpdate(
            expected_authoring_version=2,
            scheduled_start_at=datetime.now(UTC) - timedelta(minutes=1),
        )


def test_update_rejects_explicit_latest_start_without_scheduled_start() -> None:
    with pytest.raises(
        ValidationError, match="latest_normal_start_at requires scheduled_start_at"
    ):
        ExamUpdate(
            expected_authoring_version=2,
            scheduled_start_at=None,
            latest_normal_start_at=datetime.now(UTC) + timedelta(hours=2),
        )


def test_update_allows_clearing_schedule() -> None:
    update = ExamUpdate(
        expected_authoring_version=2,
        scheduled_start_at=None,
        latest_normal_start_at=None,
    )
    assert update.scheduled_start_at is None
    assert update.latest_normal_start_at is None


@pytest.mark.parametrize("offset_seconds", [0, -60])
def test_create_rejects_zero_or_negative_normal_entry_window(offset_seconds) -> None:
    scheduled = datetime.now(UTC) + timedelta(hours=2)
    with pytest.raises(ValidationError, match="Normal entry deadline must be later"):
        ExamCreate(
            **create_payload(
                scheduled_start_at=scheduled,
                latest_normal_start_at=scheduled + timedelta(seconds=offset_seconds),
            )
        )


def test_update_rejects_equal_start_and_deadline() -> None:
    scheduled = datetime.now(UTC) + timedelta(hours=2)
    with pytest.raises(ValidationError, match="Equal times leave no time"):
        ExamUpdate(scheduled_start_at=scheduled, latest_normal_start_at=scheduled)


def test_create_accepts_no_deadline_and_positive_entry_window() -> None:
    scheduled = datetime.now(UTC) + timedelta(hours=2)
    assert (
        ExamCreate(
            **create_payload(scheduled_start_at=scheduled)
        ).latest_normal_start_at
        is None
    )
    assert (
        ExamCreate(
            **create_payload(
                scheduled_start_at=scheduled,
                latest_normal_start_at=scheduled + timedelta(seconds=1),
            )
        ).latest_normal_start_at
        > scheduled
    )
