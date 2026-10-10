"""CBT machine-scoped WEAVE DNS-01 certificate challenge contract."""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from app.integrations.weave.client import WeaveClient, weave_client
from app.integrations.weave.exceptions import WeaveContractError

BASE = "/api/v1/cbt"
VALID_HOSTNAME = re.compile(
    r"[a-z0-9-]+\.[a-z0-9-]+\.cbt(?:-staging)?\.weavecloudspace\.com\Z"
)


class MachineHostname(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    server_id: UUID
    hostname: str


class MachineDNSChallenge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    hostname: str
    fqdn: str
    status: str
    expires_at: datetime
    ttl: int


def verify_hostname(value: str) -> str:
    if not VALID_HOSTNAME.fullmatch(value):
        raise WeaveContractError("WEAVE supplied an invalid CBT DNS hostname")
    return value


class WeaveCertificateGateway:
    def __init__(self, client: WeaveClient = weave_client) -> None:
        self.client = client

    async def hostname(self, *, credential: SecretStr, server_id: UUID) -> str:
        data = await self.client.request_authenticated(
            "GET", f"{BASE}/server/hostname", server_credential=credential
        )
        try:
            response = MachineHostname.model_validate(data)
        except ValidationError:
            raise WeaveContractError(
                "Invalid CBT hostname response from WEAVE"
            ) from None
        if response.server_id != server_id:
            raise WeaveContractError("CBT hostname identity mismatch")
        return verify_hostname(response.hostname)

    async def create(
        self, *, credential: SecretStr, request_id: UUID, value: str, hostname: str
    ) -> MachineDNSChallenge:
        verify_hostname(hostname)
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
            raise WeaveContractError("Invalid ACME DNS-01 validation digest")
        data = await self.client.request_authenticated(
            "POST",
            f"{BASE}/certificates/dns-challenges",
            server_credential=credential,
            json={"request_id": str(request_id), "value": value},
        )
        try:
            response = MachineDNSChallenge.model_validate(data)
        except ValidationError:
            raise WeaveContractError(
                "Invalid DNS challenge response from WEAVE"
            ) from None
        if (
            response.hostname != hostname
            or response.fqdn != "_acme-challenge." + hostname
        ):
            raise WeaveContractError("DNS challenge hostname mismatch")
        return response

    async def remove(self, *, credential: SecretStr, challenge_id: UUID) -> None:
        await self.client.request_authenticated(
            "DELETE",
            f"{BASE}/certificates/dns-challenges/{challenge_id}",
            server_credential=credential,
        )


weave_certificate_gateway = WeaveCertificateGateway()
