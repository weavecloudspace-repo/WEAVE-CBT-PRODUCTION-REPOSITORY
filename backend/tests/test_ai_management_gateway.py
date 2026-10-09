from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from pydantic import SecretStr

from app.integrations.weave.ai import WeaveAIGateway
from app.integrations.weave.ai_schemas import (
    AIQuotaRequestCreate,
    AIQuotaTopUpRequest,
)
from app.integrations.weave.exceptions import WeaveContractError


class WeaveAIGatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = AsyncMock()
        self.gateway = WeaveAIGateway(client=self.client)
        self.server_credential = SecretStr("server-secret")
        self.actor_token = "actor-access-token"

    async def test_get_quota_uses_dual_actor_auth_and_validates_response(self):
        account_id = uuid4()
        actor_id = uuid4()
        self.client.request_actor_authenticated.return_value = {
            "quota_account_id": str(account_id),
            "actor_type": "teacher",
            "actor_id": str(actor_id),
            "weekly": {
                "week_start": datetime.now(UTC).date().isoformat(),
                "credit_limit": 100,
                "used_credits": 20,
                "reserved_credits": 10,
                "available_credits": 70,
            },
            "extra": {
                "balance_credits": 40,
                "reserved_credits": 5,
                "available_credits": 35,
            },
            "total_available_credits": 105,
        }

        result = await self.gateway.get_quota(
            server_credential=self.server_credential,
            actor_access_token=self.actor_token,
        )

        self.assertEqual(result.quota_account_id, account_id)
        self.assertEqual(result.total_available_credits, 105)
        self.client.request_actor_authenticated.assert_awaited_once_with(
            "GET",
            "/api/v1/cbt/ai/quota",
            server_credential=self.server_credential,
            actor_access_token=self.actor_token,
            json=None,
            params=None,
        )

    async def test_request_credits_forwards_only_expected_payload(self):
        request_id = uuid4()
        account_id = uuid4()
        created_at = datetime.now(UTC)
        self.client.request_actor_authenticated.return_value = {
            "id": str(request_id),
            "requester_quota_account_id": str(account_id),
            "requested_credits": 250,
            "approved_credits": None,
            "status": "pending",
            "reviewed_by_admin_id": None,
            "allocation_id": None,
            "admin_note": None,
            "requester_name": "Teacher One",
            "requester_email": "teacher@example.com",
            "reviewer_email": None,
            "created_at": created_at.isoformat(),
            "reviewed_at": None,
            "cancelled_at": None,
        }

        result = await self.gateway.request_credits(
            payload=AIQuotaRequestCreate(credits=250),
            server_credential=self.server_credential,
            actor_access_token=self.actor_token,
        )

        self.assertEqual(result.requested_credits, 250)
        call = self.client.request_actor_authenticated.await_args
        self.assertEqual(call.args, ("POST", "/api/v1/cbt/ai/quota/requests"))
        self.assertEqual(call.kwargs["json"], {"credits": 250})
        self.assertEqual(call.kwargs["actor_access_token"], self.actor_token)

    async def test_purchase_checkout_contract_is_validated(self):
        purchase_id = uuid4()
        admin_id = uuid4()
        now = datetime.now(UTC)
        self.client.request_actor_authenticated.return_value = {
            "purchase": {
                "id": str(purchase_id),
                "credits": 1000,
                "amount_kobo": 2_000_000,
                "reference": "AI-REF-1",
                "status": "pending",
                "initiated_by_admin_id": str(admin_id),
                "initiated_by_email": "admin@example.com",
                "created_at": now.isoformat(),
                "credited_at": None,
            },
            "quote": {
                "credits": 1000,
                "unit_price_kobo": 2000,
                "amount_kobo": 2_000_000,
                "currency": "NGN",
            },
            "authorization_url": "https://checkout.example/AI-REF-1",
            "access_code": "access-code",
        }

        result = await self.gateway.checkout_purchase(
            payload=AIQuotaTopUpRequest(credits=1000),
            server_credential=self.server_credential,
            actor_access_token=self.actor_token,
        )

        self.assertEqual(result.purchase.id, purchase_id)
        self.assertEqual(result.quote.amount_kobo, 2_000_000)
        call = self.client.request_actor_authenticated.await_args
        self.assertEqual(
            call.args,
            ("POST", "/api/v1/cbt/ai/admin/quota/purchases/checkout"),
        )
        self.assertEqual(call.kwargs["json"], {"credits": 1000})

    async def test_invalid_upstream_shape_fails_closed(self):
        self.client.request_actor_authenticated.return_value = {
            "total_available_credits": -1,
        }

        with self.assertRaises(WeaveContractError):
            await self.gateway.get_quota(
                server_credential=self.server_credential,
                actor_access_token=self.actor_token,
            )


if __name__ == "__main__":
    unittest.main()
