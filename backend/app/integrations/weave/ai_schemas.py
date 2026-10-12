"""Typed transport contracts for CBT AI quota and payment calls to Weave Cloud."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AIQuotaActorType = Literal["teacher", "tenant_admin"]
AIQuotaRequestStatus = Literal["pending", "approved", "rejected", "cancelled"]
AIQuotaPurchaseStatus = Literal["pending", "success", "failed", "cancelled"]

MAX_QUOTA_ADMIN_NOTE_LENGTH = 2_000


class WeaveAIQuotaSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class AIQuotaRequestCreate(WeaveAIQuotaSchema):
    credits: int = Field(gt=0)


class AIQuotaRequestApprove(WeaveAIQuotaSchema):
    approved_credits: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=MAX_QUOTA_ADMIN_NOTE_LENGTH)


class AIQuotaRequestReject(WeaveAIQuotaSchema):
    note: str | None = Field(default=None, max_length=MAX_QUOTA_ADMIN_NOTE_LENGTH)


class AICreditAllocationCreate(WeaveAIQuotaSchema):
    recipient_actor_type: AIQuotaActorType
    recipient_actor_id: UUID
    credits: int = Field(gt=0)


class AIQuotaTopUpRequest(WeaveAIQuotaSchema):
    credits: int = Field(gt=0)


class AIWeeklyQuotaStatus(WeaveAIQuotaSchema):
    week_start: date
    credit_limit: int = Field(ge=0)
    used_credits: int = Field(ge=0)
    reserved_credits: int = Field(ge=0)
    available_credits: int = Field(ge=0)


class AIExtraCreditStatus(WeaveAIQuotaSchema):
    balance_credits: int = Field(ge=0)
    reserved_credits: int = Field(ge=0)
    available_credits: int = Field(ge=0)


class AIQuotaStatusResponse(WeaveAIQuotaSchema):
    quota_account_id: UUID
    actor_type: AIQuotaActorType
    actor_id: UUID
    weekly: AIWeeklyQuotaStatus
    extra: AIExtraCreditStatus
    total_available_credits: int = Field(ge=0)


class AIQuotaRequestResponse(WeaveAIQuotaSchema):
    id: UUID
    requester_quota_account_id: UUID
    requested_credits: int = Field(gt=0)
    approved_credits: int | None = Field(default=None, gt=0)
    status: AIQuotaRequestStatus
    reviewed_by_admin_id: UUID | None = None
    allocation_id: UUID | None = None
    admin_note: str | None = None
    requester_name: str | None = None
    requester_email: str | None = None
    reviewer_email: str | None = None
    created_at: datetime
    reviewed_at: datetime | None = None
    cancelled_at: datetime | None = None


class AIQuotaRequestListResponse(WeaveAIQuotaSchema):
    items: list[AIQuotaRequestResponse]
    total: int = Field(ge=0)


class AIActorQuotaBalance(WeaveAIQuotaSchema):
    quota_account_id: UUID
    actor_type: AIQuotaActorType
    actor_id: UUID
    display_name: str
    email: str | None = None
    weekly_available_credits: int = Field(ge=0)
    weekly_used_credits: int = Field(ge=0)
    extra_available_credits: int = Field(ge=0)
    total_available_credits: int = Field(ge=0)


class AIActorQuotaBalanceListResponse(WeaveAIQuotaSchema):
    items: list[AIActorQuotaBalance]
    total: int = Field(ge=0)


class AITenantQuotaSummaryResponse(WeaveAIQuotaSchema):
    tenant_reserve_credits: int = Field(ge=0)
    quota_actor_count: int = Field(ge=0)
    pending_request_count: int = Field(ge=0)
    personal_extra_balance_total: int = Field(ge=0)
    personal_extra_reserved_total: int = Field(ge=0)


class AICreditAllocationResponse(WeaveAIQuotaSchema):
    id: UUID
    recipient_quota_account_id: UUID
    recipient_actor_type: AIQuotaActorType
    recipient_actor_id: UUID
    recipient_name: str | None = None
    recipient_email: str | None = None
    allocated_by_admin_id: UUID
    allocator_email: str | None = None
    credits: int = Field(gt=0)
    created_at: datetime


class AICreditAllocationListResponse(WeaveAIQuotaSchema):
    items: list[AICreditAllocationResponse]
    total: int = Field(ge=0)


class AIQuotaPurchaseResponse(WeaveAIQuotaSchema):
    id: UUID
    credits: int = Field(gt=0)
    amount_kobo: int = Field(gt=0)
    reference: str
    status: AIQuotaPurchaseStatus
    initiated_by_admin_id: UUID
    initiated_by_email: str | None = None
    created_at: datetime
    credited_at: datetime | None = None


class AIQuotaPurchaseListResponse(WeaveAIQuotaSchema):
    items: list[AIQuotaPurchaseResponse]
    total: int = Field(ge=0)


class AIQuotaPurchaseQuote(WeaveAIQuotaSchema):
    credits: int = Field(gt=0)
    unit_price_kobo: int = Field(gt=0)
    amount_kobo: int = Field(gt=0)
    currency: str = "NGN"


class AIQuotaPurchaseCheckoutResponse(WeaveAIQuotaSchema):
    purchase: AIQuotaPurchaseResponse
    quote: AIQuotaPurchaseQuote
    authorization_url: str
    access_code: str
