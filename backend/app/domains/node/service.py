# ========================== #
# app.domains.node.service
# ========================== #

import asyncio

from app.core.security import ensure_local_signing_secret
from app.core.settings import settings
from app.domains.node.exceptions import (
    InstallationAlreadyPairedError,
    NodeIdentityNotFoundError,
)
from app.domains.node.identity_store import (
    NodeIdentityStore,
    node_identity_store,
)
from app.domains.node.schemas import (
    InstallationStatus,
    PairInstallationRequest,
    PairInstallationResponse,
    StoredNodeIdentity,
)
from app.integrations.weave.installation import (
    WeaveInstallationGateway,
    weave_installation_gateway,
)
from app.integrations.weave.schemas import WeavePairingRequest
from app.integrations.weave.certificates import weave_certificate_gateway


class NodeService:
    """
    Application service for the local CBT node lifecycle.

    Owns orchestration of local installation state and communication
    with the Weave installation integration.
    """

    def __init__(
        self,
        identity_store: NodeIdentityStore = node_identity_store,
        installation_gateway: WeaveInstallationGateway = weave_installation_gateway,
    ) -> None:
        self.identity_store = identity_store
        self.installation_gateway = installation_gateway

    def get_installation_status(
        self,
    ) -> InstallationStatus:
        """
        Return safe information about this CBT installation.
        """

        try:
            identity = self.identity_store.load()

        except NodeIdentityNotFoundError:
            return InstallationStatus(
                configured=False,
            )

        return InstallationStatus(
            configured=True,
            server_id=identity.server_id,
            server_name=identity.server_name,
            hostname=identity.hostname,
            tenant_id=identity.tenant_id,
            tenant_name=identity.tenant_name,
            paired_at=identity.paired_at,
        )

    async def refresh_hostname(self) -> InstallationStatus:
        """Recover or refresh the machine's official DNS hostname without re-pairing."""
        async with self.identity_store.pairing_lock():
            identity = self.identity_store.load()
            hostname = await weave_certificate_gateway.hostname(
                credential=identity.server_credential, server_id=identity.server_id
            )
            await asyncio.to_thread(
                self.identity_store.update_hostname,
                server_id=identity.server_id,
                hostname=hostname,
            )
        return self.get_installation_status()

    async def pair_installation(
        self,
        request: PairInstallationRequest,
    ) -> PairInstallationResponse:
        """
        Pair this local CBT installation with Weave Cloud.

        The operation is serialized across local API processes so only
        one initial pairing attempt can execute at a time.
        """

        async with self.identity_store.pairing_lock():
            # Re-check INSIDE the lock.
            #
            # Another FastAPI process may have completed pairing while
            # this request was waiting for the lock.
            if self.identity_store.exists():
                raise InstallationAlreadyPairedError(
                    "CBT installation is already paired."
                )

            # Verify local persistent storage before consuming the
            # one-time Weave pairing code.
            await asyncio.to_thread(self.identity_store.ensure_storage_ready)

            # Initialize this installation's local JWT signing secret.
            #
            # This secret is generated locally and is completely
            # independent from the Weave-issued machine credential.
            await asyncio.to_thread(ensure_local_signing_secret)

            weave_request = WeavePairingRequest(
                pairing_code=request.pairing_code,
                server_name=request.server_name,
                client_version=settings.APP_VERSION,
            )

            weave_result = await self.installation_gateway.pair(weave_request)

            identity = StoredNodeIdentity(
                server_id=weave_result.server_id,
                server_name=weave_result.server_name,
                hostname=weave_result.hostname,
                server_credential=weave_result.server_credential,
                tenant_id=weave_result.tenant.id,
                tenant_name=weave_result.tenant.name,
                paired_at=weave_result.paired_at,
            )

            await asyncio.to_thread(
                self.identity_store.save_initial,
                identity,
            )

            return PairInstallationResponse(
                configured=True,
                server_id=identity.server_id,
                server_name=identity.server_name,
                hostname=identity.hostname,
                tenant_id=identity.tenant_id,
                tenant_name=identity.tenant_name,
                paired_at=identity.paired_at,
            )


node_service = NodeService()
