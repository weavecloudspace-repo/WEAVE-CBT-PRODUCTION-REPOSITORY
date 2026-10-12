# =========================== #
#       auth/schemas.py       #
# =========================== #

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

CloudAuthState = Literal[
    "legacy",
    "synced",
    "degraded",
    "refresh_pending",
    "revoked",
]


class StaffLoginRequest(BaseModel):
    """Credentials entered by a teacher/admin into the local CBT."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class LocalActorResponse(BaseModel):
    """Safe local actor representation returned to the frontend."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    role: Literal["admin", "teacher"]
    email: EmailStr
    display_name: str


class StaffLoginResponse(BaseModel):
    """Successful local CBT login or refresh."""

    access_token: str
    access_token_expires_at: datetime
    session_expires_at: datetime
    cloud_auth_state: CloudAuthState
    token_type: Literal["bearer"] = "bearer"
    actor: LocalActorResponse


class StaffSessionResponse(BaseModel):
    """Current authoritative local session status for the staff frontend."""

    actor: LocalActorResponse
    cloud_access_token_expires_at: datetime | None
    session_expires_at: datetime
    cloud_auth_state: CloudAuthState
    cloud_access_available: bool
