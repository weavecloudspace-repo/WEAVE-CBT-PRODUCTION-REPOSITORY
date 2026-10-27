"""Weave Cloud gateway for CBT result ingestion."""

from __future__ import annotations

from pydantic import SecretStr, ValidationError

from app.integrations.weave.client import WeaveClient, weave_client
from app.integrations.weave.exceptions import WeaveContractError
from app.domains.results.rollback_schemas import CloudRollbackResponse
from uuid import UUID
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


    async def request_rollback(
        self, *, operation_id: UUID, batch_id: UUID, student_ids: list[UUID],
        reason: str, server_credential: SecretStr, actor_access_token: str,
    ) -> CloudRollbackResponse:
        data = await self.client.request_actor_authenticated(
            "POST", "/api/v1/cbt/results/rollbacks",
            server_credential=server_credential,
            actor_access_token=actor_access_token,
            json={
                "operation_id": str(operation_id),
                "source_batch_id": str(batch_id),
                "student_ids": [str(student) for student in student_ids],
                "reason": reason,
            },
        )
        try:
            return CloudRollbackResponse.model_validate(data)
        except ValidationError as exc:
            raise WeaveContractError("Cloud returned an invalid rollback acknowledgment") from exc

    async def rollback_status(
        self, *, operation_id: UUID, server_credential: SecretStr,
    ) -> CloudRollbackResponse:
        data = await self.client.request_authenticated(
            "GET", f"/api/v1/cbt/results/rollbacks/{operation_id}",
            server_credential=server_credential,
        )
        try:
            return CloudRollbackResponse.model_validate(data)
        except ValidationError as exc:
            raise WeaveContractError("Cloud returned an invalid rollback status") from exc


weave_result_gateway = WeaveResultGateway()
