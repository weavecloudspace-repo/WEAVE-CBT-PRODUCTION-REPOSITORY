from __future__ import annotations

import os
import unittest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("WEAVE_API_BASE_URL", "https://weave.invalid")

from fastapi import FastAPI

from app.domains.auth.router import router


class StaffAuthRouteContractTests(unittest.TestCase):
    def test_expected_staff_auth_routes_are_exposed(self):
        route_methods = {
            (route.path, method)
            for route in router.routes
            for method in (route.methods or set())
        }

        self.assertIn(("/auth/login", "POST"), route_methods)
        self.assertIn(("/auth/refresh", "POST"), route_methods)
        self.assertIn(("/auth/session", "GET"), route_methods)
        self.assertIn(("/auth/logout", "POST"), route_methods)

    def test_refresh_requires_idempotency_key_header(self):
        app = FastAPI()
        app.include_router(router)
        parameters = app.openapi()["paths"]["/auth/refresh"]["post"]["parameters"]
        header = next(item for item in parameters if item["name"] == "Idempotency-Key")
        self.assertEqual(header["in"], "header")
        self.assertTrue(header["required"])
        self.assertEqual(header["schema"]["format"], "uuid")


if __name__ == "__main__":
    unittest.main()
