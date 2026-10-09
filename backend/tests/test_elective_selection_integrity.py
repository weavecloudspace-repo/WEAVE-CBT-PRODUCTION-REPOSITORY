from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domains.academics.electives import (
    ElectiveEligibilityService,
    ElectiveProjectionRepository,
)
from app.domains.candidates.service import CandidateService
from app.domains.exams.exceptions import ExamStateError
from app.domains.exams.models import ExamRosterStatus, ExamStatus
from app.domains.exams.timetable_service import (
    ExamTimetableService,
    _PlannedNode,
    _ScopeWindow,
)
from app.domains.sync.service import BOOTSTRAP_SECTIONS, ENTITY_MODELS, ENTITY_SCHEMAS
from app.integrations.weave.schemas import (
    WeaveAcademicBootstrap,
    WeaveCurriculumSubjectSnapshot,
    WeaveStudentElectiveSelectionSnapshot,
)


@pytest.mark.asyncio
async def test_grouped_elective_filters_enrollments_to_authoritative_choices() -> None:
    curriculum_subject_id = uuid4()
    group_id = uuid4()
    selected_student_id = uuid4()
    unselected_student_id = uuid4()
    subject = SimpleNamespace(
        id=curriculum_subject_id,
        is_active=True,
        is_elective=True,
        elective_group_id=group_id,
    )
    enrollments = [
        SimpleNamespace(student_id=selected_student_id),
        SimpleNamespace(student_id=unselected_student_id),
    ]

    with (
        patch(
            "app.domains.academics.electives.AcademicRepository.get_curriculum_subject_by_id",
            new=AsyncMock(return_value=subject),
        ),
        patch.object(
            ElectiveProjectionRepository,
            "selected_student_ids",
            new=AsyncMock(return_value={selected_student_id}),
        ) as selected,
    ):
        result = await ElectiveEligibilityService.filter_enrollments(
            SimpleNamespace(),
            curriculum_subject_id=curriculum_subject_id,
            enrollments=enrollments,
        )

    assert [row.student_id for row in result] == [selected_student_id]
    selected.assert_awaited_once()


@pytest.mark.asyncio
async def test_compulsory_subject_preserves_existing_class_roster_behavior() -> None:
    curriculum_subject_id = uuid4()
    subject = SimpleNamespace(
        id=curriculum_subject_id,
        is_active=True,
        is_elective=False,
        elective_group_id=None,
    )
    enrollments = [
        SimpleNamespace(student_id=uuid4()),
        SimpleNamespace(student_id=uuid4()),
    ]

    with (
        patch(
            "app.domains.academics.electives.AcademicRepository.get_curriculum_subject_by_id",
            new=AsyncMock(return_value=subject),
        ),
        patch.object(
            ElectiveProjectionRepository,
            "selected_student_ids",
            new=AsyncMock(),
        ) as selected,
    ):
        result = await ElectiveEligibilityService.filter_enrollments(
            SimpleNamespace(),
            curriculum_subject_id=curriculum_subject_id,
            enrollments=enrollments,
        )

    assert result == enrollments
    selected.assert_not_awaited()


@pytest.mark.asyncio
async def test_candidate_roster_intersects_frozen_classes_with_elective_choice() -> (
    None
):
    class_id = uuid4()
    session_id = uuid4()
    curriculum_subject_id = uuid4()
    selected = SimpleNamespace(
        id=uuid4(),
        student_id=uuid4(),
        class_id=class_id,
        academic_session_id=session_id,
    )
    unselected = SimpleNamespace(
        id=uuid4(),
        student_id=uuid4(),
        class_id=class_id,
        academic_session_id=session_id,
    )
    exam = SimpleNamespace(
        session_id=session_id, curriculum_subject_id=curriculum_subject_id
    )

    with (
        patch(
            "app.domains.candidates.service.AcademicRepository.list_current_enrollments_for_classes",
            new=AsyncMock(return_value=[selected, unselected]),
        ) as enrollments,
        patch(
            "app.domains.candidates.service.ElectiveEligibilityService.filter_enrollments",
            new=AsyncMock(return_value=[selected]),
        ) as elective_filter,
    ):
        result = await CandidateService._eligible_enrollments_for_frozen_classes(
            SimpleNamespace(),
            exam=exam,
            target_classes=[SimpleNamespace(class_id=class_id)],
        )

    assert result == {selected.student_id: selected}
    enrollments.assert_awaited_once_with(
        ANY, [class_id], academic_session_id=session_id
    )
    elective_filter.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_sealed_roster_uses_current_projection_for_timetable_audience() -> (
    None
):
    class_id = uuid4()
    current_student_id = uuid4()
    exam = SimpleNamespace(
        id=uuid4(),
        status=ExamStatus.SEALED,
        roster_status=ExamRosterStatus.STALE,
        curriculum_subject_id=uuid4(),
        term_id=uuid4(),
        session_id=uuid4(),
    )
    db = SimpleNamespace(execute=AsyncMock())

    with (
        patch.object(
            ExamTimetableService,
            "_exam_delivery_class_ids",
            new=AsyncMock(return_value={class_id}),
        ),
        patch.object(
            ElectiveEligibilityService,
            "projected_student_ids_for_classes",
            new=AsyncMock(return_value={current_student_id}),
        ) as projected,
    ):
        audience = await ExamTimetableService._projected_audience_ids(db, exam=exam)

    assert audience == {current_student_id}
    db.execute.assert_not_awaited()
    projected.assert_awaited_once_with(
        db,
        curriculum_subject_id=exam.curriculum_subject_id,
        class_ids=(class_id,),
        academic_session_id=exam.session_id,
    )


