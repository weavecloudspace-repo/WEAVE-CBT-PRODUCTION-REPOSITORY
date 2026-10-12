"""Weave Cloud gateway for CBT result ingestion."""

from __future__ import annotations

from pydantic import SecretStr, ValidationError

from app.integrations.weave.client import WeaveClient, weave_client
from app.integrations.weave.exceptions import WeaveContractError
from app.integrations.weave.schemas import (
    WeaveResultBulkRequest,
    WeaveResultBulkResponse,
)

RESULT_INGESTION_PATH = "/api/v1/cbt/results"


class WeaveResultGateway:
    """Send locally calculated CBT result batches to Weave Cloud."""

    def __init__(self, client: WeaveClient = weave_client) -> None:
        self.client = client

    async def submit_results(
        self,
        *,
        payload: WeaveResultBulkRequest,
        server_credential: SecretStr,
    ) -> WeaveResultBulkResponse:
        response = await self.client.request_authenticated(
            "POST",
            RESULT_INGESTION_PATH,
            server_credential=server_credential,
            json=payload.model_dump(mode="json"),
        )

        try:
            return WeaveResultBulkResponse.model_validate(response)
        except ValidationError as exc:
            raise WeaveContractError(
                "Weave returned an invalid CBT result ingestion response."
            ) from exc


weave_result_gateway = WeaveResultGateway()
