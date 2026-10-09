"""Cloud-backed AI authoring orchestration owned by the question domain."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicAuthorizationError, AcademicScopeError
from app.domains.academics.authorization import AcademicAuthorizationService
from app.domains.academics.repository import AcademicRepository
from app.domains.ai.service import CBTAIManagementService
from app.domains.auth.models import LocalActor
from app.domains.media.models import MediaAsset
from app.domains.media.repository import MediaRepository
from app.domains.media.service import MediaService
from app.domains.media.storage import local_media_storage
from app.domains.questions.ai_models import QuestionAIImportBatch, QuestionAIImportItem
from app.domains.questions.ai_repository import QuestionAIRepository
from app.domains.questions.ai_schemas import (
    QuestionAIBulkSaveRequest,
    QuestionAIDraft,
    QuestionAIGenerateRequest,
    QuestionAIGenerateResponse,
    QuestionAIRegenerateDraftRequest,
    QuestionAIRegenerateResponse,
    QuestionAIRegenerateStoredRequest,
)
from app.domains.questions.exceptions import QuestionConflictError
from app.domains.questions.models import Question, QuestionOption, QuestionType
from app.domains.questions.repository import QuestionRepository
from app.domains.questions.schemas import QuestionOptionCreate
from app.domains.questions.service import (
    _normalize_and_validate_options,
    _normalize_optional_text,
    _normalize_required_text,
    _require_can_manage_question,
)
from app.integrations.weave.ai_authoring import (
    WeaveAIQuestionAuthoringGateway,
    weave_ai_question_authoring_gateway,
)
from app.integrations.weave.ai_authoring_schemas import (
    AIExistingQuestion,
    AIExistingQuestionOption,
    AIImagePayload,
)
from app.integrations.weave.ai_authoring_schemas import (
    AIGenerateQuestionsRequest as WeaveAIGenerateQuestionsRequest,
)
from app.integrations.weave.ai_authoring_schemas import (
    AIRegenerateQuestionRequest as WeaveAIRegenerateQuestionRequest,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _AuthoringContext:
    bank_id: UUID
    subject: str
    academic_level: str


class QuestionAIService:
    """Bridge local question authoring to Weave without persisting drafts early."""

    def __init__(
        self,
        gateway: WeaveAIQuestionAuthoringGateway = weave_ai_question_authoring_gateway,
    ) -> None:
        self.gateway = gateway

    async def generate_questions(
        self,
        db: AsyncSession,
        *,
        actor: LocalActor,
        session_id: UUID,
        bank_id: UUID,
        payload: QuestionAIGenerateRequest,
    ) -> QuestionAIGenerateResponse:
        context = await self._resolve_bank_context(
            db,
            actor=actor,
            bank_id=bank_id,
        )
        # Do not carry projection/authorization reads across credential repair or
        # the external generation call.
        await db.rollback()
        (
            server_credential,
            actor_token,
        ) = await CBTAIManagementService._cloud_credentials(
            db,
            session_id=session_id,
        )
        response = await self.gateway.generate_questions(
            payload=WeaveAIGenerateQuestionsRequest(
                subject=context.subject,
                academic_level=context.academic_level,
                generation_prompt=payload.generation_prompt,
                question_count=payload.question_count,
                question_type_counts=payload.question_type_counts,
                difficulty=payload.difficulty,
                visual_mode=payload.visual_mode,
                context=payload.context,
            ),
            idempotency_key=str(payload.operation_id),
            server_credential=server_credential,
            actor_access_token=actor_token,
        )
        return QuestionAIGenerateResponse(
            operation_id=payload.operation_id,
            questions=[
                QuestionAIDraft.model_validate(item.model_dump(mode="json"))
                for item in response.questions
            ],
            repaired=response.repaired,
            charge=response.charge.model_dump(mode="json"),
        )

    async def regenerate_draft_question(
        self,
        db: AsyncSession,
        *,
        actor: LocalActor,
        session_id: UUID,
        bank_id: UUID,
        payload: QuestionAIRegenerateDraftRequest,
    ) -> QuestionAIRegenerateResponse:
        context = await self._resolve_bank_context(db, actor=actor, bank_id=bank_id)
        await db.rollback()
        (
            server_credential,
            actor_token,
        ) = await CBTAIManagementService._cloud_credentials(
            db,
            session_id=session_id,
        )
        response = await self.gateway.regenerate_question(
            payload=WeaveAIRegenerateQuestionRequest(
                subject=context.subject,
                academic_level=context.academic_level,
                generation_prompt=payload.generation_prompt,
                existing_question=AIExistingQuestion.model_validate(
                    payload.existing_question.model_dump(mode="json")
                ),
                instruction=payload.instruction,
                difficulty=payload.difficulty,
                visual_mode=payload.visual_mode,
                context=payload.context,
            ),
            idempotency_key=str(payload.operation_id),
            server_credential=server_credential,
            actor_access_token=actor_token,
        )
        return QuestionAIRegenerateResponse(
            operation_id=payload.operation_id,
            question=QuestionAIDraft.model_validate(
                response.question.model_dump(mode="json")
            ),
            repaired=response.repaired,
            charge=response.charge.model_dump(mode="json"),
        )

    async def regenerate_stored_question(
        self,
        db: AsyncSession,
        *,
        actor: LocalActor,
        session_id: UUID,
        question_id: UUID,
        payload: QuestionAIRegenerateStoredRequest,
    ) -> QuestionAIRegenerateResponse:
        question = await QuestionRepository.get_question_by_id(db, question_id)
        if question is None:
            raise ValueError("Question does not exist")
        if not question.is_active:
            raise ValueError(
                "Archived questions must be reactivated before regeneration"
            )
        _require_can_manage_question(actor=actor, question=question)

        context = await self._resolve_bank_context(
            db,
            actor=actor,
            bank_id=question.bank_id,
        )
        options = await QuestionRepository.list_options_for_question(db, question.id)
        existing = await self._build_existing_question(
            db, question=question, options=options
        )
        await db.rollback()

        (
            server_credential,
            actor_token,
        ) = await CBTAIManagementService._cloud_credentials(
            db,
            session_id=session_id,
        )
        response = await self.gateway.regenerate_question(
            payload=WeaveAIRegenerateQuestionRequest(
                subject=context.subject,
                academic_level=context.academic_level,
                generation_prompt=payload.generation_prompt,
                existing_question=existing,
                instruction=payload.instruction,
                difficulty=payload.difficulty,
                visual_mode=payload.visual_mode,
                context=payload.context,
            ),
            idempotency_key=str(payload.operation_id),
            server_credential=server_credential,
            actor_access_token=actor_token,
        )
        return QuestionAIRegenerateResponse(
            operation_id=payload.operation_id,
            question=QuestionAIDraft.model_validate(
                response.question.model_dump(mode="json")
            ),
            repaired=response.repaired,
            charge=response.charge.model_dump(mode="json"),
        )

    @staticmethod
    def _persistence_request_hash(
        *,
        bank_id: UUID,
        payload: QuestionAIBulkSaveRequest,
    ) -> str:
        canonical = json.dumps(
            {
                "bank_id": str(bank_id),
                "questions": [
                    question.model_dump(mode="json", exclude_none=True)
                    for question in payload.questions
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    async def persist_reviewed_questions(
        self,
        db: AsyncSession,
        *,
        actor: LocalActor,
        bank_id: UUID,
        payload: QuestionAIBulkSaveRequest,
    ) -> list[Question]:
        if not actor.is_active or actor.role not in {"admin", "teacher"}:
            raise AcademicAuthorizationError(
                "Only active school staff can persist generated questions"
            )

        request_hash = self._persistence_request_hash(bank_id=bank_id, payload=payload)
        existing_batch = await QuestionAIRepository.get_import_batch_by_draft_id(
            db,
            payload.draft_id,
        )
        if existing_batch is not None:
            return await self._resolve_existing_import(
                db,
                actor=actor,
                bank_id=bank_id,
                request_hash=request_hash,
                batch=existing_batch,
            )

        bank = await QuestionRepository.get_bank_by_id(db, bank_id, lock=True)
        if bank is None:
            raise ValueError("Question bank does not exist")
        if not bank.is_active:
            raise ValueError("Questions cannot be added to an inactive question bank")
        await AcademicAuthorizationService.require_can_author_curriculum_subject(
            db,
            actor=actor,
            curriculum_subject_id=bank.curriculum_subject_id,
        )

        batch = QuestionAIImportBatch(
            draft_id=payload.draft_id,
            bank_id=bank.id,
            actor_id=actor.id,
            request_hash=request_hash,
        )
        try:
            await QuestionAIRepository.add_import_batch(db, batch)
        except IntegrityError:
            # A concurrent retry can win the unique draft_id race while this
            # request waits on the question-bank row lock. Resolve the committed
            # batch rather than inserting a duplicate set of questions.
            await db.rollback()
            existing_batch = await QuestionAIRepository.get_import_batch_by_draft_id(
                db,
                payload.draft_id,
            )
            if existing_batch is None:
                raise
            return await self._resolve_existing_import(
                db,
                actor=actor,
                bank_id=bank_id,
                request_hash=request_hash,
                batch=existing_batch,
            )

        created_storage_keys: list[str] = []
        created_questions: list[Question] = []
        try:
            for question_position, draft in enumerate(payload.questions, start=1):
                question_image_id = await self._persist_draft_image(
                    db,
                    actor=actor,
                    image=draft.image,
                    storage_keys=created_storage_keys,
                    filename="ai-question-image",
                )
                staged_options: list[QuestionOptionCreate] = []
                for position, option in enumerate(draft.options, start=1):
                    option_image_id = await self._persist_draft_image(
                        db,
                        actor=actor,
                        image=option.image,
                        storage_keys=created_storage_keys,
                        filename=f"ai-option-{position}",
                    )
                    staged_options.append(
                        QuestionOptionCreate(
                            text=option.text,
                            image_asset_id=option_image_id,
                            is_correct=option.is_correct,
                        )
                    )

                question_type = QuestionType(draft.question_type)
                normalized_options = _normalize_and_validate_options(
                    staged_options,
                    question_type=question_type,
                )
                prompt = _normalize_required_text(draft.prompt)
                if prompt is None:
                    raise ValueError("Question prompt cannot be empty")

                question = await QuestionRepository.add_question(
                    db,
                    Question(
                        bank_id=bank.id,
                        question_type=question_type,
                        prompt=prompt,
                        instruction=_normalize_optional_text(draft.instruction),
                        image_asset_id=question_image_id,
                        version=1,
                        created_by_actor_id=actor.id,
                        last_edited_by_actor_id=None,
                        is_active=True,
                    ),
                )
                await QuestionRepository.add_options(
                    db,
                    [
                        QuestionOption(
                            question_id=question.id,
                            position=position,
                            text=text,
                            image_asset_id=image_asset_id,
                            is_correct=is_correct,
                        )
                        for position, (text, image_asset_id, is_correct) in enumerate(
                            normalized_options,
                            start=1,
                        )
                    ],
                )
                await QuestionAIRepository.add_import_item(
                    db,
                    QuestionAIImportItem(
                        batch_id=batch.id,
                        question_id=question.id,
                        position=question_position,
                    ),
                )
                created_questions.append(question)

            await db.commit()
            return created_questions
        except Exception:
            await db.rollback()
            for storage_key in created_storage_keys:
                try:
                    await local_media_storage.delete(storage_key)
                except Exception:
                    logger.exception(
                        "Failed to remove staged AI question media %s after rollback",
                        storage_key,
                    )
            raise

    @staticmethod
    async def _resolve_existing_import(
        db: AsyncSession,
        *,
        actor: LocalActor,
        bank_id: UUID,
        request_hash: str,
        batch: QuestionAIImportBatch,
    ) -> list[Question]:
        if batch.actor_id != actor.id or batch.bank_id != bank_id:
            raise AcademicAuthorizationError(
                "AI draft does not belong to this question authoring context"
            )
        if batch.request_hash != request_hash:
            raise QuestionConflictError(
                "AI draft was already persisted with different reviewed questions"
            )
        questions = await QuestionAIRepository.list_questions_for_import_batch(
            db,
            batch.id,
        )
        if not questions:
            raise QuestionConflictError(
                "The previously persisted AI draft no longer contains questions"
            )
        return questions

    @staticmethod
    async def _resolve_bank_context(
        db: AsyncSession,
        *,
        actor: LocalActor,
        bank_id: UUID,
    ) -> _AuthoringContext:
        bank = await QuestionRepository.get_bank_by_id(db, bank_id)
        if bank is None:
            raise ValueError("Question bank does not exist")
        if not bank.is_active:
            raise ValueError(
                "AI authoring is unavailable for an inactive question bank"
            )

        await AcademicAuthorizationService.require_can_author_curriculum_subject(
            db,
            actor=actor,
            curriculum_subject_id=bank.curriculum_subject_id,
        )
        curriculum_subject = await AcademicRepository.get_curriculum_subject_by_id(
            db, bank.curriculum_subject_id
        )
        if curriculum_subject is None or not curriculum_subject.is_active:
            raise AcademicScopeError("Question bank curriculum subject is unavailable")
        subject = await AcademicRepository.get_subject_by_id(
            db, curriculum_subject.subject_id
        )
        curriculum = await AcademicRepository.get_curriculum_by_id(
            db, curriculum_subject.curriculum_id
        )
        if subject is None or curriculum is None or not subject.is_active:
            raise AcademicScopeError("Question bank academic context is unavailable")
        level = await AcademicRepository.get_level_by_id(
            db, curriculum.academic_level_id
        )
        if level is None:
            raise AcademicScopeError("Question bank academic level is unavailable")
        return _AuthoringContext(
            bank_id=bank.id,
            subject=subject.name,
            academic_level=level.name,
        )

    @staticmethod
    async def _image_payload(
        db: AsyncSession,
        asset_id: UUID | None,
    ) -> AIImagePayload | None:
        if asset_id is None:
            return None
        asset = await MediaRepository.get_asset_by_id(db, asset_id)
        if asset is None:
            raise ValueError("Question media asset does not exist")
        content = await MediaService.load_asset_content(db, asset_id=asset.id)
        return AIImagePayload(
            content_type=asset.mime_type,
            data_base64=base64.b64encode(content.data).decode("ascii"),
            sha256=asset.sha256,
        )

    @classmethod
    async def _build_existing_question(
        cls,
        db: AsyncSession,
        *,
        question: Question,
        options: list[QuestionOption],
    ) -> AIExistingQuestion:
        return AIExistingQuestion(
            question_type=question.question_type.value,
            prompt=question.prompt,
            instruction=question.instruction,
            image=await cls._image_payload(db, question.image_asset_id),
            options=[
                AIExistingQuestionOption(
                    text=option.text,
                    image=await cls._image_payload(db, option.image_asset_id),
                    is_correct=option.is_correct,
                )
                for option in options
            ],
        )

    @staticmethod
    async def _persist_draft_image(
        db: AsyncSession,
        *,
        actor: LocalActor,
        image,
        storage_keys: list[str],
        filename: str,
    ) -> UUID | None:
        if image is None:
            return None
        data = base64.b64decode(image.data_base64, validate=True)
        stored = await local_media_storage.save_question_image(data)
        storage_keys.append(stored.storage_key)
        asset = await MediaRepository.add_asset(
            db,
            MediaAsset(
                storage_key=stored.storage_key,
                original_filename=filename,
                mime_type=stored.mime_type,
                size_bytes=stored.size_bytes,
                sha256=stored.sha256,
                created_by_actor_id=actor.id,
            ),
        )
        return asset.id


question_ai_service = QuestionAIService()