@pytest.mark.asyncio
async def test_ready_sealed_roster_keeps_frozen_candidate_audience() -> None:
    frozen_student_id = uuid4()
    exam = SimpleNamespace(
        id=uuid4(),
        status=ExamStatus.SEALED,
        roster_status=ExamRosterStatus.READY,
        curriculum_subject_id=uuid4(),
        term_id=uuid4(),
        session_id=uuid4(),
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [frozen_student_id]
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    with (
        patch.object(
            ExamTimetableService, "_exam_delivery_class_ids", new=AsyncMock()
        ) as class_scope,
        patch.object(
            ElectiveEligibilityService,
            "projected_student_ids_for_classes",
            new=AsyncMock(),
        ) as projected,
    ):
        audience = await ExamTimetableService._projected_audience_ids(db, exam=exam)

    assert audience == {frozen_student_id}
    db.execute.assert_awaited_once()
    class_scope.assert_not_awaited()
    projected.assert_not_awaited()


@pytest.mark.asyncio
async def test_activation_scope_rechecks_stale_sibling_against_current_selection() -> (
    None
):
    shared_student_id = uuid4()
    frozen_class_id = uuid4()
    now = datetime.now(UTC)
    source = SimpleNamespace(
        id=uuid4(),
        title="French",
        status=ExamStatus.SEALED,
        roster_status=ExamRosterStatus.READY,
        curriculum_subject_id=uuid4(),
        term_id=uuid4(),
        session_id=uuid4(),
        scheduled_start_at=now,
        latest_normal_start_at=now,
        duration_minutes=60,
    )
    sibling = SimpleNamespace(
        id=uuid4(),
        title="Music",
        status=ExamStatus.SEALED,
        roster_status=ExamRosterStatus.STALE,
        curriculum_subject_id=uuid4(),
        term_id=source.term_id,
        session_id=source.session_id,
        scheduled_start_at=now,
        latest_normal_start_at=now,
        duration_minutes=60,
    )
    candidate_rows = MagicMock()
    candidate_rows.all.return_value = [(source.id, shared_student_id)]
    db = SimpleNamespace(execute=AsyncMock(return_value=candidate_rows))

    with (
        patch.object(
            ExamTimetableService,
            "_exam_delivery_class_ids",
            new=AsyncMock(return_value={frozen_class_id}),
        ),
        patch.object(
            ElectiveEligibilityService,
            "projected_student_ids_for_classes",
            new=AsyncMock(return_value={shared_student_id}),
        ),
    ):
        scopes = await ExamTimetableService._scope_map_for_exams(db, [source, sibling])

    assert scopes[source.id] == frozenset({shared_student_id})
    assert scopes[sibling.id] == frozenset({shared_student_id})

    impacts = ExamTimetableService._cascade_planned_windows(
        source_window=_ScopeWindow(
            exam_id=source.id,
            title=source.title,
            class_ids=scopes[source.id],
            start_at=now,
            end_at=now + timedelta(minutes=60),
        ),
        fixed_windows=[],
        planned_nodes=[
            _PlannedNode(
                exam_id=sibling.id,
                title=sibling.title,
                status=sibling.status,
                class_ids=scopes[sibling.id],
                scheduled_start_at=now,
                window_duration=timedelta(minutes=60),
            )
        ],
        checked_at=now,
    )

    assert len(impacts) == 1
    assert impacts[0].exam_id == sibling.id
    assert source.id in impacts[0].blocked_by_exam_ids


@pytest.mark.asyncio
async def test_planning_allows_disjoint_grouped_electives_in_same_class_slot() -> None:
    now = datetime.now(UTC)
    class_id = uuid4()
    proposed_subject_id = uuid4()
    existing_exam = SimpleNamespace(
        id=uuid4(),
        title="French",
        session_id=uuid4(),
        term_id=uuid4(),
        curriculum_subject_id=uuid4(),
        status=ExamStatus.SUBMITTED,
        scheduled_start_at=now,
        latest_normal_start_at=now,
        duration_minutes=60,
    )

    with (
        patch.object(
            ExamTimetableService, "level_id", new=AsyncMock(return_value=uuid4())
        ),
        patch.object(ExamTimetableService, "acquire_level_lock", new=AsyncMock()),
        patch.object(
            ExamTimetableService,
            "_derived_delivery_class_ids",
            new=AsyncMock(return_value={class_id}),
        ),
        patch.object(
            ExamTimetableService,
            "list_leaf_exams",
            new=AsyncMock(return_value=[existing_exam]),
        ),
        patch.object(
            ExamTimetableService,
            "_exam_delivery_class_ids",
            new=AsyncMock(return_value={class_id}),
        ),
        patch.object(
            ElectiveEligibilityService,
            "subject_requires_selection",
            new=AsyncMock(return_value=True),
        ),
        patch.object(
            ElectiveEligibilityService,
            "projected_student_ids_for_classes",
            new=AsyncMock(return_value={uuid4()}),
        ),
        patch.object(
            ExamTimetableService,
            "_projected_audience_ids",
            new=AsyncMock(return_value={uuid4()}),
        ),
    ):
        await ExamTimetableService.require_planned_slot_available(
            SimpleNamespace(),
            session_id=existing_exam.session_id,
            term_id=existing_exam.term_id,
            curriculum_subject_id=proposed_subject_id,
            scheduled_start_at=now,
            latest_normal_start_at=now,
            duration_minutes=60,
        )


@pytest.mark.asyncio
async def test_planning_rejects_grouped_electives_when_student_audiences_intersect() -> (
    None
):
    now = datetime.now(UTC)
    class_id = uuid4()
    shared_student_id = uuid4()
    proposed_subject_id = uuid4()
    existing_exam = SimpleNamespace(
        id=uuid4(),
        title="Music",
        session_id=uuid4(),
        term_id=uuid4(),
        curriculum_subject_id=uuid4(),
        status=ExamStatus.SUBMITTED,
        scheduled_start_at=now,
        latest_normal_start_at=now,
        duration_minutes=60,
    )

    with (
        patch.object(
            ExamTimetableService, "level_id", new=AsyncMock(return_value=uuid4())
        ),
        patch.object(ExamTimetableService, "acquire_level_lock", new=AsyncMock()),
        patch.object(
            ExamTimetableService,
            "_derived_delivery_class_ids",
            new=AsyncMock(return_value={class_id}),
        ),
        patch.object(
            ExamTimetableService,
            "list_leaf_exams",
            new=AsyncMock(return_value=[existing_exam]),
        ),
        patch.object(
            ExamTimetableService,
            "_exam_delivery_class_ids",
            new=AsyncMock(return_value={class_id}),
        ),
        patch.object(
            ElectiveEligibilityService,
            "subject_requires_selection",
            new=AsyncMock(return_value=True),
        ),
        patch.object(
            ElectiveEligibilityService,
            "projected_student_ids_for_classes",
            new=AsyncMock(return_value={shared_student_id}),
        ),
        patch.object(
            ExamTimetableService,
            "_projected_audience_ids",
            new=AsyncMock(return_value={shared_student_id}),
        ),
        pytest.raises(
            ExamStateError, match="Schedule clash:.*reserves shared students"
        ),
    ):
        await ExamTimetableService.require_planned_slot_available(
            SimpleNamespace(),
            session_id=existing_exam.session_id,
            term_id=existing_exam.term_id,
            curriculum_subject_id=proposed_subject_id,
            scheduled_start_at=now,
            latest_normal_start_at=now,
            duration_minutes=60,
        )


def test_weave_v5_contract_contains_elective_projection_entities() -> None:
    group_id = uuid4()
    curriculum_subject_id = uuid4()
    subject = WeaveCurriculumSubjectSnapshot(
        id=curriculum_subject_id,
        curriculum_id=uuid4(),
        subject_id=uuid4(),
        is_elective=True,
        elective_group_id=group_id,
        is_active=True,
    )
    selection = WeaveStudentElectiveSelectionSnapshot(
        id=uuid4(),
        student_id=uuid4(),
        elective_group_id=group_id,
        curriculum_subject_id=curriculum_subject_id,
    )

    assert subject.elective_group_id == group_id
    assert selection.curriculum_subject_id == curriculum_subject_id
    assert "student_elective_selection" in ENTITY_SCHEMAS
    assert "student_elective_selection" in ENTITY_MODELS
    assert (
        "student_elective_selection",
        "student_elective_selections",
    ) in BOOTSTRAP_SECTIONS


def test_v5_bootstrap_remains_compatible_when_selection_field_is_absent() -> None:
    payload = WeaveAcademicBootstrap.model_validate(
        {
            "metadata": {
                "schema_version": 5,
                "snapshot_id": uuid4(),
                "generated_at": datetime.now(UTC),
                "cursor": 0,
            },
            "school": {
                "id": uuid4(),
                "name": "Test School",
                "timezone": "Africa/Lagos",
            },
            "server": {"id": uuid4(), "name": "CBT Server"},
            "sessions": [],
            "terms": [],
            "levels": [],
            "arm_labels": [],
            "departments": [],
            "classes": [],
            "class_term_departments": [],
            "subjects": [],
            "curricula": [],
            "curriculum_subjects": [],
            "curriculum_subject_departments": [],
            "assessment_schemes": [],
            "assessment_components": [],
            "admins": [],
            "teachers": [],
            "teacher_assignments": [],
            "student_enrollments": [],
        }
    )

    assert payload.student_elective_selections == []
