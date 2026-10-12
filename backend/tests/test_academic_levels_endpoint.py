"""Independent local academic-level catalog endpoint tests (no database required)."""
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

from app.domains.academics.repository import AcademicRepository
from app.domains.academics.router import list_academic_levels
from app.domains.academics.schemas import AcademicLevelResponse


class AcademicLevelsEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_catalog_does_not_require_curriculum_subjects(self) -> None:
        level = SimpleNamespace(
            id=uuid4(), name="JSS 1", category="junior_secondary", position=1,
        )
        with patch.object(
            AcademicRepository,
            "list_levels",
            new=AsyncMock(return_value=[level]),
        ) as list_levels:
            output = await list_academic_levels(
                db=object(),  # type: ignore[arg-type]
                _admin=SimpleNamespace(role="admin"),  # type: ignore[arg-type]
            )
        list_levels.assert_awaited_once()
        self.assertEqual(output, [
            AcademicLevelResponse(
                id=level.id,
                name=level.name,
                category=level.category,
                position=level.position,
            )
        ])


if __name__ == "__main__":
    unittest.main()
