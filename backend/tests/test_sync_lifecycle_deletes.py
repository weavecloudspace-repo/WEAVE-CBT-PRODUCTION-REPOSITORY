from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.domains.academics.repository import AcademicRepository
from app.domains.sync.invalidation import SyncInvalidationRepository
from app.domains.sync.service import ENTITY_MODELS, SyncService
from app.integrations.weave.schemas import (
    SYNC_SCHEMA_VERSION,
    WeaveSyncChange,
)


class SyncLifecycleDeleteTests(unittest.IsolatedAsyncioTestCase):
    async def test_revoked_academic_entities_tombstone_existing_local_projection(
        self,
    ) -> None:
        service = SyncService()
        occurred_at = datetime.now(UTC)

        for entity_type in ("student_enrollment", "teacher_assignment"):
            with self.subTest(entity_type=entity_type):
                entity_id = uuid4()
                change = WeaveSyncChange(
                    event_id=uuid4(),
                    cursor=200,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    operation="deleted",
                    schema_version=SYNC_SCHEMA_VERSION,
                    payload=None,
                    occurred_at=occurred_at,
                )

                with (
                    patch.object(
                        AcademicRepository,
                        "bulk_tombstone_projections",
                        new=AsyncMock(),
                    ) as tombstone_projection,
                    patch.object(
                        AcademicRepository,
                        "bulk_upsert_projections",
                        new=AsyncMock(),
                    ),
                    patch.object(
                        SyncInvalidationRepository,
                        "mark_pre_execution_rosters_stale",
                        new=AsyncMock(),
                    ) as invalidate,
                ):
                    await service._apply_delta_page(  # type: ignore[arg-type]
                        object(),
                        [change],
                    )

                tombstone_projection.assert_awaited_once_with(
                    unittest.mock.ANY,
                    ENTITY_MODELS[entity_type],
                    [entity_id],
                    deleted_at=occurred_at,
                )
                if entity_type == "student_enrollment":
                    invalidate.assert_awaited_once()
                else:
                    invalidate.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
