# ========================== #
# app.domains.node.schemas
# ========================== #

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class StoredNodeIdentity(BaseModel):
    """
    Persistent machine identity for this CBT installation.

    This is sensitive internal state.

    It must never be returned directly from an API endpoint because
    it contains the Weave-issued server credential.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    format_version: Literal[1] = 1

    server_id: UUID

    server_name: str = Field(
        ...,
        min_length=2,
        max_length=150,
    )

    hostname: str | None = Field(default=None, max_length=253)

    server_credential: SecretStr

    tenant_id: UUID

    tenant_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )

    paired_at: datetime


class InstallationStatus(BaseModel):
    """
    Safe installation state that may be exposed to the frontend.

    The Weave server credential is deliberately absent.
    """

    model_config = ConfigDict(
        frozen=True,
    )

    configured: bool

    server_id: UUID | None = None
    server_name: str | None = None
    hostname: str | None = None

    tenant_id: UUID | None = None
    tenant_name: str | None = None

    paired_at: datetime | None = None


class PairInstallationRequest(BaseModel):
    """
    Data entered by the school administrator on the local CBT setup page.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    pairing_code: str = Field(
        ...,
        min_length=8,
        max_length=20,
    )

    server_name: str = Field(
        ...,
        min_length=2,
        max_length=150,
    )

    @field_validator("pairing_code")
    @classmethod
    def normalize_pairing_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("server_name")
    @classmethod
    def normalize_server_name(cls, value: str) -> str:
        return " ".join(value.split())


class PairInstallationResponse(BaseModel):
    """
    Safe response returned to the local frontend after successful pairing.

    The Weave server credential is intentionally excluded.
    """

    model_config = ConfigDict(
        frozen=True,
    )

    configured: bool = True

    server_id: UUID
    server_name: str
    hostname: str | None = None

    tenant_id: UUID
    tenant_name: str

    paired_at: datetime
