from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from pydantic import SecretStr

from app.domains.ai.service import CBTAIManagementService
from app.domains.auth.service import LocalSessionAuthenticationError
from app.integrations.weave.ai_schemas import AIQuotaRequestCreate
from app.integrations.weave.exceptions import WeaveRequestRejectedError


class CBTAIManagementServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cloud_credentials_are_resolved_only_on_backend(self):
        db = AsyncMock()
        session_id = uuid4()
        installation = SimpleNamespace(
            server_credential=SecretStr("server-secret"),
        )

        with (
            patch(
                "app.domains.ai.service.node_identity_store.load",
                return_value=installation,
            ),
            patch(
                "app.domains.ai.service.get_or_repair_weave_actor_access_token",
                new=AsyncMock(return_value="weave-actor-token"),
            ) as get_actor_token,
        ):
            (
                server_credential,
                actor_token,
            ) = await CBTAIManagementService._cloud_credentials(
                db,
                session_id=session_id,
            )

        self.assertIs(server_credential, installation.server_credential)
        self.assertEqual(actor_token, "weave-actor-token")
        get_actor_token.assert_awaited_once_with(db, session_id=session_id)

    async def test_invalid_cloud_auth_is_exposed_as_local_reauthentication(self):
        db = AsyncMock()
        session_id = uuid4()
        installation = SimpleNamespace(
            server_credential=SecretStr("server-secret"),
        )

        with (
            patch(
                "app.domains.ai.service.node_identity_store.load",
                return_value=installation,
            ),
            patch(
                "app.domains.ai.service.get_or_repair_weave_actor_access_token",
                new=AsyncMock(
                    side_effect=LocalSessionAuthenticationError(
                        "Local staff session is invalid or expired."
                    )
                ),
            ),
            self.assertRaises(WeaveRequestRejectedError) as captured,
        ):
            await CBTAIManagementService._cloud_credentials(
                db,
                session_id=session_id,
            )

        self.assertEqual(captured.exception.status_code, 401)
        self.assertEqual(
            captured.exception.detail,
            "Staff session requires reauthentication.",
        )

    async def test_request_credits_passes_internal_credentials_to_gateway(self):
        db = AsyncMock()
        session_id = uuid4()
        gateway = AsyncMock()
        gateway.request_credits.return_value = SimpleNamespace(id=uuid4())
        service = CBTAIManagementService(gateway=gateway)
        payload = AIQuotaRequestCreate(credits=75)

        with patch.object(
            CBTAIManagementService,
            "_cloud_credentials",
            new=AsyncMock(return_value=(SecretStr("server-secret"), "actor-token")),
        ):
            result = await service.request_credits(
                db,
                session_id=session_id,
                payload=payload,
            )

        self.assertIs(result, gateway.request_credits.return_value)
        gateway.request_credits.assert_awaited_once()
        kwargs = gateway.request_credits.await_args.kwargs
        self.assertIs(kwargs["payload"], payload)
        self.assertEqual(kwargs["actor_access_token"], "actor-token")
        self.assertEqual(
            kwargs["server_credential"].get_secret_value(),
            "server-secret",
        )


if __name__ == "__main__":
    unittest.main()
