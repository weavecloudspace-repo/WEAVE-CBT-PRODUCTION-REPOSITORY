"""Current Weave Cloud contracts used by CBT staff authentication."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


class WeaveStaffLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class WeaveActorRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(..., min_length=32, max_length=512)


class WeaveActorTokenPair(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    access_token: SecretStr
    access_token_expires_at: datetime
    refresh_token: SecretStr
    refresh_token_expires_at: datetime
    token_type: Literal["Bearer"] = "Bearer"


class WeaveStaffAuthResult(WeaveActorTokenPair):
    actor_id: UUID
    membership_id: UUID | None = None
    tenant_id: UUID
    role: Literal["admin", "teacher"]
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
