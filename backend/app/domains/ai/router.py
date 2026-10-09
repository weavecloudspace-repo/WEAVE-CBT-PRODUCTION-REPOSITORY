"""Protected local CBT routes for Weave-backed AI quota and payment management."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.core.database import DbSession
from app.domains.ai.schemas import (
    AIActorQuotaBalanceListResponse,
    AICreditAllocationCreate,
    AICreditAllocationListResponse,
    AICreditAllocationResponse,
    AIQuotaPurchaseCheckoutResponse,
    AIQuotaPurchaseListResponse,
    AIQuotaPurchaseQuote,
    AIQuotaPurchaseResponse,
    AIQuotaPurchaseStatus,
    AIQuotaRequestApprove,
    AIQuotaRequestCreate,
    AIQuotaRequestListResponse,
    AIQuotaRequestReject,
    AIQuotaRequestResponse,
    AIQuotaRequestStatus,
    AIQuotaStatusResponse,
    AIQuotaTopUpRequest,
    AITenantQuotaSummaryResponse,
)
from app.domains.ai.service import cbt_ai_management_service
from app.domains.auth.dependencies import CurrentLocalContext, LocalActorContext

router = APIRouter(prefix="/ai", tags=["AI Management"])


def _require_admin(context: LocalActorContext) -> None:
    if context.actor.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="School administrator access required.",
        )


@router.get("/quota", response_model=AIQuotaStatusResponse)
async def get_my_quota(
    db: DbSession,
    context: CurrentLocalContext,
) -> AIQuotaStatusResponse:
    return await cbt_ai_management_service.get_quota(
        db,
        session_id=context.session.id,
    )


@router.post("/quota/requests", response_model=AIQuotaRequestResponse)
async def request_credits(
    payload: AIQuotaRequestCreate,
    db: DbSession,
    context: CurrentLocalContext,
) -> AIQuotaRequestResponse:
    return await cbt_ai_management_service.request_credits(
        db,
        session_id=context.session.id,
        payload=payload,
    )


@router.get("/quota/requests", response_model=AIQuotaRequestListResponse)
async def list_my_credit_requests(
    db: DbSession,
    context: CurrentLocalContext,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AIQuotaRequestListResponse:
    return await cbt_ai_management_service.list_my_requests(
        db,
        session_id=context.session.id,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/quota/requests/{request_id}/cancel", response_model=AIQuotaRequestResponse
)
async def cancel_my_credit_request(
    request_id: UUID,
    db: DbSession,
    context: CurrentLocalContext,
) -> AIQuotaRequestResponse:
    return await cbt_ai_management_service.cancel_request(
        db,
        session_id=context.session.id,
        request_id=request_id,
    )


@router.get("/admin/quota/summary", response_model=AITenantQuotaSummaryResponse)
async def get_tenant_quota_summary(
    db: DbSession,
    context: CurrentLocalContext,
) -> AITenantQuotaSummaryResponse:
    _require_admin(context)
    return await cbt_ai_management_service.get_admin_summary(
        db,
        session_id=context.session.id,
    )


@router.get("/admin/quota/actors", response_model=AIActorQuotaBalanceListResponse)
async def list_actor_quota_balances(
    db: DbSession,
    context: CurrentLocalContext,
) -> AIActorQuotaBalanceListResponse:
    _require_admin(context)
    return await cbt_ai_management_service.list_actor_balances(
        db,
        session_id=context.session.id,
    )


@router.get("/admin/quota/requests", response_model=AIQuotaRequestListResponse)
async def list_credit_requests(
    db: DbSession,
    context: CurrentLocalContext,
    request_status: Annotated[
        AIQuotaRequestStatus | None, Query(alias="status")
    ] = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AIQuotaRequestListResponse:
    _require_admin(context)
    return await cbt_ai_management_service.list_admin_requests(
        db,
        session_id=context.session.id,
        status=request_status,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/admin/quota/requests/{request_id}/approve",
    response_model=AIQuotaRequestResponse,
)
async def approve_credit_request(
    request_id: UUID,
    payload: AIQuotaRequestApprove,
    db: DbSession,
    context: CurrentLocalContext,
) -> AIQuotaRequestResponse:
    _require_admin(context)
    return await cbt_ai_management_service.approve_request(
        db,
        session_id=context.session.id,
        request_id=request_id,
        payload=payload,
    )


@router.post(
    "/admin/quota/requests/{request_id}/reject",
    response_model=AIQuotaRequestResponse,
)
async def reject_credit_request(
    request_id: UUID,
    payload: AIQuotaRequestReject,
    db: DbSession,
    context: CurrentLocalContext,
) -> AIQuotaRequestResponse:
    _require_admin(context)
    return await cbt_ai_management_service.reject_request(
        db,
        session_id=context.session.id,
        request_id=request_id,
        payload=payload,
    )


@router.post("/admin/quota/allocations", response_model=AICreditAllocationResponse)
async def allocate_credits(
    payload: AICreditAllocationCreate,
    db: DbSession,
    context: CurrentLocalContext,
) -> AICreditAllocationResponse:
    _require_admin(context)
    return await cbt_ai_management_service.allocate_credits(
        db,
        session_id=context.session.id,
        payload=payload,
    )


@router.get("/admin/quota/allocations", response_model=AICreditAllocationListResponse)
async def list_credit_allocations(
    db: DbSession,
    context: CurrentLocalContext,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AICreditAllocationListResponse:
    _require_admin(context)
    return await cbt_ai_management_service.list_allocations(
        db,
        session_id=context.session.id,
        offset=offset,
        limit=limit,
    )


@router.post("/admin/quota/purchases/quote", response_model=AIQuotaPurchaseQuote)
async def quote_credit_purchase(
    payload: AIQuotaTopUpRequest,
    db: DbSession,
    context: CurrentLocalContext,
) -> AIQuotaPurchaseQuote:
    _require_admin(context)
    return await cbt_ai_management_service.quote_purchase(
        db,
        session_id=context.session.id,
        payload=payload,
    )


@router.post(
    "/admin/quota/purchases/checkout",
    response_model=AIQuotaPurchaseCheckoutResponse,
)
async def initialize_credit_purchase(
    payload: AIQuotaTopUpRequest,
    db: DbSession,
    context: CurrentLocalContext,
) -> AIQuotaPurchaseCheckoutResponse:
    _require_admin(context)
    return await cbt_ai_management_service.checkout_purchase(
        db,
        session_id=context.session.id,
        payload=payload,
    )


@router.post(
    "/admin/quota/purchases/{reference}/verify",
    response_model=AIQuotaPurchaseResponse,
)
async def verify_credit_purchase(
    reference: str,
    db: DbSession,
    context: CurrentLocalContext,
) -> AIQuotaPurchaseResponse:
    _require_admin(context)
    return await cbt_ai_management_service.verify_purchase(
        db,
        session_id=context.session.id,
        reference=reference,
    )


@router.get("/admin/quota/purchases", response_model=AIQuotaPurchaseListResponse)
async def list_credit_purchases(
    db: DbSession,
    context: CurrentLocalContext,
    purchase_status: Annotated[
        AIQuotaPurchaseStatus | None, Query(alias="status")
    ] = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AIQuotaPurchaseListResponse:
    _require_admin(context)
    return await cbt_ai_management_service.list_purchases(
        db,
        session_id=context.session.id,
        status=purchase_status,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/admin/quota/purchases/{purchase_id}", response_model=AIQuotaPurchaseResponse
)
async def get_credit_purchase(
    purchase_id: UUID,
    db: DbSession,
    context: CurrentLocalContext,
) -> AIQuotaPurchaseResponse:
    _require_admin(context)
    return await cbt_ai_management_service.get_purchase(
        db,
        session_id=context.session.id,
        purchase_id=purchase_id,
    )
