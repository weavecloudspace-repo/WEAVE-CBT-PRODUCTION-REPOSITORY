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
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.domains.academics.repository import AcademicRepository
from app.domains.auth.service import LocalAuthService
from app.domains.sync.invalidation import SyncInvalidationRepository
from app.domains.sync.service import SyncService
from app.integrations.weave.schemas import (
    WeaveAcademicBootstrap,
    WeaveSyncChange,
)


class StaffTrustSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_staff_tombstone_reconciles_local_trust(self):
        db = AsyncMock()
        occurred_at = datetime.now(UTC)
        change = WeaveSyncChange(
            event_id=uuid4(),
            cursor=1,
            entity_type="teacher",
            entity_id=uuid4(),
            operation="deleted",
            schema_version=5,
            payload=None,
            occurred_at=occurred_at,
        )

        with (
            patch.object(
                AcademicRepository,
                "bulk_tombstone_projections",
                new=AsyncMock(),
            ),
            patch.object(
                AcademicRepository,
                "bulk_upsert_projections",
                new=AsyncMock(),
            ),
            patch.object(
                SyncInvalidationRepository,
                "mark_pre_execution_rosters_stale",
                new=AsyncMock(),
            ),
            patch.object(
                LocalAuthService,
                "reconcile_synced_staff_trust",
                new=AsyncMock(),
            ) as reconcile_trust,
        ):
            await SyncService()._apply_delta_page(db, [change])

        reconcile_trust.assert_awaited_once_with(
            db,
            revalidated_at=occurred_at,
        )

    async def test_full_bootstrap_reconciles_staff_missing_from_snapshot(self):
        db = AsyncMock()
        generated_at = datetime.now(UTC)
        payload = WeaveAcademicBootstrap.model_validate(
            {
                "metadata": {
                    "schema_version": 5,
                    "snapshot_id": str(uuid4()),
                    "generated_at": generated_at,
                    "cursor": 12,
                },
                "school": {
                    "id": str(uuid4()),
                    "name": "Test School",
                    "institution_type": "secondary",
                    "timezone": "Africa/Lagos",
                },
                "server": {
                    "id": str(uuid4()),
                    "name": "CBT Server",
                },
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

        with (
            patch.object(
                AcademicRepository,
                "bulk_upsert_projections",
                new=AsyncMock(),
            ),
            patch.object(
                AcademicRepository,
                "mark_all_projection_rows_deleted",
                new=AsyncMock(),
            ),
            patch.object(
                SyncInvalidationRepository,
                "mark_pre_execution_rosters_stale",
                new=AsyncMock(),
            ),
            patch.object(
                LocalAuthService,
                "reconcile_synced_staff_trust",
                new=AsyncMock(),
            ) as reconcile_trust,
        ):
            await SyncService()._bulk_install_bootstrap(db, payload)

        reconcile_trust.assert_awaited_once_with(
            db,
            revalidated_at=generated_at,
        )
