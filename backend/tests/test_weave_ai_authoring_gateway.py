from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from app.integrations.weave.ai_authoring import (
    AI_AUTHORING_REQUEST_TIMEOUT_SECONDS,
    WeaveAIQuestionAuthoringGateway,
)
from app.integrations.weave.ai_authoring_schemas import AIGenerateQuestionsRequest
from app.integrations.weave.exceptions import (
    WeaveRequestRejectedError,
    WeaveUnavailableError,
)


def _success_payload() -> dict:
    return {
        "questions": [
            {
                "question_type": "single_choice",
                "prompt": "Question?",
                "instruction": None,
                "image": None,
                "options": [
                    {"text": "A", "is_correct": True, "image": None},
                    {"text": "B", "is_correct": False, "image": None},
                ],
            }
        ],
        "repaired": False,
        "charge": {
            "reservation_id": "00000000-0000-0000-0000-000000000001",
            "credits_charged": 1,
            "credits_released": 0,
        },
    }


def _request() -> AIGenerateQuestionsRequest:
    return AIGenerateQuestionsRequest(
        subject="Biology",
        academic_level="SS 2",
        generation_prompt="Cells",
        question_count=1,
    )


@pytest.mark.asyncio
async def test_ai_authoring_transport_retry_reuses_same_idempotency_key() -> None:
    client = AsyncMock()
    client.request_actor_authenticated.side_effect = [
        WeaveUnavailableError("timeout"),
        _success_payload(),
    ]
    gateway = WeaveAIQuestionAuthoringGateway(
        gateway=type("Gateway", (), {"client": client})()
    )

    result = await gateway.generate_questions(
        payload=_request(),
        idempotency_key="operation-123",
        server_credential=SecretStr("server-secret"),
        actor_access_token="actor-token",
    )

    assert result.charge.credits_charged == 1
    assert client.request_actor_authenticated.await_count == 2
    for call in client.request_actor_authenticated.await_args_list:
        assert call.kwargs["headers"] == {"Idempotency-Key": "operation-123"}
        assert call.kwargs["timeout_seconds"] == AI_AUTHORING_REQUEST_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_ai_authoring_waits_for_in_progress_after_ambiguous_timeout() -> None:
    client = AsyncMock()
    client.request_actor_authenticated.side_effect = [
        WeaveUnavailableError("timeout"),
        WeaveRequestRejectedError(
            status_code=409,
            detail="This AI request is already being processed.",
            payload={"code": "AI_REQUEST_IN_PROGRESS", "retryable": True},
        ),
        _success_payload(),
    ]
    gateway = WeaveAIQuestionAuthoringGateway(
        gateway=type("Gateway", (), {"client": client})(),
        in_progress_poll_interval_seconds=0.01,
        in_progress_max_wait_seconds=1.0,
    )

    sleep = AsyncMock()
    with patch("app.integrations.weave.ai_authoring.asyncio.sleep", sleep):
        result = await gateway.generate_questions(
            payload=_request(),
            idempotency_key="operation-in-progress",
            server_credential=SecretStr("server-secret"),
            actor_access_token="actor-token",
        )

    assert result.charge.credits_charged == 1
    assert client.request_actor_authenticated.await_count == 3
    assert sleep.await_count == 2
    assert {
        call.kwargs["headers"]["Idempotency-Key"]
        for call in client.request_actor_authenticated.await_args_list
    } == {"operation-in-progress"}


@pytest.mark.asyncio
async def test_ai_authoring_retries_transient_cloud_503_with_same_key() -> None:
    client = AsyncMock()
    client.request_actor_authenticated.side_effect = [
        WeaveRequestRejectedError(
            status_code=503,
            detail="AI result recovery is temporarily unavailable.",
            payload={"code": "AI_REPLAY_UNAVAILABLE", "retryable": True},
        ),
        _success_payload(),
    ]
    gateway = WeaveAIQuestionAuthoringGateway(
        gateway=type("Gateway", (), {"client": client})()
    )

    await gateway.generate_questions(
        payload=_request(),
        idempotency_key="operation-503",
        server_credential=SecretStr("server-secret"),
        actor_access_token="actor-token",
    )

    assert client.request_actor_authenticated.await_count == 2
    assert {
        call.kwargs["headers"]["Idempotency-Key"]
        for call in client.request_actor_authenticated.await_args_list
    } == {"operation-503"}


@pytest.mark.asyncio
async def test_ai_authoring_does_not_retry_business_rejection() -> None:
    client = AsyncMock()
    client.request_actor_authenticated.side_effect = WeaveRequestRejectedError(
        status_code=409,
        detail="Result expired.",
        payload={"code": "AI_RESULT_EXPIRED"},
    )
    gateway = WeaveAIQuestionAuthoringGateway(
        gateway=type("Gateway", (), {"client": client})()
    )

    with pytest.raises(WeaveRequestRejectedError):
        await gateway.generate_questions(
            payload=_request(),
            idempotency_key="operation-terminal",
            server_credential=SecretStr("server-secret"),
            actor_access_token="actor-token",
        )

    assert client.request_actor_authenticated.await_count == 1
