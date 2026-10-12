"""Actor-authenticated Weave Cloud gateway for CBT AI quota and payments."""

from __future__ import annotations

from typing import TypeVar
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, SecretStr, ValidationError

from app.integrations.weave.ai_schemas import (
    AIActorQuotaBalanceListResponse,
    AICreditAllocationCreate,
    AICreditAllocationListResponse,
    AICreditAllocationResponse,
    AIQuotaPurchaseCheckoutResponse,
    AIQuotaPurchaseListResponse,
    AIQuotaPurchaseQuote,
    AIQuotaPurchaseResponse,
    AIQuotaRequestApprove,
    AIQuotaRequestCreate,
    AIQuotaRequestListResponse,
    AIQuotaRequestReject,
    AIQuotaRequestResponse,
    AIQuotaStatusResponse,
    AIQuotaTopUpRequest,
    AITenantQuotaSummaryResponse,
)
from app.integrations.weave.client import WeaveClient, weave_client
from app.integrations.weave.exceptions import WeaveContractError

ResponseT = TypeVar("ResponseT", bound=BaseModel)
AI_PATH = "/api/v1/cbt/ai"


class WeaveAIGateway:
    """Own all CBT -> Weave transport details for non-authoring AI workflows."""

    def __init__(self, client: WeaveClient = weave_client) -> None:
        self.client = client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        response_model: type[ResponseT],
        server_credential: SecretStr,
        actor_access_token: str,
        json: dict | None = None,
        params: dict | None = None,
    ) -> ResponseT:
        payload = await self.client.request_actor_authenticated(
            method,
            f"{AI_PATH}{path}",
            server_credential=server_credential,
            actor_access_token=actor_access_token,
            json=json,
            params=params,
        )
        try:
            return response_model.model_validate(payload)
        except ValidationError as exc:
            raise WeaveContractError(
                f"Weave returned an invalid CBT AI response for {path}."
            ) from exc

    async def get_quota(
        self,
        *,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AIQuotaStatusResponse:
        return await self._request(
            "GET",
            "/quota",
            response_model=AIQuotaStatusResponse,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
        )

    async def request_credits(
        self,
        *,
        payload: AIQuotaRequestCreate,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AIQuotaRequestResponse:
        return await self._request(
            "POST",
            "/quota/requests",
            response_model=AIQuotaRequestResponse,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
            json=payload.model_dump(mode="json"),
        )

    async def list_my_requests(
        self,
        *,
        offset: int,
        limit: int,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AIQuotaRequestListResponse:
        return await self._request(
            "GET",
            "/quota/requests",
            response_model=AIQuotaRequestListResponse,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
            params={"offset": offset, "limit": limit},
        )

    async def cancel_request(
        self,
        *,
        request_id: UUID,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AIQuotaRequestResponse:
        return await self._request(
            "POST",
            f"/quota/requests/{request_id}/cancel",
            response_model=AIQuotaRequestResponse,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
        )

    async def get_admin_summary(
        self,
        *,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AITenantQuotaSummaryResponse:
        return await self._request(
            "GET",
            "/admin/quota/summary",
            response_model=AITenantQuotaSummaryResponse,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
        )

    async def list_actor_balances(
        self,
        *,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AIActorQuotaBalanceListResponse:
        return await self._request(
            "GET",
            "/admin/quota/actors",
            response_model=AIActorQuotaBalanceListResponse,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
        )

    async def list_admin_requests(
        self,
        *,
        status: str | None,
        offset: int,
        limit: int,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AIQuotaRequestListResponse:
        params = {"offset": offset, "limit": limit}
        if status is not None:
            params["status"] = status
        return await self._request(
            "GET",
            "/admin/quota/requests",
            response_model=AIQuotaRequestListResponse,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
            params=params,
        )

    async def approve_request(
        self,
        *,
        request_id: UUID,
        payload: AIQuotaRequestApprove,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AIQuotaRequestResponse:
        return await self._request(
            "POST",
            f"/admin/quota/requests/{request_id}/approve",
            response_model=AIQuotaRequestResponse,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
            json=payload.model_dump(mode="json"),
        )

    async def reject_request(
        self,
        *,
        request_id: UUID,
        payload: AIQuotaRequestReject,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AIQuotaRequestResponse:
        return await self._request(
            "POST",
            f"/admin/quota/requests/{request_id}/reject",
            response_model=AIQuotaRequestResponse,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
            json=payload.model_dump(mode="json"),
        )

    async def allocate_credits(
        self,
        *,
        payload: AICreditAllocationCreate,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AICreditAllocationResponse:
        return await self._request(
            "POST",
            "/admin/quota/allocations",
            response_model=AICreditAllocationResponse,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
            json=payload.model_dump(mode="json"),
        )

    async def list_allocations(
        self,
        *,
        offset: int,
        limit: int,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AICreditAllocationListResponse:
        return await self._request(
            "GET",
            "/admin/quota/allocations",
            response_model=AICreditAllocationListResponse,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
            params={"offset": offset, "limit": limit},
        )

    async def quote_purchase(
        self,
        *,
        payload: AIQuotaTopUpRequest,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AIQuotaPurchaseQuote:
        return await self._request(
            "POST",
            "/admin/quota/purchases/quote",
            response_model=AIQuotaPurchaseQuote,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
            json=payload.model_dump(mode="json"),
        )

    async def checkout_purchase(
        self,
        *,
        payload: AIQuotaTopUpRequest,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AIQuotaPurchaseCheckoutResponse:
        return await self._request(
            "POST",
            "/admin/quota/purchases/checkout",
            response_model=AIQuotaPurchaseCheckoutResponse,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
            json=payload.model_dump(mode="json"),
        )

    async def verify_purchase(
        self,
        *,
        reference: str,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AIQuotaPurchaseResponse:
        encoded_reference = quote(reference, safe="")
        return await self._request(
            "POST",
            f"/admin/quota/purchases/{encoded_reference}/verify",
            response_model=AIQuotaPurchaseResponse,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
        )

    async def list_purchases(
        self,
        *,
        status: str | None,
        offset: int,
        limit: int,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AIQuotaPurchaseListResponse:
        params = {"offset": offset, "limit": limit}
        if status is not None:
            params["status"] = status
        return await self._request(
            "GET",
            "/admin/quota/purchases",
            response_model=AIQuotaPurchaseListResponse,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
            params=params,
        )

    async def get_purchase(
        self,
        *,
        purchase_id: UUID,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AIQuotaPurchaseResponse:
        return await self._request(
            "GET",
            f"/admin/quota/purchases/{purchase_id}",
            response_model=AIQuotaPurchaseResponse,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
        )


weave_ai_gateway = WeaveAIGateway()
