from __future__ import annotations

import base64
import hashlib

import pytest
from pydantic import ValidationError

from app.domains.questions.ai_schemas import QuestionAIImage


def _image_payload(data: bytes) -> dict:
    return {
        "content_type": "image/png",
        "data_base64": base64.b64encode(data).decode("ascii"),
        "sha256": hashlib.sha256(data).hexdigest(),
        "source": "generated",
    }


def test_ai_draft_image_accepts_matching_binary_hash() -> None:
    image = QuestionAIImage.model_validate(_image_payload(b"not-a-real-image-yet"))
    assert image.sha256 == hashlib.sha256(b"not-a-real-image-yet").hexdigest()


def test_ai_draft_image_rejects_tampered_browser_payload() -> None:
    payload = _image_payload(b"original")
    payload["data_base64"] = base64.b64encode(b"tampered").decode("ascii")
    with pytest.raises(ValidationError, match="SHA-256"):
        QuestionAIImage.model_validate(payload)
