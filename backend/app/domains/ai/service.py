"""Application service for cloud-backed CBT AI quota and payment workflows."""

from __future__ import annotations

from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth.cloud_access import get_or_repair_weave_actor_access_token
from app.domains.auth.service import LocalSessionAuthenticationError
from app.domains.node.identity_store import node_identity_store
from app.integrations.weave.ai import WeaveAIGateway, weave_ai_gateway
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
from app.integrations.weave.exceptions import WeaveRequestRejectedError


class CBTAIManagementService:
    """Keep Weave AI accounting authoritative while exposing it through CBT."""

    def __init__(self, gateway: WeaveAIGateway = weave_ai_gateway) -> None:
        self.gateway = gateway

    @staticmethod
    async def _cloud_credentials(
        db: AsyncSession,
        *,
        session_id: UUID,
    ) -> tuple[SecretStr, str]:
        installation = node_identity_store.load()
        try:
            actor_access_token = await get_or_repair_weave_actor_access_token(
                db,
                session_id=session_id,
            )
        except LocalSessionAuthenticationError as exc:
            raise WeaveRequestRejectedError(
                status_code=401,
                detail="Staff session requires reauthentication.",
            ) from exc
        return installation.server_credential, actor_access_token

    async def get_quota(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
    ) -> AIQuotaStatusResponse:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.get_quota(
            server_credential=server_credential,
            actor_access_token=actor_token,
        )

    async def request_credits(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        payload: AIQuotaRequestCreate,
    ) -> AIQuotaRequestResponse:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.request_credits(
            payload=payload,
            server_credential=server_credential,
            actor_access_token=actor_token,
        )

    async def list_my_requests(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        offset: int,
        limit: int,
    ) -> AIQuotaRequestListResponse:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.list_my_requests(
            offset=offset,
            limit=limit,
            server_credential=server_credential,
            actor_access_token=actor_token,
        )

    async def cancel_request(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        request_id: UUID,
    ) -> AIQuotaRequestResponse:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.cancel_request(
            request_id=request_id,
            server_credential=server_credential,
            actor_access_token=actor_token,
        )

    async def get_admin_summary(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
    ) -> AITenantQuotaSummaryResponse:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.get_admin_summary(
            server_credential=server_credential,
            actor_access_token=actor_token,
        )

    async def list_actor_balances(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
    ) -> AIActorQuotaBalanceListResponse:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.list_actor_balances(
            server_credential=server_credential,
            actor_access_token=actor_token,
        )

    async def list_admin_requests(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        status: str | None,
        offset: int,
        limit: int,
    ) -> AIQuotaRequestListResponse:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.list_admin_requests(
            status=status,
            offset=offset,
            limit=limit,
            server_credential=server_credential,
            actor_access_token=actor_token,
        )

    async def approve_request(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        request_id: UUID,
        payload: AIQuotaRequestApprove,
    ) -> AIQuotaRequestResponse:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.approve_request(
            request_id=request_id,
            payload=payload,
            server_credential=server_credential,
            actor_access_token=actor_token,
        )

    async def reject_request(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        request_id: UUID,
        payload: AIQuotaRequestReject,
    ) -> AIQuotaRequestResponse:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.reject_request(
            request_id=request_id,
            payload=payload,
            server_credential=server_credential,
            actor_access_token=actor_token,
        )

    async def allocate_credits(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        payload: AICreditAllocationCreate,
    ) -> AICreditAllocationResponse:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.allocate_credits(
            payload=payload,
            server_credential=server_credential,
            actor_access_token=actor_token,
        )

    async def list_allocations(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        offset: int,
        limit: int,
    ) -> AICreditAllocationListResponse:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.list_allocations(
            offset=offset,
            limit=limit,
            server_credential=server_credential,
            actor_access_token=actor_token,
        )

    async def quote_purchase(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        payload: AIQuotaTopUpRequest,
    ) -> AIQuotaPurchaseQuote:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.quote_purchase(
            payload=payload,
            server_credential=server_credential,
            actor_access_token=actor_token,
        )

    async def checkout_purchase(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        payload: AIQuotaTopUpRequest,
    ) -> AIQuotaPurchaseCheckoutResponse:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.checkout_purchase(
            payload=payload,
            server_credential=server_credential,
            actor_access_token=actor_token,
        )

    async def verify_purchase(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        reference: str,
    ) -> AIQuotaPurchaseResponse:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.verify_purchase(
            reference=reference,
            server_credential=server_credential,
            actor_access_token=actor_token,
        )

    async def list_purchases(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        status: str | None,
        offset: int,
        limit: int,
    ) -> AIQuotaPurchaseListResponse:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.list_purchases(
            status=status,
            offset=offset,
            limit=limit,
            server_credential=server_credential,
            actor_access_token=actor_token,
        )

    async def get_purchase(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        purchase_id: UUID,
    ) -> AIQuotaPurchaseResponse:
        server_credential, actor_token = await self._cloud_credentials(
            db,
            session_id=session_id,
        )
        return await self.gateway.get_purchase(
            purchase_id=purchase_id,
            server_credential=server_credential,
            actor_access_token=actor_token,
        )


cbt_ai_management_service = CBTAIManagementService()
