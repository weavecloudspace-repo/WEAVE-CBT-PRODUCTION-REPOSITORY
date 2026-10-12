# ==================================== #
# app.integrations.weave.auth
# ==================================== #

"""Weave Cloud staff authentication integration."""

from uuid import UUID

from pydantic import SecretStr, ValidationError

from app.integrations.weave.auth_schemas import (
    WeaveActorRefreshRequest,
    WeaveActorTokenPair,
    WeaveStaffAuthResult,
    WeaveStaffLoginRequest,
)
from app.integrations.weave.client import WeaveClient, weave_client
from app.integrations.weave.exceptions import WeaveContractError


class WeaveAuthGateway:
    """Domain-specific gateway for staff authentication against Weave Cloud."""

    def __init__(self, client: WeaveClient) -> None:
        self.client = client

    async def authenticate_staff(
        self,
        *,
        payload: WeaveStaffLoginRequest,
        server_credential: SecretStr,
    ) -> WeaveStaffAuthResult:
        response = await self.client.request_authenticated(
            "POST",
            "/api/v1/cbt/auth/staff/login",
            server_credential=server_credential,
            json=payload.model_dump(mode="json"),
        )
        try:
            return WeaveStaffAuthResult.model_validate(response)
        except ValidationError as exc:
            raise WeaveContractError(
                "Weave returned an invalid staff authentication response."
            ) from exc

    async def refresh_staff_authorization(
        self,
        *,
        refresh_token: str,
        idempotency_key: UUID,
        server_credential: SecretStr,
    ) -> WeaveActorTokenPair:
        response = await self.client.request_authenticated(
            "POST",
            "/api/v1/cbt/auth/staff/refresh",
            server_credential=server_credential,
            json=WeaveActorRefreshRequest(
                refresh_token=refresh_token,
            ).model_dump(mode="json"),
            headers={"Idempotency-Key": str(idempotency_key)},
        )
        try:
            return WeaveActorTokenPair.model_validate(response)
        except ValidationError as exc:
            raise WeaveContractError(
                "Weave returned an invalid staff authorization refresh response."
            ) from exc


weave_auth_gateway = WeaveAuthGateway(client=weave_client)
