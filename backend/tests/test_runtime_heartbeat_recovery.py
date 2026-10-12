from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ["DEBUG"] = "false"

from app.domains.runtime.repository import RuntimeRepository
from app.domains.runtime.service import (
    RUNTIME_GAP_SUSPEND_AFTER_SECONDS,
    RuntimeHeartbeatService,
)


class _SessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


class RuntimeHeartbeatRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_runtime_health_uses_durable_heartbeat_threshold(self) -> None:
        now = datetime.now(UTC)
        healthy = SimpleNamespace(
            last_heartbeat_at=now
            - timedelta(seconds=RUNTIME_GAP_SUSPEND_AFTER_SECONDS - 1)
        )
        stale = SimpleNamespace(
            last_heartbeat_at=now
            - timedelta(seconds=RUNTIME_GAP_SUSPEND_AFTER_SECONDS + 1)
        )
        self.assertTrue(RuntimeHeartbeatService._is_healthy_runtime(healthy, now=now))
        self.assertFalse(RuntimeHeartbeatService._is_healthy_runtime(stale, now=now))

    async def test_local_process_gap_does_not_suspend_when_peer_is_healthy(
        self,
    ) -> None:
        service = RuntimeHeartbeatService()
        runtime_id = uuid4()
        service._runtime_id = runtime_id
        db = AsyncMock()
        runtime = SimpleNamespace(
            runtime_id=runtime_id,
            stopped_at=None,
            last_heartbeat_at=datetime.now(UTC) - timedelta(seconds=30),
        )
        now = datetime.now(UTC)
        last_healthy = now - timedelta(seconds=30)

        with (
            patch(
                "app.domains.runtime.service.async_session_factory",
                new=lambda: _SessionContext(db),
            ),
            patch.object(service, "_acquire_cluster_lock", new=AsyncMock()),
            patch.object(
                service,
                "_other_healthy_runtime_exists",
                new=AsyncMock(return_value=True),
            ),
            patch.object(
                service,
                "_suspend_active_exams_in_transaction",
                new=AsyncMock(),
            ) as suspend,
            patch.object(
                RuntimeRepository,
                "get_runtime_state_by_id",
                new=AsyncMock(return_value=runtime),
            ),
            patch.object(
                RuntimeRepository,
                "save_runtime_state",
                new=AsyncMock(),
            ),
        ):
            await service._recover_live_gap_and_heartbeat(
                last_healthy_at=last_healthy,
                now=now,
            )

        suspend.assert_not_awaited()
        self.assertEqual(runtime.last_heartbeat_at, now)
        db.commit.assert_awaited_once()

    async def test_cluster_wide_gap_suspends_from_last_healthy_time(self) -> None:
        service = RuntimeHeartbeatService()
        runtime_id = uuid4()
        service._runtime_id = runtime_id
        db = AsyncMock()
        runtime = SimpleNamespace(
            runtime_id=runtime_id,
            stopped_at=None,
            last_heartbeat_at=datetime.now(UTC) - timedelta(seconds=30),
        )
        now = datetime.now(UTC)
        last_healthy = now - timedelta(seconds=30)

        with (
            patch(
                "app.domains.runtime.service.async_session_factory",
                new=lambda: _SessionContext(db),
            ),
            patch.object(service, "_acquire_cluster_lock", new=AsyncMock()),
            patch.object(
                service,
                "_other_healthy_runtime_exists",
                new=AsyncMock(return_value=False),
            ),
            patch.object(
                service,
                "_suspend_active_exams_in_transaction",
                new=AsyncMock(return_value=[uuid4()]),
            ) as suspend,
            patch.object(
                RuntimeRepository,
                "get_runtime_state_by_id",
                new=AsyncMock(return_value=runtime),
            ),
            patch.object(
                RuntimeRepository,
                "save_runtime_state",
                new=AsyncMock(),
            ),
        ):
            await service._recover_live_gap_and_heartbeat(
                last_healthy_at=last_healthy,
                now=now,
            )

        suspend.assert_awaited_once()
        self.assertEqual(
            suspend.await_args.kwargs["outage_started_at"],
            last_healthy,
        )
        self.assertEqual(runtime.last_heartbeat_at, now)
        db.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
