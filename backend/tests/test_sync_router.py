from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Response

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.domains.sync import router as sync_router


class SyncRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconcile_uses_incremental_cursor_path_by_default(self) -> None:
        db = object()
        response = Response()
        expected = SimpleNamespace(bootstrapped=False, changes_applied=0)

        with (
            patch.object(
                sync_router.sync_service,
                "reconcile",
                new=AsyncMock(return_value=expected),
            ) as reconcile,
            patch.object(
                sync_router.sync_service,
                "bootstrap",
                new=AsyncMock(),
            ) as bootstrap,
        ):
            result = await sync_router.reconcile_now(
                db,  # type: ignore[arg-type]
                object(),  # type: ignore[arg-type]
                response,
                force_full=False,
            )

        self.assertIs(result, expected)
        reconcile.assert_awaited_once_with(db)
        bootstrap.assert_not_awaited()
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_reconcile_force_full_reinstalls_authoritative_snapshot(self) -> None:
        db = object()
        response = Response()
        expected = SimpleNamespace(bootstrapped=True, changes_applied=0)

        with (
            patch.object(
                sync_router.sync_service,
                "reconcile",
                new=AsyncMock(),
            ) as reconcile,
            patch.object(
                sync_router.sync_service,
                "bootstrap",
                new=AsyncMock(return_value=expected),
            ) as bootstrap,
            patch(
                "app.domains.sync.router.enqueue_roster_reconciliation_after_sync",
                new=AsyncMock(),
            ),
        ):
            result = await sync_router.reconcile_now(
                db,  # type: ignore[arg-type]
                object(),  # type: ignore[arg-type]
                response,
                force_full=True,
            )

        self.assertIs(result, expected)
        bootstrap.assert_awaited_once_with(db, force=True)
        reconcile.assert_not_awaited()
        self.assertEqual(response.headers["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main()
