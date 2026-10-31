"""Question-authoring extension over the existing CBT -> Weave AI gateway."""

from __future__ import annotations

import asyncio

from pydantic import SecretStr, ValidationError

from app.integrations.weave.ai import AI_PATH, WeaveAIGateway, weave_ai_gateway
from app.integrations.weave.ai_authoring_schemas import (
    AIGenerateQuestionsRequest,
    AIGenerateQuestionsResponse,
    AIRegenerateQuestionRequest,
    AIRegenerateQuestionResponse,
)
from app.integrations.weave.exceptions import (
    WeaveContractError,
    WeaveRequestRejectedError,
    WeaveUnavailableError,
)

# Large hybrid batches can take several minutes. Keep one synchronous request;
# if the transport fails, recover using WEAVE's existing idempotency replay.
AI_AUTHORING_REQUEST_TIMEOUT_SECONDS = 600.0
AI_AUTHORING_IN_PROGRESS_POLL_INTERVAL_SECONDS = 5.0
AI_AUTHORING_IN_PROGRESS_MAX_POLL_INTERVAL_SECONDS = 20.0
AI_AUTHORING_IN_PROGRESS_MAX_WAIT_SECONDS = 600.0
AI_AUTHORING_TRANSIENT_RETRY_DELAY_SECONDS = 0.2
AI_AUTHORING_MAX_TRANSIENT_RETRIES = 1
AI_REQUEST_IN_PROGRESS_CODE = "AI_REQUEST_IN_PROGRESS"


class WeaveAIQuestionAuthoringGateway:
    """Add authoring calls while reusing the shared AI gateway/client/auth stack."""

    def __init__(
        self,
        gateway: WeaveAIGateway = weave_ai_gateway,
        *,
        request_timeout_seconds: float = AI_AUTHORING_REQUEST_TIMEOUT_SECONDS,
        in_progress_poll_interval_seconds: float = AI_AUTHORING_IN_PROGRESS_POLL_INTERVAL_SECONDS,
        in_progress_max_poll_interval_seconds: float = AI_AUTHORING_IN_PROGRESS_MAX_POLL_INTERVAL_SECONDS,
        in_progress_max_wait_seconds: float = AI_AUTHORING_IN_PROGRESS_MAX_WAIT_SECONDS,
    ) -> None:
        self.gateway = gateway
        self.request_timeout_seconds = request_timeout_seconds
        if request_timeout_seconds <= 0 or in_progress_poll_interval_seconds <= 0:
            raise ValueError("AI request timeout and poll interval must be positive.")
        if in_progress_max_poll_interval_seconds < in_progress_poll_interval_seconds:
            raise ValueError(
                "Maximum AI poll interval must not be shorter than its initial interval."
            )
        if in_progress_max_wait_seconds <= 0:
            raise ValueError("AI recovery wait must be positive.")
        self.in_progress_poll_interval_seconds = in_progress_poll_interval_seconds
        self.in_progress_max_poll_interval_seconds = (
            in_progress_max_poll_interval_seconds
        )
        self.in_progress_max_wait_seconds = in_progress_max_wait_seconds

    async def generate_questions(
        self,
        *,
        payload: AIGenerateQuestionsRequest,
        idempotency_key: str,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AIGenerateQuestionsResponse:
        raw = await self._request_with_transport_retry(
            path="/questions/generate",
            payload=payload.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
        )
        try:
            return AIGenerateQuestionsResponse.model_validate(raw)
        except ValidationError as exc:
            raise WeaveContractError(
                "Weave returned an invalid CBT AI generation response."
            ) from exc

    async def regenerate_question(
        self,
        *,
        payload: AIRegenerateQuestionRequest,
        idempotency_key: str,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> AIRegenerateQuestionResponse:
        raw = await self._request_with_transport_retry(
            path="/questions/regenerate",
            payload=payload.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            server_credential=server_credential,
            actor_access_token=actor_access_token,
        )
        try:
            return AIRegenerateQuestionResponse.model_validate(raw)
        except ValidationError as exc:
            raise WeaveContractError(
                "Weave returned an invalid CBT AI regeneration response."
            ) from exc

    async def _request_with_transport_retry(
        self,
        *,
        path: str,
        payload: dict,
        idempotency_key: str,
        server_credential: SecretStr,
        actor_access_token: str,
    ) -> dict:
        """Recover ambiguous AI calls without changing their idempotency identity."""

        transient_retries = 0
        in_progress_started_at: float | None = None
        in_progress_attempts = 0
        loop = asyncio.get_running_loop()

        while True:
            try:
                return await self.gateway.client.request_actor_authenticated(
                    "POST",
                    f"{AI_PATH}{path}",
                    server_credential=server_credential,
                    actor_access_token=actor_access_token,
                    json=payload,
                    headers={"Idempotency-Key": idempotency_key},
                    timeout_seconds=self.request_timeout_seconds,
                )
            except WeaveUnavailableError:
                if transient_retries >= AI_AUTHORING_MAX_TRANSIENT_RETRIES:
                    raise
                transient_retries += 1
                await asyncio.sleep(AI_AUTHORING_TRANSIENT_RETRY_DELAY_SECONDS)
                continue
            except WeaveRequestRejectedError as exc:
                if self._is_request_in_progress(exc):
                    now = loop.time()
                    if in_progress_started_at is None:
                        in_progress_started_at = now
                    remaining = self.in_progress_max_wait_seconds - (
                        now - in_progress_started_at
                    )
                    if remaining <= 0:
                        raise

                    # Exponential, bounded polling prevents 409 storms while
                    # WEAVE is still producing Qwen images. Keep exactly the
                    # same idempotency key and request body for each replay.
                    retry_delay = min(
                        self.in_progress_poll_interval_seconds
                        * (2 ** min(in_progress_attempts, 2)),
                        self.in_progress_max_poll_interval_seconds,
                    )
                    if exc.retry_after is not None:
                        retry_delay = max(retry_delay, float(exc.retry_after))
                    in_progress_attempts += 1
                    await asyncio.sleep(min(retry_delay, remaining))
                    continue

                if (
                    exc.status_code in {502, 503, 504}
                    and exc.payload.get("retryable") is not False
                    and transient_retries < AI_AUTHORING_MAX_TRANSIENT_RETRIES
                ):
                    transient_retries += 1
                    await asyncio.sleep(AI_AUTHORING_TRANSIENT_RETRY_DELAY_SECONDS)
                    continue
                raise

    @staticmethod
    def _is_request_in_progress(exc: WeaveRequestRejectedError) -> bool:
        return (
            exc.status_code == 409
            and exc.payload.get("code") == AI_REQUEST_IN_PROGRESS_CODE
            and exc.payload.get("retryable") is True
        )


weave_ai_question_authoring_gateway = WeaveAIQuestionAuthoringGateway()
