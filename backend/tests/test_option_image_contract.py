from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.attempts.models import AttemptOptionAllocation
from app.domains.attempts.router import student_router
from app.domains.attempts.schemas import AttemptOptionResponse
from app.domains.exams.models import ExamQuestionOption
from app.domains.questions.models import QuestionOption
from app.domains.questions.router import router as question_router
from app.domains.questions.schemas import QuestionOptionCreate


def test_question_option_accepts_image_without_text() -> None:
    asset_id = uuid4()

    option = QuestionOptionCreate(image_asset_id=asset_id, is_correct=True)

    assert option.text is None
    assert option.image_asset_id == asset_id


def test_question_option_rejects_empty_content() -> None:
    with pytest.raises(ValidationError):
        QuestionOptionCreate(is_correct=False)


def test_option_snapshot_models_include_nullable_media_content() -> None:
    for model in (QuestionOption, ExamQuestionOption, AttemptOptionAllocation):
        assert model.__table__.c.text.nullable is True
        assert model.__table__.c.image_asset_id.nullable is True


def test_attempt_option_response_exposes_media_id() -> None:
    option = AttemptOptionResponse(
        id=uuid4(),
        position=1,
        text=None,
        image_asset_id=uuid4(),
    )

    assert option.image_asset_id is not None


def test_question_and_student_option_image_routes_are_registered() -> None:
    question_paths = {route.path for route in question_router.routes}
    student_paths = {route.path for route in student_router.routes}

    assert "/questions/{question_id}/options/{option_id}/image" in question_paths
    assert (
        "/student/attempts/current/questions/{attempt_question_id}/options/"
        "{attempt_option_id}/image"
    ) in student_paths
    assert (
        "/student/attempts/current/questions/{attempt_question_id}/image"
        in student_paths
    )
