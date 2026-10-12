"""Weave Cloud gateway for academic bootstrap and durable delta recovery."""

from __future__ import annotations

from pydantic import SecretStr, ValidationError

from app.integrations.weave.client import WeaveClient, weave_client
from app.integrations.weave.exceptions import WeaveContractError
from app.integrations.weave.schemas import WeaveAcademicBootstrap, WeaveSyncDelta

ACADEMIC_BOOTSTRAP_PATH = "/api/v1/cbt/academics/bootstrap"
SYNC_CHANGES_PATH = "/api/v1/cbt/sync/changes"
SYNC_STREAM_PATH = "/api/v1/cbt/sync/stream"


class WeaveAcademicsGateway:
    def __init__(self, client: WeaveClient = weave_client) -> None:
        self.client = client

    async def fetch_bootstrap(
        self,
        *,
        server_credential: SecretStr,
    ) -> WeaveAcademicBootstrap:
        payload = await self.client.request_authenticated(
            "GET",
            ACADEMIC_BOOTSTRAP_PATH,
            server_credential=server_credential,
        )
        try:
            return WeaveAcademicBootstrap.model_validate(payload)
        except ValidationError as exc:
            raise WeaveContractError(
                "Weave returned an invalid CBT academic bootstrap payload."
            ) from exc

    async def fetch_changes(
        self,
        *,
        server_credential: SecretStr,
        after_cursor: int,
        limit: int = 500,
    ) -> WeaveSyncDelta:
        payload = await self.client.request_authenticated(
            "GET",
            SYNC_CHANGES_PATH,
            server_credential=server_credential,
            params={"after": after_cursor, "limit": limit},
        )
        try:
            return WeaveSyncDelta.model_validate(payload)
        except ValidationError as exc:
            raise WeaveContractError(
                "Weave returned an invalid CBT synchronization delta."
            ) from exc

    def stream_url(self) -> str:
        return self.client.build_websocket_url(SYNC_STREAM_PATH)


weave_academics_gateway = WeaveAcademicsGateway()
