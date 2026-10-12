# ============================================#
# backend.app.integrations.weave.installation
# ============================================#


from pydantic import ValidationError

from app.integrations.weave.client import (
    WeaveClient,
    weave_client,
)
from app.integrations.weave.exceptions import (
    WeaveContractError,
)
from app.integrations.weave.schemas import (
    WeavePairingRequest,
    WeavePairingResult,
)

PAIRING_VERIFY_PATH = "/api/v1/cbt/pairing/verify"


class WeaveInstallationGateway:
    """
    Weave Cloud integration for CBT installation lifecycle operations.

    This layer knows the HTTP contracts and endpoints specific to
    installation pairing.

    It does not own local installation state or persist credentials.
    """

    def __init__(
        self,
        client: WeaveClient = weave_client,
    ) -> None:
        self.client = client

    async def pair(
        self,
        request: WeavePairingRequest,
    ) -> WeavePairingResult:
        """
        Exchange a one-time Weave pairing code for a persistent
        CBT server identity and credential.
        """

        payload = request.model_dump(
            mode="json",
            exclude_none=True,
        )

        response_payload = await self.client.post_public(
            path=PAIRING_VERIFY_PATH,
            payload=payload,
        )

        try:
            return WeavePairingResult.model_validate(response_payload)

        except ValidationError as exc:
            raise WeaveContractError(
                "Weave returned an invalid installation pairing response."
            ) from exc


weave_installation_gateway = WeaveInstallationGateway()
