from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from pydantic import SecretStr

from app.domains.auth.cloud_access import (
    _CloudAccessPreparation,
    _inspect_cloud_access,
    get_or_repair_weave_actor_access_token,
)
from app.domains.auth.coordination import LocalAuthCoordinationUnavailable
from app.domains.auth.models import (
    WEAVE_AUTH_STATE_DEGRADED,
    WEAVE_AUTH_STATE_REFRESH_PENDING,
)
from app.domains.auth.repository import AuthRepository
from app.integrations.weave.auth_schemas import WeaveActorTokenPair
from app.integrations.weave.exceptions import (
    WeaveRequestRejectedError,
    WeaveUnavailableError,
)


class _AsyncContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _db() -> AsyncMock:
    db = AsyncMock()
    db.begin = MagicMock(return_value=_AsyncContext())
    return db


@asynccontextmanager
async def _unlocked(_session_id):
    yield


@asynccontextmanager
async def _coordination_failure(_session_id):
    raise LocalAuthCoordinationUnavailable("redis unavailable")
    yield


class CloudActorAccessPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_degraded_session_reuses_pending_cloud_operation_before_io(self):
        db = _db()
        session_id = uuid4()
        operation_id = uuid4()
        now = datetime.now(UTC)
        session = SimpleNamespace(
            id=session_id,
            revoked_at=None,
            expires_at=now + timedelta(hours=5),
            weave_auth_state=WEAVE_AUTH_STATE_DEGRADED,
            weave_access_token_encrypted="encrypted-access",
            weave_access_token_expires_at=now - timedelta(minutes=1),
            weave_refresh_token_encrypted="encrypted-refresh",
            weave_refresh_token_expires_at=now + timedelta(hours=5),
            weave_refresh_operation_id=operation_id,
        )

        with (
            patch.object(
                AuthRepository,
                "get_session_by_id",
                new=AsyncMock(return_value=session),
            ) as get_session,
            patch.object(
                AuthRepository,
                "save_session",
                new=AsyncMock(return_value=session),
            ) as save_session,
            patch(
                "app.domains.auth.cloud_access.decrypt_local_secret",
                return_value="raw-cloud-refresh",
            ) as decrypt,
        ):
            prepared = await _inspect_cloud_access(
                db,
                session_id=session_id,
                prepare_repair=True,
            )

        self.assertIsNone(prepared.access_token)
        self.assertEqual(prepared.operation_id, operation_id)
        self.assertEqual(prepared.refresh_token, "raw-cloud-refresh")
        self.assertEqual(session.weave_refresh_operation_id, operation_id)
        self.assertEqual(session.weave_auth_state, WEAVE_AUTH_STATE_REFRESH_PENDING)
        get_session.assert_awaited_once_with(db, session_id, lock=True)
        save_session.assert_awaited_once_with(db, session)
        self.assertIn("weave-refresh", decrypt.call_args.kwargs["purpose"])


class CloudActorAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_cloud_access_token_returns_without_rotation(self):
        db = AsyncMock()
        session_id = uuid4()

        with patch(
            "app.domains.auth.cloud_access._inspect_cloud_access",
            new=AsyncMock(
                return_value=_CloudAccessPreparation(access_token="current-actor-token")
            ),
        ) as inspect:
            result = await get_or_repair_weave_actor_access_token(
                db,
                session_id=session_id,
            )

        self.assertEqual(result, "current-actor-token")
        inspect.assert_awaited_once_with(
            db,
            session_id=session_id,
            prepare_repair=False,
        )

    async def test_expired_cloud_access_repairs_with_persisted_operation_id(self):
        db = AsyncMock()
        session_id = uuid4()
        operation_id = uuid4()
        token_pair = WeaveActorTokenPair(
            access_token=SecretStr("new-actor-access"),
            access_token_expires_at=datetime.now(UTC) + timedelta(minutes=20),
            refresh_token=SecretStr("new-actor-refresh"),
            refresh_token_expires_at=datetime.now(UTC) + timedelta(hours=6),
        )
        installation = SimpleNamespace(
            server_credential=SecretStr("server-secret"),
        )

        with (
            patch(
                "app.domains.auth.cloud_access._inspect_cloud_access",
                new=AsyncMock(
                    side_effect=[
                        _CloudAccessPreparation(),
                        _CloudAccessPreparation(
                            operation_id=operation_id,
                            refresh_token="old-cloud-refresh",
                        ),
                    ]
                ),
            ),
            patch(
                "app.domains.auth.cloud_access.staff_refresh_lock",
                side_effect=_unlocked,
            ),
            patch(
                "app.domains.auth.cloud_access.node_identity_store.load",
                return_value=installation,
            ),
            patch(
                "app.domains.auth.cloud_access.weave_auth_gateway.refresh_staff_authorization",
                new=AsyncMock(return_value=token_pair),
            ) as cloud_refresh,
            patch(
                "app.domains.auth.cloud_access._complete_cloud_repair",
                new=AsyncMock(return_value="new-actor-access"),
            ) as complete,
        ):
            result = await get_or_repair_weave_actor_access_token(
                db,
                session_id=session_id,
            )

        self.assertEqual(result, "new-actor-access")
        cloud_refresh.assert_awaited_once_with(
            refresh_token="old-cloud-refresh",
            idempotency_key=operation_id,
            server_credential=installation.server_credential,
        )
        complete.assert_awaited_once_with(
            db,
            session_id=session_id,
            operation_id=operation_id,
            token_pair=token_pair,
        )

    async def test_network_failure_marks_repair_degraded_and_preserves_retry(self):
        db = AsyncMock()
        session_id = uuid4()
        operation_id = uuid4()
        installation = SimpleNamespace(
            server_credential=SecretStr("server-secret"),
        )

        with (
            patch(
                "app.domains.auth.cloud_access._inspect_cloud_access",
                new=AsyncMock(
                    side_effect=[
                        _CloudAccessPreparation(),
                        _CloudAccessPreparation(
                            operation_id=operation_id, refresh_token="old-cloud-refresh"
                        ),
                    ]
                ),
            ),
            patch(
                "app.domains.auth.cloud_access.staff_refresh_lock",
                side_effect=_unlocked,
            ),
            patch(
                "app.domains.auth.cloud_access.node_identity_store.load",
                return_value=installation,
            ),
            patch(
                "app.domains.auth.cloud_access.weave_auth_gateway.refresh_staff_authorization",
                new=AsyncMock(side_effect=WeaveUnavailableError("offline")),
            ),
            patch(
                "app.domains.auth.cloud_access._mark_cloud_repair_degraded",
                new=AsyncMock(),
            ) as mark_degraded,
            self.assertRaises(WeaveUnavailableError),
        ):
            await get_or_repair_weave_actor_access_token(
                db,
                session_id=session_id,
            )

        mark_degraded.assert_awaited_once_with(
            db,
            session_id=session_id,
            operation_id=operation_id,
        )

    async def test_terminal_weave_rejection_revokes_local_session(self):
        db = AsyncMock()
        session_id = uuid4()
        operation_id = uuid4()
        installation = SimpleNamespace(
            server_credential=SecretStr("server-secret"),
        )

        with (
            patch(
                "app.domains.auth.cloud_access._inspect_cloud_access",
                new=AsyncMock(
                    side_effect=[
                        _CloudAccessPreparation(),
                        _CloudAccessPreparation(
                            operation_id=operation_id, refresh_token="old-cloud-refresh"
                        ),
                    ]
                ),
            ),
            patch(
                "app.domains.auth.cloud_access.staff_refresh_lock",
                side_effect=_unlocked,
            ),
            patch(
                "app.domains.auth.cloud_access.node_identity_store.load",
                return_value=installation,
            ),
            patch(
                "app.domains.auth.cloud_access.weave_auth_gateway.refresh_staff_authorization",
                new=AsyncMock(
                    side_effect=WeaveRequestRejectedError(
                        status_code=401, detail="Actor authorization revoked."
                    )
                ),
            ),
            patch(
                "app.domains.auth.cloud_access._revoke_cloud_session", new=AsyncMock()
            ) as revoke,
            self.assertRaises(WeaveRequestRejectedError),
        ):
            await get_or_repair_weave_actor_access_token(
                db,
                session_id=session_id,
            )

        revoke.assert_awaited_once()
        self.assertEqual(revoke.await_args.kwargs["session_id"], session_id)

    async def test_coordination_failure_becomes_retryable_cloud_unavailable(self):
        db = AsyncMock()
        session_id = uuid4()

        with (
            patch(
                "app.domains.auth.cloud_access._inspect_cloud_access",
                new=AsyncMock(return_value=_CloudAccessPreparation()),
            ),
            patch(
                "app.domains.auth.cloud_access.staff_refresh_lock",
                side_effect=_coordination_failure,
            ),
            self.assertRaises(WeaveUnavailableError),
        ):
            await get_or_repair_weave_actor_access_token(
                db,
                session_id=session_id,
            )


if __name__ == "__main__":
    unittest.main()
