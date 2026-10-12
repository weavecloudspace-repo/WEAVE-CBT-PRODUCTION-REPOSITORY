from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.domains.sync.supervisor import SyncSupervisor
from app.workers.roster_delivery import enqueue_roster_reconciliation_after_sync


class _AsyncSessionContext:
    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class ImmediateRosterDeliveryDecisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_sync_change_does_not_scan_for_stale_rosters(self) -> None:
        result = SimpleNamespace(bootstrapped=False, changes_applied=0)

        with patch(
            "app.workers.roster_delivery.enqueue_stale_roster_reconciliations",
            AsyncMock(),
        ) as enqueue_stale:
            queued = await enqueue_roster_reconciliation_after_sync(result)

        self.assertEqual(queued, 0)
        enqueue_stale.assert_not_awaited()

    async def test_applied_sync_changes_trigger_immediate_delivery(self) -> None:
        result = SimpleNamespace(bootstrapped=False, changes_applied=3)

        with patch(
            "app.workers.roster_delivery.enqueue_stale_roster_reconciliations",
            AsyncMock(return_value=2),
        ) as enqueue_stale:
            queued = await enqueue_roster_reconciliation_after_sync(result)

        self.assertEqual(queued, 2)
        enqueue_stale.assert_awaited_once_with()

    async def test_bootstrap_triggers_immediate_delivery(self) -> None:
        result = SimpleNamespace(bootstrapped=True, changes_applied=0)

        with patch(
            "app.workers.roster_delivery.enqueue_stale_roster_reconciliations",
            AsyncMock(return_value=1),
        ) as enqueue_stale:
            queued = await enqueue_roster_reconciliation_after_sync(result)

        self.assertEqual(queued, 1)
        enqueue_stale.assert_awaited_once_with()


class SyncSupervisorRosterDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_reconcile_requests_roster_delivery_after_sync(self) -> None:
        db = SimpleNamespace()
        result = SimpleNamespace(
            cursor=42,
            bootstrapped=False,
            changes_applied=1,
        )

        with (
            patch(
                "app.domains.sync.supervisor.async_session_factory",
                Mock(return_value=_AsyncSessionContext(db)),
            ),
            patch(
                "app.domains.sync.supervisor.sync_service.reconcile",
                AsyncMock(return_value=result),
            ) as reconcile,
            patch(
                "app.domains.sync.supervisor.enqueue_roster_reconciliation_after_sync",
                AsyncMock(return_value=1),
            ) as enqueue_rosters,
            patch(
                "app.domains.sync.supervisor.branding_service.refresh_best_effort",
                AsyncMock(),
            ) as refresh_branding,
        ):
            cursor = await SyncSupervisor._reconcile_once()

        self.assertEqual(cursor, 42)
        reconcile.assert_awaited_once_with(db)
        enqueue_rosters.assert_awaited_once_with(result)
        refresh_branding.assert_awaited_once_with(db)


if __name__ == "__main__":
    unittest.main()
