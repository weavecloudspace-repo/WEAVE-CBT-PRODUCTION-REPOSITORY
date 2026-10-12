"""Weave Cloud gateway for the effective CBT tenant-branding projection."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.integrations.weave.client import WeaveClient, weave_client
from app.integrations.weave.exceptions import WeaveContractError

BRANDING_PATH = "/api/v1/cbt/branding"


class WeaveBrandingProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: UUID
    school_name: str
    logo_url: str | None = None
    logo_revision: UUID | None = None
    is_enabled: bool
    is_default_theme: bool
    theme_version: int = Field(ge=0)
    token_schema_version: int = Field(ge=1)
    light_tokens: dict[str, str]
    dark_tokens: dict[str, str]


class WeaveBrandingGateway:
    def __init__(self, client: WeaveClient = weave_client) -> None:
        self.client = client

    async def fetch_branding(
        self,
        *,
        server_credential: SecretStr,
    ) -> WeaveBrandingProjection:
        payload = await self.client.request_authenticated(
            "GET",
            BRANDING_PATH,
            server_credential=server_credential,
        )
        try:
            return WeaveBrandingProjection.model_validate(payload)
        except ValidationError as exc:
            raise WeaveContractError(
                "Weave returned an invalid CBT branding projection."
            ) from exc


weave_branding_gateway = WeaveBrandingGateway()
