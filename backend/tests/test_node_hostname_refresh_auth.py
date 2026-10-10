"""A paired machine's cloud DNS hostname is an administrator-only mutation."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.auth.dependencies import get_current_local_actor
from app.domains.node.router import router
from app.domains.node.service import node_service


class HostnameRefreshSecurityTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)

    def test_anonymous_candidate_cannot_trigger_cloud_hostname_request(self):
        with (
            TestClient(self.app) as client,
            patch.object(node_service, "refresh_hostname", new_callable=AsyncMock) as cloud,
        ):
            response = client.post("/installation/hostname/refresh")
            self.assertEqual(response.status_code, 401)
            cloud.assert_not_awaited()

    def test_teacher_cannot_trigger_cloud_hostname_request(self):
        self.app.dependency_overrides[get_current_local_actor] = (
            lambda: SimpleNamespace(role="teacher")
        )
        with (
            TestClient(self.app) as client,
            patch.object(node_service, "refresh_hostname", new_callable=AsyncMock) as cloud,
        ):
            response = client.post("/installation/hostname/refresh")
            self.assertEqual(response.status_code, 403)
            cloud.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
