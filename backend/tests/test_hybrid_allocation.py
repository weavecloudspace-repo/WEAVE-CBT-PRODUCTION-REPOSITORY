"""Regression coverage for WEAVE's hybrid assessment allocation contract."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.core.exceptions import AcademicScopeError
from app.domains.academics.models import AssessmentComponent
from app.domains.academics.schemas import AssessmentComponentResponse
from app.domains.exams.models import Exam
from app.domains.exams.schemas import ExamCreate, ExamResponse, ExamUpdate
from app.domains.exams.score_allocation import resolved_cbt_allocation
from app.integrations.weave.schemas import (
    SYNC_SCHEMA_VERSION,
    WeaveAssessmentComponentSnapshot,
    WeaveResultBulkRequest,
    WeaveResultScore,
)


def _component(*, hybrid: bool, maximum: str = "50") -> SimpleNamespace:
    return SimpleNamespace(maximum_score=Decimal(maximum), is_hybrid=hybrid)


def test_hybrid_projection_is_backward_compatible_without_schema_version_change() -> None:
    assert SYNC_SCHEMA_VERSION == 5
    sample = dict(
        id=uuid4(),
        assessment_scheme_id=uuid4(),
        name="Examination",
        maximum_score=Decimal("50"),
        position=0,
        is_active=True,
    )
    old = WeaveAssessmentComponentSnapshot(**sample)
    hybrid = WeaveAssessmentComponentSnapshot(**sample, is_hybrid=True)
    assert old.is_hybrid is False
    assert hybrid.is_hybrid is True
    assert AssessmentComponentResponse.model_fields["is_hybrid"].default is False
    assert "is_hybrid" in AssessmentComponent.__table__.columns


def test_partial_marks_allowed_only_on_hybrid_components() -> None:
    hybrid = _component(hybrid=True)
    ordinary = _component(hybrid=False)
    assert resolved_cbt_allocation(hybrid, None) == Decimal("50")
    assert resolved_cbt_allocation(hybrid, Decimal("50")) == Decimal("50")
    assert resolved_cbt_allocation(hybrid, Decimal("20")) == Decimal("20")
    assert resolved_cbt_allocation(ordinary, None) == Decimal("50")
    with pytest.raises(AcademicScopeError, match="Only hybrid"):
        resolved_cbt_allocation(ordinary, Decimal("20"))
    for invalid in (Decimal("-1"), Decimal("0"), Decimal("50.01")):
        with pytest.raises(AcademicScopeError):
            resolved_cbt_allocation(hybrid, invalid)


def test_create_and_update_accept_optional_partial_allocation() -> None:
    args = dict(
        session_id=uuid4(),
        term_id=uuid4(),
        curriculum_subject_id=uuid4(),
        assessment_scheme_id=uuid4(),
        assessment_component_id=uuid4(),
        question_bank_id=uuid4(),
        question_count=10,
        title="Mathematics Examination",
        duration_minutes=45,
    )
    assert ExamCreate(**args).cbt_maximum_score is None
    assert ExamCreate(**args, cbt_maximum_score=Decimal("20")).cbt_maximum_score == 20
    assert ExamUpdate(cbt_maximum_score=None).model_fields_set == {"cbt_maximum_score"}
    assert ExamUpdate(cbt_maximum_score=Decimal("20")).cbt_maximum_score == 20
    for invalid in (Decimal("0"), Decimal("-1"), Decimal("101")):
        with pytest.raises(ValidationError):
            ExamCreate(**args, cbt_maximum_score=invalid)
    assert "cbt_maximum_score" in Exam.__table__.columns
    assert "cbt_maximum_score" in ExamResponse.model_fields


def test_result_batch_carries_frozen_allocation_and_zero_marks() -> None:
    common = dict(
        batch_id=uuid4(),
        source_exam_id=uuid4(),
        academic_session_id=uuid4(),
        academic_term_id=uuid4(),
        academic_level_id=uuid4(),
        curriculum_subject_id=uuid4(),
        assessment_component_id=uuid4(),
        exam_date=date(2026, 10, 10),
        scores=[WeaveResultScore(student_id=uuid4(), score=Decimal("0"))],
    )
    payload = WeaveResultBulkRequest(**common, cbt_maximum_score=Decimal("20"))
    assert payload.model_dump(mode="json")["cbt_maximum_score"] == "20"
    assert WeaveResultBulkRequest(**common).cbt_maximum_score is None
