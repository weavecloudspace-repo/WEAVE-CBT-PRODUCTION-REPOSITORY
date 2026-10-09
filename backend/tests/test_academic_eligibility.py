from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.core.exceptions import AcademicScopeError
from app.domains.academics.eligibility import AcademicEligibilityService
from app.domains.academics.repository import AcademicRepository


class AcademicEligibilityTests(unittest.IsolatedAsyncioTestCase):
    def test_specialization_is_inactive_before_threshold(self) -> None:
        level = SimpleNamespace(specialization_required_from_term_position=2)
        term = SimpleNamespace(name="first_term")

        self.assertFalse(
            AcademicEligibilityService.specialization_is_active(
                level,  # type: ignore[arg-type]
                term,  # type: ignore[arg-type]
            )
        )

    def test_specialization_is_active_at_threshold(self) -> None:
        level = SimpleNamespace(specialization_required_from_term_position=2)
        term = SimpleNamespace(name="second_term")

        self.assertTrue(
            AcademicEligibilityService.specialization_is_active(
                level,  # type: ignore[arg-type]
                term,  # type: ignore[arg-type]
            )
        )

    def test_unsupported_term_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(AcademicScopeError, "Unsupported academic term"):
            AcademicEligibilityService.term_position(
                SimpleNamespace(name="summer_term")  # type: ignore[arg-type]
            )

    async def test_subject_applies_to_same_level_before_specialization(self) -> None:
        level_id = uuid4()
        class_id = uuid4()
        subject_id = uuid4()
        curriculum_id = uuid4()
        term_id = uuid4()

        with (
            patch.object(
                AcademicRepository,
                "get_term_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(id=term_id, name="first_term")
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_class_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=class_id,
                        academic_level_id=level_id,
                        is_active=True,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_curriculum_subject_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=subject_id,
                        curriculum_id=curriculum_id,
                        is_active=True,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_curriculum_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=curriculum_id,
                        academic_level_id=level_id,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_level_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=level_id,
                        specialization_required_from_term_position=2,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_class_term_department",
                new=AsyncMock(),
            ) as class_department,
        ):
            applies = await AcademicEligibilityService.subject_applies_to_class(
                object(),  # type: ignore[arg-type]
                curriculum_subject_id=subject_id,
                class_id=class_id,
                academic_term_id=term_id,
            )

        self.assertTrue(applies)
        class_department.assert_not_awaited()

    async def test_subject_from_other_level_does_not_apply(self) -> None:
        class_level_id = uuid4()
        curriculum_level_id = uuid4()
        class_id = uuid4()
        subject_id = uuid4()
        curriculum_id = uuid4()
        term_id = uuid4()

        with (
            patch.object(
                AcademicRepository,
                "get_term_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(id=term_id, name="first_term")
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_class_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=class_id,
                        academic_level_id=class_level_id,
                        is_active=True,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_curriculum_subject_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=subject_id,
                        curriculum_id=curriculum_id,
                        is_active=True,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_curriculum_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=curriculum_id,
                        academic_level_id=curriculum_level_id,
                    )
                ),
            ),
        ):
            applies = await AcademicEligibilityService.subject_applies_to_class(
                object(),  # type: ignore[arg-type]
                curriculum_subject_id=subject_id,
                class_id=class_id,
                academic_term_id=term_id,
            )

        self.assertFalse(applies)

    async def test_general_subject_applies_after_specialization(self) -> None:
        level_id = uuid4()
        department_id = uuid4()
        class_id = uuid4()
        subject_id = uuid4()
        curriculum_id = uuid4()
        term_id = uuid4()

        with (
            patch.object(
                AcademicRepository,
                "get_term_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(id=term_id, name="second_term")
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_class_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=class_id,
                        academic_level_id=level_id,
                        is_active=True,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_curriculum_subject_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=subject_id,
                        curriculum_id=curriculum_id,
                        is_active=True,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_curriculum_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=curriculum_id,
                        academic_level_id=level_id,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_level_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=level_id,
                        specialization_required_from_term_position=2,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_class_term_department",
                new=AsyncMock(
                    return_value=SimpleNamespace(department_id=department_id)
                ),
            ),
            patch.object(
                AcademicRepository,
                "list_curriculum_subject_departments",
                new=AsyncMock(return_value=[]),
            ),
        ):
            applies = await AcademicEligibilityService.subject_applies_to_class(
                object(),  # type: ignore[arg-type]
                curriculum_subject_id=subject_id,
                class_id=class_id,
                academic_term_id=term_id,
            )

        self.assertTrue(applies)

    async def test_department_subject_requires_matching_class_department(self) -> None:
        level_id = uuid4()
        science_department_id = uuid4()
        arts_department_id = uuid4()
        class_id = uuid4()
        subject_id = uuid4()
        curriculum_id = uuid4()
        term_id = uuid4()

        with (
            patch.object(
                AcademicRepository,
                "get_term_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(id=term_id, name="second_term")
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_class_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=class_id,
                        academic_level_id=level_id,
                        is_active=True,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_curriculum_subject_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=subject_id,
                        curriculum_id=curriculum_id,
                        is_active=True,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_curriculum_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=curriculum_id,
                        academic_level_id=level_id,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_level_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=level_id,
                        specialization_required_from_term_position=2,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_class_term_department",
                new=AsyncMock(
                    return_value=SimpleNamespace(department_id=science_department_id)
                ),
            ),
            patch.object(
                AcademicRepository,
                "list_curriculum_subject_departments",
                new=AsyncMock(
                    return_value=[SimpleNamespace(department_id=arts_department_id)]
                ),
            ),
        ):
            applies = await AcademicEligibilityService.subject_applies_to_class(
                object(),  # type: ignore[arg-type]
                curriculum_subject_id=subject_id,
                class_id=class_id,
                academic_term_id=term_id,
            )

        self.assertFalse(applies)

    async def test_missing_class_department_is_invalid_after_specialization(
        self,
    ) -> None:
        level_id = uuid4()
        class_id = uuid4()
        subject_id = uuid4()
        curriculum_id = uuid4()
        term_id = uuid4()

        with (
            patch.object(
                AcademicRepository,
                "get_term_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(id=term_id, name="third_term")
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_class_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=class_id,
                        academic_level_id=level_id,
                        is_active=True,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_curriculum_subject_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=subject_id,
                        curriculum_id=curriculum_id,
                        is_active=True,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_curriculum_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=curriculum_id,
                        academic_level_id=level_id,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_level_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=level_id,
                        specialization_required_from_term_position=1,
                    )
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_class_term_department",
                new=AsyncMock(return_value=None),
            ),
            self.assertRaisesRegex(
                AcademicScopeError,
                "requires a department specialization",
            ),
        ):
            await AcademicEligibilityService.subject_applies_to_class(
                object(),  # type: ignore[arg-type]
                curriculum_subject_id=subject_id,
                class_id=class_id,
                academic_term_id=term_id,
            )

    async def test_inactive_class_is_rejected(self) -> None:
        class_id = uuid4()
        term_id = uuid4()
        subject_id = uuid4()

        with (
            patch.object(
                AcademicRepository,
                "get_term_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(id=term_id, name="first_term")
                ),
            ),
            patch.object(
                AcademicRepository,
                "get_class_by_id",
                new=AsyncMock(
                    return_value=SimpleNamespace(id=class_id, is_active=False)
                ),
            ),
            self.assertRaisesRegex(AcademicScopeError, "Class is inactive"),
        ):
            await AcademicEligibilityService.subject_applies_to_class(
                object(),  # type: ignore[arg-type]
                curriculum_subject_id=subject_id,
                class_id=class_id,
                academic_term_id=term_id,
            )


if __name__ == "__main__":
    unittest.main()
