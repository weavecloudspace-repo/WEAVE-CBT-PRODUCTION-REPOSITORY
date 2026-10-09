from __future__ import annotations

import os
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from pydantic import SecretStr

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("WEAVE_API_BASE_URL", "https://weave.invalid")

from app.domains.academics.repository import AcademicRepository
from app.domains.auth.models import (
    WEAVE_AUTH_STATE_DEGRADED,
    WEAVE_AUTH_STATE_SYNCED,
)
from app.domains.auth.repository import AuthRepository
from app.domains.auth.schemas import StaffLoginRequest
from app.domains.auth.service import (
    INVALID_LOCAL_STAFF_SESSION,
    SYNC_TRUST_REVOKED_REASON,
    LocalAuthService,
    LocalLoginResult,
    LocalSessionAuthenticationError,
    _PreparedCloudRefresh,
)
from app.integrations.weave.auth_schemas import (
    WeaveActorTokenPair,
    WeaveStaffAuthResult,
)
from app.integrations.weave.exceptions import (
    WeaveRequestRejectedError,
    WeaveUnavailableError,
)


class _AsyncContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@asynccontextmanager
async def _unlocked(_session_id):
    yield


def _db() -> AsyncMock:
    db = AsyncMock()
    db.begin = MagicMock(return_value=_AsyncContext())
    return db


def _teacher_actor():
    account_id = uuid4()
    membership_id = uuid4()
    return SimpleNamespace(
        id=uuid4(),
        weave_actor_id=str(account_id),
        weave_membership_id=str(membership_id),
        role="teacher",
        email="teacher@example.com",
        display_name="Teacher One",
        is_active=True,
        last_weave_authenticated_at=None,
        last_weave_revalidated_at=None,
    )


def _session(actor, *, now: datetime):
    return SimpleNamespace(
        id=uuid4(),
        actor_id=actor.id,
        expires_at=now + timedelta(hours=6),
        last_seen_at=now,
        last_refreshed_at=None,
        revoked_at=None,
        revocation_reason=None,
        weave_access_token_encrypted="encrypted-access",
        weave_access_token_issued_at=now - timedelta(minutes=10),
        weave_access_token_expires_at=now + timedelta(minutes=10),
        weave_refresh_token_encrypted="encrypted-refresh",
        weave_refresh_token_expires_at=now + timedelta(hours=6),
        weave_auth_state=WEAVE_AUTH_STATE_SYNCED,
        weave_refresh_operation_id=None,
    )


def _local_refresh(session, *, now: datetime):
    return SimpleNamespace(
        id=uuid4(),
        session_id=session.id,
        token_hash="hash-old-token",
        expires_at=session.expires_at,
        revoked_at=None,
        consumed_at=None,
        reuse_detected_at=None,
        replaced_by_token_id=None,
        refresh_operation_id=None,
        replacement_token_encrypted=None,
    )


class StaffLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_uses_weave_access_and_hard_expiry_as_local_clocks(self):
        db = _db()
        actor = _teacher_actor()
        now = datetime.now(UTC)
        access_expires_at = now + timedelta(minutes=20)
        hard_expires_at = now + timedelta(hours=12)
        tenant_id = uuid4()
        server_id = uuid4()
        weave_result = WeaveStaffAuthResult(
            actor_id=uuid4(),
            membership_id=uuid4(),
            tenant_id=tenant_id,
            role="teacher",
            email="teacher@example.com",
            first_name="Teacher",
            last_name="One",
            access_token=SecretStr("weave-access"),
            access_token_expires_at=access_expires_at,
            refresh_token=SecretStr("weave-refresh"),
            refresh_token_expires_at=hard_expires_at,
        )
        installation = SimpleNamespace(
            tenant_id=tenant_id,
            server_id=server_id,
            server_credential=SecretStr("server-secret"),
        )
        captured_session = None
        captured_local_refresh = None

        async def add_session(_db, value):
            nonlocal captured_session
            captured_session = value
            return value

        async def add_refresh(_db, value):
            nonlocal captured_local_refresh
            captured_local_refresh = value
            value.id = uuid4()
            return value

        with (
            patch(
                "app.domains.auth.service.node_identity_store.load",
                return_value=installation,
            ),
            patch(
                "app.domains.auth.service.weave_auth_gateway.authenticate_staff",
                new=AsyncMock(return_value=weave_result),
            ),
            patch.object(
                LocalAuthService,
                "_upsert_actor",
                new=AsyncMock(return_value=actor),
            ),
            patch.object(
                AuthRepository,
                "add_session",
                new=AsyncMock(side_effect=add_session),
            ),
            patch.object(
                AuthRepository,
                "add_refresh_token",
                new=AsyncMock(side_effect=add_refresh),
            ),
            patch(
                "app.domains.auth.service.encrypt_local_secret",
                side_effect=lambda value, purpose: f"encrypted:{purpose}:{value}",
            ),
            patch(
                "app.domains.auth.service.generate_refresh_token",
                return_value="local-refresh",
            ),
            patch(
                "app.domains.auth.service.hash_refresh_token",
                return_value="hash-local-refresh",
            ),
            patch(
                "app.domains.auth.service.create_local_access_token",
                return_value="local-access",
            ) as issue_access,
        ):
            result = await LocalAuthService.login_staff(
                db,
                payload=StaffLoginRequest(
                    email="teacher@example.com",
                    password="secret",
                ),
            )

        self.assertEqual(result.access_token, "local-access")
        self.assertEqual(result.refresh_token, "local-refresh")
        self.assertEqual(result.access_token_expires_at, access_expires_at)
        self.assertEqual(result.session_expires_at, hard_expires_at)
        self.assertEqual(result.cloud_auth_state, WEAVE_AUTH_STATE_SYNCED)
        self.assertIsNotNone(captured_session)
        self.assertEqual(captured_session.expires_at, hard_expires_at)
        self.assertEqual(
            captured_session.weave_access_token_expires_at, access_expires_at
        )
        self.assertEqual(
            captured_session.weave_refresh_token_expires_at, hard_expires_at
        )
        self.assertNotIn(
            "weave-access", [captured_session.weave_access_token_encrypted]
        )
        self.assertNotIn(
            "weave-refresh", [captured_session.weave_refresh_token_encrypted]
        )
        self.assertEqual(captured_local_refresh.expires_at, hard_expires_at)
        self.assertEqual(issue_access.call_args.kwargs["expires_at"], access_expires_at)


class StaffRefreshOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_forwards_persisted_cloud_operation_to_weave(self):
        db = _db()
        session_id = uuid4()
        operation_id = uuid4()
        cloud_operation_id = uuid4()
        prepared = _PreparedCloudRefresh(
            session_id=session_id,
            cloud_operation_id=cloud_operation_id,
            cloud_refresh_token="cloud-refresh",
        )
        token_pair = WeaveActorTokenPair(
            access_token=SecretStr("new-cloud-access"),
            access_token_expires_at=datetime.now(UTC) + timedelta(minutes=20),
            refresh_token=SecretStr("new-cloud-refresh"),
            refresh_token_expires_at=datetime.now(UTC) + timedelta(hours=6),
        )
        expected = SimpleNamespace(access_token="local-access")
        installation = SimpleNamespace(
            server_id=uuid4(),
            server_credential=SecretStr("server-secret"),
        )

        with (
            patch.object(
                AuthRepository,
                "get_refresh_token_by_hash",
                new=AsyncMock(return_value=SimpleNamespace(session_id=session_id)),
            ),
            patch.object(
                AuthRepository,
                "get_session_by_id",
                new=AsyncMock(return_value=SimpleNamespace(id=session_id)),
            ),
            patch(
                "app.domains.auth.service.hash_refresh_token",
                return_value="local-hash",
            ),
            patch(
                "app.domains.auth.service.staff_refresh_lock",
                side_effect=_unlocked,
            ),
            patch.object(
                LocalAuthService,
                "_prepare_cloud_refresh",
                new=AsyncMock(return_value=prepared),
            ),
            patch(
                "app.domains.auth.service.node_identity_store.load",
                return_value=installation,
            ),
            patch(
                "app.domains.auth.service.weave_auth_gateway.refresh_staff_authorization",
                new=AsyncMock(return_value=token_pair),
            ) as weave_refresh,
            patch.object(
                LocalAuthService,
                "_complete_synced_refresh",
                new=AsyncMock(return_value=expected),
            ) as complete,
        ):
            result = await LocalAuthService.refresh_staff(
                db,
                refresh_token="local-refresh",
                idempotency_key=operation_id,
            )

        self.assertIs(result, expected)
        weave_refresh.assert_awaited_once_with(
            refresh_token="cloud-refresh",
            idempotency_key=cloud_operation_id,
            server_credential=installation.server_credential,
        )
        self.assertEqual(
            complete.await_args.kwargs["cloud_operation_id"],
            cloud_operation_id,
        )

    async def test_network_failure_preserves_local_session_in_degraded_mode(self):
        db = _db()
        session_id = uuid4()
        operation_id = uuid4()
        prepared = _PreparedCloudRefresh(
            session_id=session_id,
            cloud_operation_id=uuid4(),
            cloud_refresh_token="cloud-refresh",
        )
        degraded_result = SimpleNamespace(cloud_auth_state=WEAVE_AUTH_STATE_DEGRADED)
        installation = SimpleNamespace(
            server_id=uuid4(),
            server_credential=SecretStr("server-secret"),
        )

        with (
            patch.object(
                AuthRepository,
                "get_refresh_token_by_hash",
                new=AsyncMock(return_value=SimpleNamespace(session_id=session_id)),
            ),
            patch.object(
                AuthRepository,
                "get_session_by_id",
                new=AsyncMock(return_value=SimpleNamespace(id=session_id)),
            ),
            patch(
                "app.domains.auth.service.hash_refresh_token",
                return_value="local-hash",
            ),
            patch(
                "app.domains.auth.service.staff_refresh_lock",
                side_effect=_unlocked,
            ),
            patch.object(
                LocalAuthService,
                "_prepare_cloud_refresh",
                new=AsyncMock(return_value=prepared),
            ),
            patch(
                "app.domains.auth.service.node_identity_store.load",
                return_value=installation,
            ),
            patch(
                "app.domains.auth.service.weave_auth_gateway.refresh_staff_authorization",
                new=AsyncMock(side_effect=WeaveUnavailableError("offline")),
            ),
            patch.object(
                LocalAuthService,
                "_complete_degraded_refresh",
                new=AsyncMock(return_value=degraded_result),
            ) as degraded,
        ):
            result = await LocalAuthService.refresh_staff(
                db,
                refresh_token="local-refresh",
                idempotency_key=operation_id,
            )

        self.assertIs(result, degraded_result)
        self.assertEqual(
            degraded.await_args.kwargs["cloud_operation_id"],
            prepared.cloud_operation_id,
        )

    async def test_weave_unauthorized_revokes_local_session(self):
        db = _db()
        session_id = uuid4()
        operation_id = uuid4()
        prepared = _PreparedCloudRefresh(
            session_id=session_id,
            cloud_operation_id=uuid4(),
            cloud_refresh_token="cloud-refresh",
        )
        installation = SimpleNamespace(
            server_id=uuid4(),
            server_credential=SecretStr("server-secret"),
        )

        with (
            patch.object(
                AuthRepository,
                "get_refresh_token_by_hash",
                new=AsyncMock(return_value=SimpleNamespace(session_id=session_id)),
            ),
            patch.object(
                AuthRepository,
                "get_session_by_id",
                new=AsyncMock(return_value=SimpleNamespace(id=session_id)),
            ),
            patch(
                "app.domains.auth.service.hash_refresh_token", return_value="local-hash"
            ),
            patch("app.domains.auth.service.staff_refresh_lock", side_effect=_unlocked),
            patch.object(
                LocalAuthService,
                "_prepare_cloud_refresh",
                new=AsyncMock(return_value=prepared),
            ),
            patch(
                "app.domains.auth.service.node_identity_store.load",
                return_value=installation,
            ),
            patch(
                "app.domains.auth.service.weave_auth_gateway.refresh_staff_authorization",
                new=AsyncMock(
                    side_effect=WeaveRequestRejectedError(
                        status_code=401,
                        detail="Invalid or expired CBT actor authorization",
                    )
                ),
            ),
            patch.object(
                LocalAuthService, "_revoke_session_for_cloud_rejection", new=AsyncMock()
            ) as revoke,
            self.assertRaisesRegex(
                LocalSessionAuthenticationError, INVALID_LOCAL_STAFF_SESSION
            ),
        ):
            await LocalAuthService.refresh_staff(
                db,
                refresh_token="local-refresh",
                idempotency_key=operation_id,
            )

        revoke.assert_awaited_once_with(db, token_hash="local-hash")


class LocalRefreshRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_local_operation_recovers_replacement_without_cloud_call(self):
        db = _db()
        actor = _teacher_actor()
        now = datetime.now(UTC)
        session = _session(actor, now=now)
        operation_id = uuid4()
        replacement_id = uuid4()
        stored_token = _local_refresh(session, now=now)
        stored_token.consumed_at = now - timedelta(seconds=5)
        stored_token.replaced_by_token_id = replacement_id
        stored_token.refresh_operation_id = operation_id
        stored_token.replacement_token_encrypted = "encrypted-replacement"
        replacement = SimpleNamespace(
            id=replacement_id,
            session_id=session.id,
            expires_at=session.expires_at,
            revoked_at=None,
            consumed_at=None,
        )
        installation = SimpleNamespace(server_id=uuid4())

        with (
            patch.object(
                LocalAuthService,
                "_lock_refresh_chain",
                new=AsyncMock(return_value=(actor, session, stored_token)),
            ),
            patch.object(
                AuthRepository,
                "get_refresh_token_by_id",
                new=AsyncMock(return_value=replacement),
            ),
            patch.object(
                AuthRepository,
                "save_session",
                new=AsyncMock(return_value=session),
            ),
            patch(
                "app.domains.auth.service.node_identity_store.load",
                return_value=installation,
            ),
            patch(
                "app.domains.auth.service.decrypt_local_secret",
                return_value="replacement-local-refresh",
            ),
            patch(
                "app.domains.auth.service.create_local_access_token",
                return_value="recovered-local-access",
            ),
        ):
            result = await LocalAuthService._prepare_cloud_refresh(
                db,
                token_hash="hash-old-token",
                local_operation_id=operation_id,
            )

        self.assertIsInstance(result, LocalLoginResult)
        self.assertEqual(result.refresh_token, "replacement-local-refresh")
        self.assertEqual(result.access_token, "recovered-local-access")

    async def test_different_operation_on_consumed_local_token_revokes_session(self):
        db = _db()
        actor = _teacher_actor()
        now = datetime.now(UTC)
        session = _session(actor, now=now)
        stored_token = _local_refresh(session, now=now)
        stored_token.consumed_at = now - timedelta(seconds=5)
        stored_token.refresh_operation_id = uuid4()
        stored_token.replaced_by_token_id = uuid4()
        stored_token.replacement_token_encrypted = "encrypted-replacement"

        with (
            patch.object(
                LocalAuthService,
                "_lock_refresh_chain",
                new=AsyncMock(return_value=(actor, session, stored_token)),
            ),
            patch.object(
                LocalAuthService,
                "_recover_local_refresh_locked",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                LocalAuthService,
                "_revoke_session_locked",
                new=AsyncMock(),
            ) as revoke,
            patch.object(
                AuthRepository,
                "save_refresh_token",
                new=AsyncMock(return_value=stored_token),
            ),
            patch(
                "app.domains.auth.service.node_identity_store.load",
                return_value=SimpleNamespace(server_id=uuid4()),
            ),
            self.assertRaisesRegex(
                LocalSessionAuthenticationError,
                INVALID_LOCAL_STAFF_SESSION,
            ),
        ):
            await LocalAuthService._prepare_cloud_refresh(
                db,
                token_hash="hash-old-token",
                local_operation_id=uuid4(),
            )

        self.assertIsNotNone(stored_token.reuse_detected_at)
        revoke.assert_awaited_once()


class StaffTrustTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_teacher_projection_deactivates_actor_and_revokes_session(
        self,
    ):
        db = _db()
        actor = _teacher_actor()
        now = datetime.now(UTC)
        session = _session(actor, now=now)
        refresh = _local_refresh(session, now=now)

        with (
            patch.object(
                AuthRepository,
                "list_actors",
                new=AsyncMock(return_value=[actor]),
            ),
            patch.object(
                AuthRepository,
                "get_actor_by_id",
                new=AsyncMock(return_value=actor),
            ),
            patch.object(
                AcademicRepository,
                "get_teacher_by_membership_id",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                AuthRepository,
                "save_actor",
                new=AsyncMock(return_value=actor),
            ),
            patch.object(
                AuthRepository,
                "list_sessions_for_actor",
                new=AsyncMock(return_value=[session]),
            ),
            patch.object(
                AuthRepository,
                "save_session",
                new=AsyncMock(return_value=session),
            ),
            patch.object(
                AuthRepository,
                "list_refresh_tokens_for_session",
                new=AsyncMock(return_value=[refresh]),
            ),
            patch.object(
                AuthRepository,
                "save_refresh_tokens",
                new=AsyncMock(return_value=[refresh]),
            ),
        ):
            await LocalAuthService.reconcile_synced_staff_trust(
                db,
                revalidated_at=now,
            )

        self.assertFalse(actor.is_active)
        self.assertEqual(actor.last_weave_revalidated_at, now)
        self.assertEqual(session.revoked_at, now)
        self.assertEqual(session.revocation_reason, SYNC_TRUST_REVOKED_REASON)
        self.assertIsNone(session.weave_access_token_encrypted)
        self.assertIsNone(session.weave_refresh_token_encrypted)
        self.assertEqual(refresh.revoked_at, now)


class TimingPolicyTests(unittest.TestCase):
    def test_degraded_access_reuses_observed_weave_window_and_never_crosses_hard_expiry(
        self,
    ):
        now = datetime.now(UTC)
        actor = _teacher_actor()
        session = _session(actor, now=now)
        session.weave_access_token_issued_at = now - timedelta(minutes=10)
        session.weave_access_token_expires_at = now + timedelta(minutes=10)
        session.expires_at = now + timedelta(minutes=12)

        expiry = LocalAuthService._degraded_access_expiry(
            session=session,
            now=now,
        )

        self.assertEqual(expiry, session.expires_at)


if __name__ == "__main__":
    unittest.main()
