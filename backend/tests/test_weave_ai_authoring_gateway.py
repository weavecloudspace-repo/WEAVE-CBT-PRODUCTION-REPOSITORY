from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from app.integrations.weave.ai_authoring import (
    AI_AUTHORING_IN_PROGRESS_MAX_POLL_INTERVAL_SECONDS,
    AI_AUTHORING_IN_PROGRESS_MAX_WAIT_SECONDS,
    AI_AUTHORING_IN_PROGRESS_POLL_INTERVAL_SECONDS,
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


def test_hybrid_ai_timeouts_allow_sync_generation_and_replay() -> None:
    assert AI_AUTHORING_REQUEST_TIMEOUT_SECONDS == 600.0
    assert AI_AUTHORING_IN_PROGRESS_POLL_INTERVAL_SECONDS == 5.0
    assert AI_AUTHORING_IN_PROGRESS_MAX_POLL_INTERVAL_SECONDS == 20.0
    assert AI_AUTHORING_IN_PROGRESS_MAX_WAIT_SECONDS == 600.0


@pytest.mark.asyncio
async def test_recovery_polling_backs_off_instead_of_spamming_weave() -> None:
    client = AsyncMock()
    processing = WeaveRequestRejectedError(
        status_code=409,
        detail="This AI request is already being processed.",
        payload={"code": "AI_REQUEST_IN_PROGRESS", "retryable": True},
    )
    client.request_actor_authenticated.side_effect = [
        WeaveUnavailableError("original request timed out"),
        processing,
        processing,
        processing,
        processing,
        _success_payload(),
    ]
    gateway = WeaveAIQuestionAuthoringGateway(
        gateway=type("Gateway", (), {"client": client})(),
    )

    with patch(
        "app.integrations.weave.ai_authoring.asyncio.sleep", new_callable=AsyncMock
    ) as sleep:
        result = await gateway.generate_questions(
            payload=_request(),
            idempotency_key="replay-the-same-operation",
            server_credential=SecretStr("server-secret"),
            actor_access_token="actor-token",
        )

    assert result.charge.credits_charged == 1
    assert sleep.await_args_list[0].args == (0.2,)
    assert [call.args[0] for call in sleep.await_args_list[1:]] == [
        5.0,
        10.0,
        20.0,
        20.0,
    ]
    assert len(client.request_actor_authenticated.await_args_list) == 6
    for request in client.request_actor_authenticated.await_args_list:
        assert (
            request.kwargs["headers"]["Idempotency-Key"] == "replay-the-same-operation"
        )
        assert request.kwargs["timeout_seconds"] == 600.0


@pytest.mark.asyncio
async def test_cloud_retry_after_is_honored_without_one_second_polling() -> None:
    client = AsyncMock()
    client.request_actor_authenticated.side_effect = [
        WeaveRequestRejectedError(
            status_code=409,
            detail="Still processing",
            retry_after=30,
            payload={"code": "AI_REQUEST_IN_PROGRESS", "retryable": True},
        ),
        _success_payload(),
    ]
    gateway = WeaveAIQuestionAuthoringGateway(
        gateway=type("Gateway", (), {"client": client})(),
    )
    with patch("app.integrations.weave.ai_authoring.asyncio.sleep", new_callable=AsyncMock) as sleep:
        await gateway.generate_questions(
            payload=_request(),
            idempotency_key="operation-retry-after",
            server_credential=SecretStr("server-secret"),
            actor_access_token="actor-token",
        )
    sleep.assert_awaited_once_with(30.0)


@pytest.mark.asyncio
async def test_non_retryable_ai_validation_502_is_not_masked_by_a_replay_conflict() -> (
    None
):
    client = AsyncMock()
    failure = WeaveRequestRejectedError(
        status_code=502,
        detail="AI generated invalid questions",
        payload={"code": "AI_INVALID_QUESTION_OUTPUT", "retryable": False},
    )
    client.request_actor_authenticated.side_effect = failure
    gateway = WeaveAIQuestionAuthoringGateway(
        gateway=type("Gateway", (), {"client": client})(),
    )
    with pytest.raises(WeaveRequestRejectedError) as raised:
        await gateway.generate_questions(
            payload=_request(),
            idempotency_key="rejected-operation",
            server_credential=SecretStr("server-secret"),
            actor_access_token="actor-token",
        )
    assert raised.value.payload["code"] == "AI_INVALID_QUESTION_OUTPUT"
    assert client.request_actor_authenticated.await_count == 1


def test_invalid_recovery_wait_settings_are_rejected() -> None:
    transport = type("Gateway", (), {"client": AsyncMock()})()
    with pytest.raises(ValueError, match="Maximum AI poll interval"):
        WeaveAIQuestionAuthoringGateway(
            gateway=transport,
            in_progress_poll_interval_seconds=30.0,
            in_progress_max_poll_interval_seconds=20.0,
        )
