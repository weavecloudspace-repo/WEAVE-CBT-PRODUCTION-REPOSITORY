from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from pydantic import SecretStr, ValidationError

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.core.database import Base
from app.domains.academics.models import CurriculumSubjectDepartment
from app.domains.academics.repository import AcademicRepository
from app.domains.node.identity_store import node_identity_store
from app.domains.sync.invalidation import SyncInvalidationRepository
from app.domains.sync.repository import SyncRepository
from app.domains.sync.service import (
    ENTITY_MODELS,
    ENTITY_SCHEMAS,
    SyncService,
)
from app.integrations.weave.exceptions import WeaveRequestRejectedError
from app.integrations.weave.schemas import (
    SYNC_SCHEMA_VERSION,
    WeaveAcademicBootstrap,
    WeaveCurriculumSubjectDepartmentSnapshot,
    WeaveSyncChange,
    WeaveTeacherAssignmentSnapshot,
)


class _FakeAsyncSession:
    def __init__(self) -> None:
        self.rollback = AsyncMock()


class SyncContractTests(unittest.TestCase):
    def _bootstrap_payload(self) -> dict:
        tenant_id = uuid4()
        server_id = uuid4()
        return {
            "metadata": {
                "schema_version": SYNC_SCHEMA_VERSION,
                "snapshot_id": str(uuid4()),
                "generated_at": "2026-09-15T00:10:46Z",
                "cursor": 134,
            },
            "school": {
                "id": str(tenant_id),
                "name": "Debright college",
                "institution_type": "SECONDARY_SCHOOL",
                "timezone": "Africa/Lagos",
            },
            "server": {"id": str(server_id), "name": "Debright server 1"},
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

    def test_bootstrap_v5_parses_exact_top_level_shape(self) -> None:
        raw = self._bootstrap_payload()
        payload = WeaveAcademicBootstrap.model_validate(raw)

        self.assertEqual(payload.metadata.schema_version, 5)
        self.assertEqual(payload.metadata.cursor, 134)
        self.assertEqual(payload.school.id, UUID(raw["school"]["id"]))
        self.assertEqual(payload.server.id, UUID(raw["server"]["id"]))
        self.assertEqual(payload.curriculum_subject_departments, [])

    def test_bootstrap_rejects_legacy_offerings_field(self) -> None:
        raw = self._bootstrap_payload()
        raw["offerings"] = []
        del raw["curriculum_subject_departments"]

        with self.assertRaises(ValidationError):
            WeaveAcademicBootstrap.model_validate(raw)

    def test_incremental_dispatch_covers_every_weave_v5_entity(self) -> None:
        expected = {
            "academic_level",
            "department",
            "arm_label",
            "class",
            "class_term_department",
            "academic_session",
            "academic_term",
            "subject",
            "curriculum",
            "curriculum_subject",
            "curriculum_subject_department",
            "assessment_scheme",
            "assessment_component",
            "admin",
            "teacher",
            "teacher_assignment",
            "student_enrollment",
            "student_elective_selection",
        }
        self.assertEqual(set(ENTITY_MODELS), expected)
        self.assertEqual(set(ENTITY_SCHEMAS), expected)
        self.assertIs(
            ENTITY_MODELS["curriculum_subject_department"],
            CurriculumSubjectDepartment,
        )

    def test_curriculum_subject_department_has_only_current_v5_scope(self) -> None:
        row = WeaveCurriculumSubjectDepartmentSnapshot.model_validate(
            {
                "id": str(uuid4()),
                "curriculum_subject_id": str(uuid4()),
                "department_id": str(uuid4()),
            }
        )
        self.assertIsNotNone(row.department_id)

        with self.assertRaises(ValidationError):
            WeaveCurriculumSubjectDepartmentSnapshot.model_validate(
                {
                    "id": str(uuid4()),
                    "curriculum_subject_id": str(uuid4()),
                    "department_id": str(uuid4()),
                    "academic_term_id": str(uuid4()),
                }
            )

    def test_teacher_assignment_rejects_removed_is_active_flag(self) -> None:
        raw = {
            "id": str(uuid4()),
            "teacher_membership_id": str(uuid4()),
            "class_id": str(uuid4()),
            "curriculum_subject_id": str(uuid4()),
            "effective_from": "2026-09-01",
            "effective_to": None,
            "is_active": True,
        }
        with self.assertRaises(ValidationError):
            WeaveTeacherAssignmentSnapshot.model_validate(raw)

    def test_model_registry_contains_v5_scope_without_subject_offerings(self) -> None:
        tables = set(Base.metadata.tables)
        self.assertIn("curriculum_subject_departments", tables)
        self.assertNotIn("subject_offerings", tables)
        self.assertNotIn("subject_offering_eligibilities", tables)

    def test_deleted_change_requires_null_tombstone(self) -> None:
        change = WeaveSyncChange.model_validate(
            {
                "event_id": str(uuid4()),
                "cursor": 135,
                "entity_type": "class",
                "entity_id": str(uuid4()),
                "operation": "deleted",
                "schema_version": SYNC_SCHEMA_VERSION,
                "payload": None,
                "occurred_at": "2026-09-15T00:11:00Z",
            }
        )
        self.assertEqual(change.operation, "deleted")


class SyncApplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_curriculum_subject_department_delta_uses_v5_projection(self) -> None:
        service = SyncService()
        now = datetime.now(UTC)
        entity_id = uuid4()
        change = WeaveSyncChange(
            event_id=uuid4(),
            cursor=1,
            entity_type="curriculum_subject_department",
            entity_id=entity_id,
            operation="created",
            schema_version=SYNC_SCHEMA_VERSION,
            payload={
                "id": str(entity_id),
                "curriculum_subject_id": str(uuid4()),
                "department_id": str(uuid4()),
            },
            occurred_at=now,
        )

        with (
            patch.object(
                AcademicRepository,
                "bulk_upsert_projections",
                new=AsyncMock(),
            ) as upsert,
            patch.object(
                AcademicRepository,
                "bulk_tombstone_projections",
                new=AsyncMock(),
            ),
            patch.object(
                SyncInvalidationRepository,
                "mark_pre_execution_rosters_stale",
                new=AsyncMock(),
            ) as invalidate,
        ):
            await service._apply_delta_page(object(), [change])  # type: ignore[arg-type]

        upsert.assert_awaited_once()
        self.assertIs(upsert.await_args.args[1], CurriculumSubjectDepartment)
        invalidate.assert_not_awaited()

    async def test_student_enrollment_change_invalidates_ready_pre_execution_rosters(
        self,
    ) -> None:
        service = SyncService()
        now = datetime.now(UTC)
        entity_id = uuid4()
        change = WeaveSyncChange(
            event_id=uuid4(),
            cursor=1,
            entity_type="student_enrollment",
            entity_id=entity_id,
            operation="updated",
            schema_version=SYNC_SCHEMA_VERSION,
            payload={
                "id": str(entity_id),
                "student_id": str(uuid4()),
                "admission_number": "STD-001",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "academic_level_id": str(uuid4()),
                "class_id": str(uuid4()),
                "academic_session_id": str(uuid4()),
                "is_current": True,
                "student_status": "active",
            },
            occurred_at=now,
        )

        with (
            patch.object(
                AcademicRepository,
                "bulk_upsert_projections",
                new=AsyncMock(),
            ),
            patch.object(
                AcademicRepository,
                "bulk_tombstone_projections",
                new=AsyncMock(),
            ),
            patch.object(
                SyncInvalidationRepository,
                "mark_pre_execution_rosters_stale",
                new=AsyncMock(return_value=1),
            ) as invalidate,
        ):
            await service._apply_delta_page(object(), [change])  # type: ignore[arg-type]

        invalidate.assert_awaited_once()

    async def test_cursor_expiry_forces_authoritative_bootstrap(self) -> None:
        cursor = 40
        gateway = SimpleNamespace(
            fetch_changes=AsyncMock(
                side_effect=WeaveRequestRejectedError(
                    status_code=409,
                    detail="bootstrap required",
                )
            )
        )
        service = SyncService(gateway=gateway)  # type: ignore[arg-type]
        db = _FakeAsyncSession()
        state = SimpleNamespace(
            cursor=cursor,
            bootstrap_completed_at=datetime.now(UTC),
            schema_version=SYNC_SCHEMA_VERSION,
        )
        recovered = object()

        with (
            patch.object(
                node_identity_store,
                "load",
                return_value=SimpleNamespace(
                    server_credential=SecretStr("server-credential")
                ),
            ),
            patch.object(
                SyncRepository,
                "get_state",
                new=AsyncMock(return_value=state),
            ),
            patch.object(
                service,
                "bootstrap",
                new=AsyncMock(return_value=recovered),
            ) as bootstrap,
        ):
            result = await service.reconcile(db)  # type: ignore[arg-type]

        self.assertIs(result, recovered)
        bootstrap.assert_awaited_once_with(db, force=True)


if __name__ == "__main__":
    unittest.main()
