from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from fastapi import FastAPI
from starlette.testclient import TestClient

from app.core.database import get_database_session
from app.domains.auth.dependencies import get_current_local_actor
from app.domains.exams.repository import ExamRepository
from app.domains.media.models import MediaAsset
from app.domains.media.router import router as media_router
from app.domains.media.service import MediaContent, MediaService
from app.domains.questions.models import (
    Question,
    QuestionBank,
    QuestionOption,
    QuestionType,
)
from app.domains.questions.repository import QuestionRepository
from app.domains.questions.router import router as questions_router
from app.domains.questions.service import QuestionService


class QuestionRouteIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        for repository, method in [
            (ExamRepository, "list_referenced_question_ids"),
            (ExamRepository, "list_referenced_bank_ids"),
            (QuestionRepository, "list_nonempty_bank_ids"),
        ]:
            patcher = patch.object(
                repository, method, new=AsyncMock(return_value=set())
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        self.db = object()
        self.current_actor = SimpleNamespace(
            id=uuid4(),
            role="admin",
            is_active=True,
            weave_membership_id=None,
        )

        app = FastAPI()
        app.include_router(media_router, prefix="/api/v1")
        app.include_router(questions_router, prefix="/api/v1")

        async def override_db():
            yield self.db

        async def override_actor():
            return self.current_actor

        app.dependency_overrides[get_database_session] = override_db
        app.dependency_overrides[get_current_local_actor] = override_actor

        self.client = TestClient(app)

    def test_fastapi_multipart_question_image_upload(self) -> None:
        asset_id = uuid4()
        asset = MediaAsset(
            id=asset_id,
            storage_key="questions/aa/example.webp",
            original_filename="diagram.png",
            mime_type="image/webp",
            size_bytes=1234,
            sha256="a" * 64,
            created_by_actor_id=self.current_actor.id,
        )

        with patch.object(
            MediaService,
            "upload_question_image",
            new=AsyncMock(return_value=asset),
        ) as upload:
            response = self.client.post(
                "/api/v1/media/question-images",
                files={
                    "file": (
                        "diagram.png",
                        b"raw-image-bytes",
                        "image/png",
                    )
                },
            )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["id"], str(asset_id))
        self.assertEqual(body["mime_type"], "image/webp")
        upload.assert_awaited_once_with(
            self.db,
            actor=self.current_actor,
            original_filename="diagram.png",
            data=b"raw-image-bytes",
        )

    def test_teacher_cannot_create_question_bank(self) -> None:
        self.current_actor = SimpleNamespace(
            id=uuid4(),
            role="teacher",
            is_active=True,
            weave_membership_id=str(uuid4()),
        )

        with patch.object(
            QuestionService,
            "create_question_bank",
            new=AsyncMock(),
        ) as create_bank:
            response = self.client.post(
                f"/api/v1/questions/banks/{uuid4()}",
                json={"name": "Revision"},
            )

        self.assertEqual(response.status_code, 403)
        create_bank.assert_not_awaited()

    def test_admin_can_discover_archived_banks_for_reactivation(self) -> None:
        subject_id = uuid4()
        archived_bank = QuestionBank(
            id=uuid4(),
            curriculum_subject_id=subject_id,
            name="REVISION",
            description=None,
            created_by_actor_id=self.current_actor.id,
            is_active=False,
        )

        with patch.object(
            QuestionService,
            "list_admin_question_banks",
            new=AsyncMock(return_value=[archived_bank]),
        ) as list_banks:
            response = self.client.get(
                "/api/v1/questions/banks",
                params={
                    "curriculum_subject_id": str(subject_id),
                    "include_archived": "true",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()[0]["is_active"])
        list_banks.assert_awaited_once_with(
            self.db,
            actor=self.current_actor,
            curriculum_subject_id=subject_id,
            include_archived=True,
        )

    def test_create_single_choice_returns_question_with_options(self) -> None:
        bank_id = uuid4()
        question_id = uuid4()
        question = Question(
            id=question_id,
            bank_id=bank_id,
            question_type=QuestionType.SINGLE_CHOICE,
            prompt="Capital of Nigeria?",
            instruction=None,
            image_asset_id=None,
            version=1,
            created_by_actor_id=self.current_actor.id,
            last_edited_by_actor_id=None,
            is_active=True,
        )
        options = [
            QuestionOption(
                id=uuid4(),
                question_id=question_id,
                position=1,
                text="Lagos",
                is_correct=False,
            ),
            QuestionOption(
                id=uuid4(),
                question_id=question_id,
                position=2,
                text="Abuja",
                is_correct=True,
            ),
        ]

        with (
            patch.object(
                QuestionService,
                "create_single_choice_question",
                new=AsyncMock(return_value=question),
            ) as create_question,
            patch.object(
                QuestionRepository,
                "list_options_for_question",
                new=AsyncMock(return_value=options),
            ),
        ):
            response = self.client.post(
                f"/api/v1/questions/banks/{bank_id}/single-choice",
                json={
                    "prompt": "Capital of Nigeria?",
                    "options": [
                        {"text": "Lagos", "is_correct": False},
                        {"text": "Abuja", "is_correct": True},
                    ],
                },
            )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["id"], str(question_id))
        self.assertEqual(body["question_type"], "single_choice")
        self.assertEqual(len(body["options"]), 2)
        self.assertTrue(body["options"][1]["is_correct"])
        create_question.assert_awaited_once()

    def test_patch_explicit_null_image_reaches_service_as_explicit_field(self) -> None:
        question_id = uuid4()
        bank_id = uuid4()
        question = Question(
            id=question_id,
            bank_id=bank_id,
            question_type=QuestionType.SINGLE_CHOICE,
            prompt="Question",
            instruction=None,
            image_asset_id=None,
            version=2,
            created_by_actor_id=self.current_actor.id,
            last_edited_by_actor_id=self.current_actor.id,
            is_active=True,
        )

        with (
            patch.object(
                QuestionService,
                "update_question",
                new=AsyncMock(return_value=question),
            ) as update,
            patch.object(
                QuestionRepository,
                "list_options_for_question",
                new=AsyncMock(return_value=[]),
            ),
        ):
            response = self.client.patch(
                f"/api/v1/questions/{question_id}",
                json={"image_asset_id": None},
            )

        self.assertEqual(response.status_code, 200)
        payload = update.await_args.kwargs["payload"]
        self.assertIn("image_asset_id", payload.model_fields_set)
        self.assertIsNone(payload.image_asset_id)

    def test_question_image_is_served_only_through_question_route(self) -> None:
        question_id = uuid4()
        image_id = uuid4()
        question = Question(
            id=question_id,
            bank_id=uuid4(),
            question_type=QuestionType.SINGLE_CHOICE,
            prompt="Identify the diagram",
            instruction=None,
            image_asset_id=image_id,
            version=1,
            created_by_actor_id=self.current_actor.id,
            last_edited_by_actor_id=None,
            is_active=True,
        )

        with (
            patch.object(
                QuestionService,
                "get_actor_question",
                new=AsyncMock(return_value=question),
            ),
            patch.object(
                MediaService,
                "load_asset_content",
                new=AsyncMock(
                    return_value=MediaContent(
                        data=b"normalized-webp",
                        mime_type="image/webp",
                        original_filename="diagram.png",
                    )
                ),
            ),
        ):
            response = self.client.get(f"/api/v1/questions/{question_id}/image")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"normalized-webp")
        self.assertEqual(response.headers["content-type"], "image/webp")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_used_question_delete_conflict_maps_to_409(self) -> None:
        question_id = uuid4()

        with patch.object(
            QuestionService,
            "delete_unused_question",
            new=AsyncMock(
                side_effect=ValueError(
                    "A question already used by an exam cannot be deleted; archive it instead"
                )
            ),
        ):
            response = self.client.delete(f"/api/v1/questions/{question_id}")

        self.assertEqual(response.status_code, 409)
        self.assertIn("archive it instead", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
