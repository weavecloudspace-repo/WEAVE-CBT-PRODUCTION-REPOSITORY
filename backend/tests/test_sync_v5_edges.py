from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.domains.sync.service import SyncContractViolation, SyncService
from app.integrations.weave.schemas import (
    SYNC_SCHEMA_VERSION,
    WeaveSyncChange,
)


class SyncV5EdgeTests(unittest.TestCase):
    def test_empty_delta_cannot_advance_cursor(self) -> None:
        with self.assertRaises(SyncContractViolation):
            SyncService._validate_delta(10, [], 11)

    def test_empty_delta_may_keep_cursor_unchanged(self) -> None:
        SyncService._validate_delta(10, [], 10)

    def test_repeated_entity_changes_coalesce_to_latest_cursor_state(self) -> None:
        entity_id = uuid4()
        now = datetime.now(UTC)
        first = WeaveSyncChange(
            event_id=uuid4(),
            cursor=11,
            entity_type="teacher_assignment",
            entity_id=entity_id,
            operation="updated",
            schema_version=SYNC_SCHEMA_VERSION,
            payload={
                "id": str(entity_id),
                "teacher_membership_id": str(uuid4()),
                "class_id": str(uuid4()),
                "curriculum_subject_id": str(uuid4()),
                "effective_from": now.date().isoformat(),
                "effective_to": None,
            },
            occurred_at=now,
        )
        tombstone = WeaveSyncChange(
            event_id=uuid4(),
            cursor=12,
            entity_type="teacher_assignment",
            entity_id=entity_id,
            operation="deleted",
            schema_version=SYNC_SCHEMA_VERSION,
            payload=None,
            occurred_at=now,
        )

        effective = SyncService._coalesce_changes([first, tombstone])

        self.assertEqual(len(effective), 1)
        self.assertEqual(effective[0].cursor, 12)
        self.assertEqual(effective[0].operation, "deleted")


if __name__ == "__main__":
    unittest.main()
