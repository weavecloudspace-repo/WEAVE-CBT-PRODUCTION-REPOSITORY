from __future__ import annotations

import os
import unittest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.integration_errors import (
    WEAVE_CONTRACT_FAILURE_MESSAGE,
    WEAVE_UNAVAILABLE_MESSAGE,
    WEAVE_UPSTREAM_FAILURE_MESSAGE,
    register_weave_integration_error_handlers,
)
from app.integrations.weave.exceptions import (
    WeaveContractError,
    WeaveRequestRejectedError,
    WeaveUnavailableError,
)


def _app_for(exc: Exception) -> FastAPI:
    app = FastAPI()
    register_weave_integration_error_handlers(app)

    @app.get("/boom")
    async def boom():
        raise exc

    return app


class WeaveIntegrationErrorHandlerTests(unittest.TestCase):
    def test_expected_upstream_client_error_preserves_status_and_detail(self) -> None:
        app = _app_for(
            WeaveRequestRejectedError(
                status_code=403,
                detail="This teacher membership is currently suspended.",
            )
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {"detail": "This teacher membership is currently suspended."},
        )

    def test_rate_limit_preserves_retry_after(self) -> None:
        app = _app_for(
            WeaveRequestRejectedError(
                status_code=429,
                detail="Too many requests.",
                retry_after=45,
            )
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("retry-after"), "45")
        self.assertEqual(response.json(), {"detail": "Too many requests."})

    def test_upstream_server_failure_becomes_safe_bad_gateway(self) -> None:
        app = _app_for(
            WeaveRequestRejectedError(
                status_code=500,
                detail="internal database traceback that must not reach the browser",
            )
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": WEAVE_UPSTREAM_FAILURE_MESSAGE})
        self.assertNotIn("traceback", response.text.lower())

    def test_weave_unavailable_becomes_user_actionable_503(self) -> None:
        app = _app_for(WeaveUnavailableError("Unable to connect to Weave Cloud"))

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": WEAVE_UNAVAILABLE_MESSAGE})

    def test_contract_failure_becomes_safe_bad_gateway(self) -> None:
        app = _app_for(WeaveContractError("unexpected actor payload internals"))

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": WEAVE_CONTRACT_FAILURE_MESSAGE})
        self.assertNotIn("actor payload", response.text.lower())


if __name__ == "__main__":
    unittest.main()
