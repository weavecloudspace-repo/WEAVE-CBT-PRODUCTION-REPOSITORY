from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.domains.sync.supervisor import (
    RECONCILE_FALLBACK_SECONDS,
    SYNC_LEADER_LOCK_KEY,
    SyncSupervisor,
)


class _FakeConnection:
    def __init__(self, *, acquired: bool = True) -> None:
        self.scalar = AsyncMock(return_value=acquired)
        self.execute = AsyncMock()
        self.commit = AsyncMock()


class SyncSupervisorLeadershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_postgres_advisory_lock_elects_single_sync_owner(self) -> None:
        connection = _FakeConnection(acquired=True)
        acquired = await SyncSupervisor._acquire_leadership(connection)  # type: ignore[arg-type]

        self.assertTrue(acquired)
        connection.scalar.assert_awaited_once()
        params = connection.scalar.await_args.args[1]
        self.assertEqual(params["lock_key"], SYNC_LEADER_LOCK_KEY)
        connection.commit.assert_awaited_once()

    async def test_non_leader_does_not_claim_sync_owner(self) -> None:
        connection = _FakeConnection(acquired=False)
        acquired = await SyncSupervisor._acquire_leadership(connection)  # type: ignore[arg-type]
        self.assertFalse(acquired)

    async def test_leader_connection_is_heartbeat_checked(self) -> None:
        connection = _FakeConnection()
        await SyncSupervisor._check_leadership_connection(connection)  # type: ignore[arg-type]
        connection.execute.assert_awaited_once()
        connection.commit.assert_awaited_once()

    def test_fallback_reconcile_interval_remains_bounded(self) -> None:
        self.assertGreater(RECONCILE_FALLBACK_SECONDS, 0)
        self.assertLessEqual(RECONCILE_FALLBACK_SECONDS, 60)


if __name__ == "__main__":
    unittest.main()
