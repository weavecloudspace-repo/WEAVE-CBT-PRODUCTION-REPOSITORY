"""Low-level pooled HTTP transport for communication with Weave Cloud."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx2 as httpx
from pydantic import SecretStr

from app.core.settings import settings
from app.integrations.weave.exceptions import (
    WeaveContractError,
    WeaveRequestRejectedError,
    WeaveUnavailableError,
)


class WeaveClient:
    """Own transport mechanics and reuse one keep-alive connection pool per process."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or str(settings.WEAVE_API_BASE_URL)).rstrip("/")
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        client = self._client
        if client is not None and not client.is_closed:
            return client
        async with self._client_lock:
            client = self._client
            if client is None or client.is_closed:
                timeout = httpx.Timeout(
                    timeout=settings.WEAVE_REQUEST_TIMEOUT_SECONDS,
                    connect=settings.WEAVE_CONNECT_TIMEOUT_SECONDS,
                )
                self._client = httpx.AsyncClient(
                    timeout=timeout,
                    limits=httpx.Limits(
                        max_connections=50,
                        max_keepalive_connections=20,
                        keepalive_expiry=30.0,
                    ),
                    headers={"Accept": "application/json"},
                )
            return self._client

    async def close(self) -> None:
        async with self._client_lock:
            client = self._client
            self._client = None
        if client is not None and not client.is_closed:
            await client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        url = self._build_url_path(path)
        try:
            client = await self._get_client()
            request_kwargs: dict[str, Any] = {
                "method": method,
                "url": url,
                "json": json,
                "params": params,
                "headers": headers,
            }
            if timeout_seconds is not None:
                request_kwargs["timeout"] = httpx.Timeout(
                    timeout=timeout_seconds,
                    connect=settings.WEAVE_CONNECT_TIMEOUT_SECONDS,
                )
            response = await client.request(**request_kwargs)
        except httpx.TimeoutException as exc:
            raise WeaveUnavailableError("Weave Cloud did not respond in time") from exc
        except httpx.RequestError as exc:
            raise WeaveUnavailableError("Unable to connect to Weave Cloud") from exc

        if not response.is_success:
            raise WeaveRequestRejectedError(
                status_code=response.status_code,
                detail=self._extract_error_detail(response),
                retry_after=self._extract_retry_after(response),
                payload=self._extract_error_payload(response),
            )
        if response.status_code == 204:
            return {}
        return self._parse_json_object(response)

    async def post_public(
        self,
        *,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._request("POST", path, json=payload)

    async def request_authenticated(
        self,
        method: str,
        path: str,
        *,
        server_credential: SecretStr,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        request_headers = {
            "Authorization": f"Bearer {server_credential.get_secret_value()}"
        }
        if headers:
            request_headers.update(headers)
        return await self._request(
            method,
            path,
            json=json,
            params=params,
            headers=request_headers,
            timeout_seconds=timeout_seconds,
        )

    async def request_actor_authenticated(
        self,
        method: str,
        path: str,
        *,
        server_credential: SecretStr,
        actor_access_token: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Call a Weave route requiring both server and staff-actor authorization."""

        actor_token = actor_access_token.strip()
        if not actor_token:
            raise WeaveContractError("Weave actor access token is missing.")

        request_headers = {
            "Authorization": f"Bearer {server_credential.get_secret_value()}",
            "X-CBT-Actor-Authorization": actor_token,
        }
        if headers:
            request_headers.update(headers)
        return await self._request(
            method,
            path,
            json=json,
            params=params,
            headers=request_headers,
            timeout_seconds=timeout_seconds,
        )

    def _build_url_path(self, path: str) -> str:
        return f"{self.base_url}/" + path.lstrip("/")

    def build_websocket_url(self, path: str) -> str:
        parsed = urlsplit(self._build_url_path(path))
        if parsed.scheme == "https":
            scheme = "wss"
        elif parsed.scheme == "http":
            scheme = "ws"
        else:
            raise WeaveContractError("WEAVE_API_BASE_URL must use http or https.")
        return urlunsplit(
            (scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment)
        )

    @staticmethod
    def _parse_json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise WeaveContractError(
                "Weave returned an invalid JSON response."
            ) from exc
        if not isinstance(payload, dict):
            raise WeaveContractError("Weave returned an unexpected response structure.")
        return payload

    @staticmethod
    def _extract_error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return "Weave rejected the request."
        if not isinstance(payload, dict):
            return "Weave rejected the request."
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        if isinstance(detail, dict):
            message = detail.get("message") or detail.get("detail")
            if isinstance(message, str) and message.strip():
                return message.strip()
        return "Weave rejected the request."

    @staticmethod
    def _extract_error_payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            return {}
        if not isinstance(payload, dict):
            return {}
        return {key: value for key, value in payload.items() if key != "detail"}

    @staticmethod
    def _extract_retry_after(response: httpx.Response) -> int | None:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        value = value.strip()
        return int(value) if value.isdigit() else None


weave_client = WeaveClient()
