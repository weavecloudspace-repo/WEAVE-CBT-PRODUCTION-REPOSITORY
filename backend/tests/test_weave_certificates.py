"""Machine-scoped HTTPS DNS challenge contracts."""

import os
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from pydantic import SecretStr

from app.integrations.weave.certificates import WeaveCertificateGateway, verify_hostname
from app.integrations.weave.exceptions import WeaveContractError


class CertificateGatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = AsyncMock()
        self.gateway = WeaveCertificateGateway(client=self.client)
        self.server_id = uuid4()
        self.credential = SecretStr("local-machine-only")
        self.hostname = "main-lab.greenfield.cbt-staging.weavecloudspace.com"

    async def test_hostname_is_scoped_to_authenticated_machine(self):
        self.client.request_authenticated.return_value = {
            "server_id": str(self.server_id),
            "hostname": self.hostname,
        }
        result = await self.gateway.hostname(
            credential=self.credential, server_id=self.server_id
        )
        self.assertEqual(result, self.hostname)
        self.client.request_authenticated.assert_awaited_once_with(
            "GET",
            "/api/v1/cbt/server/hostname",
            server_credential=self.credential,
        )

    async def test_cross_server_hostname_is_rejected(self):
        self.client.request_authenticated.return_value = {
            "server_id": str(uuid4()),
            "hostname": self.hostname,
        }
        with self.assertRaises(WeaveContractError):
            await self.gateway.hostname(
                credential=self.credential, server_id=self.server_id
            )

    async def test_create_challenge_uses_machine_auth_without_arbitrary_hostname(self):
        request_id = uuid4()
        self.client.request_authenticated.return_value = {
            "id": str(uuid4()),
            "hostname": self.hostname,
            "fqdn": "_acme-challenge." + self.hostname,
            "status": "created",
            "expires_at": datetime.now(UTC).isoformat(),
            "ttl": 300,
        }
        await self.gateway.create(
            credential=self.credential,
            request_id=request_id,
            value="A" * 43,
            hostname=self.hostname,
        )
        self.client.request_authenticated.assert_awaited_once_with(
            "POST",
            "/api/v1/cbt/certificates/dns-challenges",
            server_credential=self.credential,
            json={"request_id": str(request_id), "value": "A" * 43},
        )

    def test_disallow_untrusted_hostname(self):
        for hostname in (
            "api.weavecloudspace.com",
            "evil.weavecloudspace.com.attacker.net",
            "x..cbt.weavecloudspace.com",
        ):
            with self.assertRaises(WeaveContractError):
                verify_hostname(hostname)

    async def test_delete_uses_existing_machine_credential(self):
        challenge_id = uuid4()
        await self.gateway.remove(credential=self.credential, challenge_id=challenge_id)
        self.client.request_authenticated.assert_awaited_once_with(
            "DELETE",
            f"/api/v1/cbt/certificates/dns-challenges/{challenge_id}",
            server_credential=self.credential,
        )
