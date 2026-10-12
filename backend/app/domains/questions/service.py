"""Application services for question banks and source questions."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AcademicAuthorizationError, AcademicScopeError
from app.domains.academics.authorization import AcademicAuthorizationService
from app.domains.academics.repository import AcademicRepository
from app.domains.auth.models import LocalActor
from app.domains.exams.repository import ExamRepository
from app.domains.media.repository import MediaRepository
from app.domains.media.service import MediaService
from app.domains.questions.exceptions import QuestionConflictError
from app.domains.questions.models import (
    Question,
    QuestionBank,
    QuestionOption,
    QuestionType,
)
from app.domains.questions.repository import QuestionRepository
from app.domains.questions.schemas import (
    MultipleChoiceQuestionCreate,
    QuestionBankCreate,
    QuestionBankUpdate,
    QuestionOptionCreate,
    QuestionUpdate,
    SingleChoiceQuestionCreate,
)

logger = logging.getLogger(__name__)


def _normalize_question_bank_name(name: str) -> str | None:
    value = name.strip()
    return value.upper() if value else None


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _normalize_required_text(value: str) -> str | None:
    value = value.strip()
    return value or None


def _require_admin(actor: LocalActor) -> None:
    if not actor.is_active:
        raise AcademicAuthorizationError("Active local actor is required")
    if actor.role != "admin":
        raise AcademicAuthorizationError(
            "Only school administrators can manage question banks"
        )


def _require_can_manage_question(*, actor: LocalActor, question: Question) -> None:
    if not actor.is_active:
        raise AcademicAuthorizationError("Active local actor is required")
    if actor.role == "admin":
        return
    if actor.role == "teacher" and question.created_by_actor_id == actor.id:
        return
    raise AcademicAuthorizationError("You are not allowed to manage this question")


def _normalize_and_validate_options(
    options: list[QuestionOptionCreate],
    *,
    question_type: QuestionType,
) -> list[tuple[str | None, UUID | None, bool]]:
    if len(options) < 2:
        raise ValueError("A question must have at least two options")

    normalized: list[tuple[str | None, UUID | None, bool]] = []
    for option in options:
        text = _normalize_optional_text(option.text)
        if text is None and option.image_asset_id is None:
            raise ValueError("Question options must include text, an image, or both")
        normalized.append((text, option.image_asset_id, option.is_correct))

    comparable = [
        (text.casefold() if text is not None else None, image_asset_id)
        for text, image_asset_id, _ in normalized
    ]
    if len(comparable) != len(set(comparable)):
        raise ValueError("Question options must be unique")

    correct_count = sum(1 for _, _, is_correct in normalized if is_correct)

    if question_type == QuestionType.SINGLE_CHOICE and correct_count != 1:
        raise ValueError(
            "A single-choice question must have exactly one correct option"
        )

    if question_type == QuestionType.MULTIPLE_CHOICE:
        if correct_count < 2:
            raise ValueError(
                "A multiple-choice question must have at least two correct options"
            )
        if correct_count == len(normalized):
            raise ValueError(
                "A multiple-choice question must have at least one incorrect option"
            )

    return normalized


async def _resolve_new_media_asset(
    db: AsyncSession,
    *,
    actor: LocalActor,
    image_asset_id: UUID,
    label: str,
) -> UUID:
    # Lock the immutable asset so cleanup cannot delete it between validation
    # and the owning domain FK write in this transaction.
    asset = await MediaRepository.get_asset_by_id(
        db,
        image_asset_id,
        lock=True,
    )
    if asset is None:
        raise ValueError(f"{label} does not exist")
    if asset.created_by_actor_id != actor.id:
        raise ValueError(
            f"New {label.lower()} must have been uploaded by the current actor"
        )
    return asset.id


async def _resolve_new_question_image(
    db: AsyncSession,
    *,
    actor: LocalActor,
    image_asset_id: UUID,
) -> UUID:
    return await _resolve_new_media_asset(
        db,
        actor=actor,
        image_asset_id=image_asset_id,
        label="Question image",
    )


async def _resolve_new_option_image(
    db: AsyncSession,
    *,
    actor: LocalActor,
    image_asset_id: UUID,
) -> UUID:
    return await _resolve_new_media_asset(
        db,
        actor=actor,
        image_asset_id=image_asset_id,
        label="Answer option image",
    )


async def _resolve_updated_question_image(
    db: AsyncSession,
    *,
    actor: LocalActor,
    question: Question,
    requested_image_asset_id: UUID | None,
) -> UUID | None:
    """Resolve PATCH image semantics without re-owning an unchanged asset.

    - None explicitly removes the image.
    - The current image ID is accepted unchanged regardless of who uploaded it.
    - A different image ID is a replacement and must have been uploaded by the editor.
    """

    if requested_image_asset_id is None:
        return None

    if requested_image_asset_id == question.image_asset_id:
        return question.image_asset_id

    return await _resolve_new_question_image(
        db,
        actor=actor,
        image_asset_id=requested_image_asset_id,
    )


async def _resolve_created_option_images(
    db: AsyncSession,
    *,
    actor: LocalActor,
    normalized_options: list[tuple[str | None, UUID | None, bool]],
) -> list[tuple[str | None, UUID | None, bool]]:
    resolved: list[tuple[str | None, UUID | None, bool]] = []
    for text, image_asset_id, is_correct in normalized_options:
        if image_asset_id is not None:
            image_asset_id = await _resolve_new_option_image(
                db,
                actor=actor,
                image_asset_id=image_asset_id,
            )
        resolved.append((text, image_asset_id, is_correct))
    return resolved


async def _resolve_updated_option_images(
    db: AsyncSession,
    *,
    actor: LocalActor,
    normalized_options: list[tuple[str | None, UUID | None, bool]],
    current_options: list[QuestionOption],
) -> list[tuple[str | None, UUID | None, bool]]:
    current_image_ids = {
        option.image_asset_id
        for option in current_options
        if option.image_asset_id is not None
    }
    resolved: list[tuple[str | None, UUID | None, bool]] = []
    for text, image_asset_id, is_correct in normalized_options:
        if image_asset_id is not None and image_asset_id not in current_image_ids:
            image_asset_id = await _resolve_new_option_image(
                db,
                actor=actor,
                image_asset_id=image_asset_id,
            )
        resolved.append((text, image_asset_id, is_correct))
    return resolved


async def _cleanup_unreferenced_media(
    db: AsyncSession,
    *,
    asset_ids: Iterable[UUID | None],
    log_context: str,
) -> None:
    for asset_id in {asset_id for asset_id in asset_ids if asset_id is not None}:
        try:
            await MediaService.delete_unreferenced_asset(db, asset_id=asset_id)
        except ValueError:
            pass
        except Exception:
            logger.exception(
                "Failed to clean up %s media asset %s", log_context, asset_id
            )


class QuestionService:
    @staticmethod
    async def create_question_bank(
        db: AsyncSession,
        *,
        actor: LocalActor,
        curriculum_subject_id: UUID,
        payload: QuestionBankCreate,
    ) -> QuestionBank:
        _require_admin(actor)

        curriculum_subject = await AcademicRepository.get_curriculum_subject_by_id(
            db,
            curriculum_subject_id,
        )
        if curriculum_subject is None:
            raise AcademicScopeError(
                "Curriculum subject does not exist or is no longer available"
            )
        if not curriculum_subject.is_active:
            raise AcademicScopeError("Curriculum subject is inactive")

        name = _normalize_question_bank_name(payload.name)
        if name is None:
            raise ValueError("Question bank name cannot be empty")

        existing = await QuestionRepository.get_bank_by_scope_and_name(
            db,
            curriculum_subject_id,
            name,
        )
        if existing is not None:
            raise ValueError(
                "A question bank with this name already exists for this curriculum subject"
            )

        bank = QuestionBank(
            curriculum_subject_id=curriculum_subject_id,
            name=name,
            description=_normalize_optional_text(payload.description),
            created_by_actor_id=actor.id,
            is_active=True,
        )

        try:
            bank = await QuestionRepository.add_bank(db, bank)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "A question bank with this name already exists for this curriculum subject"
            ) from exc

        return bank

    @staticmethod
    async def list_actor_authorable_question_banks(
        db: AsyncSession,
        *,
        actor: LocalActor,
    ) -> list[QuestionBank]:
        subjects = await AcademicAuthorizationService.list_actor_authorable_curriculum_subjects(
            db,
            actor=actor,
        )
        return await QuestionRepository.list_banks_for_curriculum_subjects(
            db,
            curriculum_subject_ids=[subject.id for subject in subjects],
            active_only=True,
        )

    @staticmethod
    async def list_admin_question_banks(
        db: AsyncSession,
        *,
        actor: LocalActor,
        curriculum_subject_id: UUID | None = None,
        include_archived: bool = False,
    ) -> list[QuestionBank]:
        """Return banks for admin management, optionally including archived rows."""

        _require_admin(actor)
        return await QuestionRepository.list_banks(
            db,
            curriculum_subject_id=curriculum_subject_id,
            active_only=not include_archived,
        )

    @staticmethod
    async def update_question_bank(
        db: AsyncSession,
        *,
        actor: LocalActor,
        bank_id: UUID,
        payload: QuestionBankUpdate,
    ) -> QuestionBank:
        _require_admin(actor)

        bank = await QuestionRepository.get_bank_by_id(db, bank_id, lock=True)
        if bank is None:
            raise ValueError("Question bank does not exist")

        fields = payload.model_fields_set
        if not fields:
            await db.commit()
            return bank

        next_subject_id = bank.curriculum_subject_id
        next_name = bank.name

        if "curriculum_subject_id" in fields:
            if payload.curriculum_subject_id is None:
                raise ValueError("Curriculum subject cannot be null")
            if payload.curriculum_subject_id != bank.curriculum_subject_id:
                question_count = await QuestionRepository.count_questions_for_bank(
                    db,
                    bank.id,
                )
                if question_count > 0:
                    raise ValueError(
                        "A question bank's curriculum subject can only change while the bank is empty"
                    )
                subject = await AcademicRepository.get_curriculum_subject_by_id(
                    db,
                    payload.curriculum_subject_id,
                )
                if subject is None:
                    raise AcademicScopeError(
                        "Curriculum subject does not exist or is no longer available"
                    )
                if not subject.is_active:
                    raise AcademicScopeError("Curriculum subject is inactive")
                next_subject_id = subject.id

        if "name" in fields:
            if payload.name is None:
                raise ValueError("Question bank name cannot be null")
            normalized_name = _normalize_question_bank_name(payload.name)
            if normalized_name is None:
                raise ValueError("Question bank name cannot be empty")
            next_name = normalized_name

        duplicate = await QuestionRepository.get_bank_by_scope_and_name(
            db,
            next_subject_id,
            next_name,
        )
        if duplicate is not None and duplicate.id != bank.id:
            raise ValueError(
                "A question bank with this name already exists for this curriculum subject"
            )

        bank.curriculum_subject_id = next_subject_id
        bank.name = next_name

        if "description" in fields:
            bank.description = _normalize_optional_text(payload.description)

        try:
            bank = await QuestionRepository.save_bank(db, bank)
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(
                "A question bank with this name already exists for this curriculum subject"
            ) from exc

        return bank

    @staticmethod
    async def archive_question_bank(
        db: AsyncSession,
        *,
        actor: LocalActor,
        bank_id: UUID,
    ) -> QuestionBank:
        _require_admin(actor)
        bank = await QuestionRepository.get_bank_by_id(db, bank_id, lock=True)
        if bank is None:
            raise ValueError("Question bank does not exist")
        if bank.is_active:
            bank.is_active = False
            bank = await QuestionRepository.save_bank(db, bank)
        await db.commit()
        return bank

    @staticmethod
    async def reactivate_question_bank(
        db: AsyncSession,
        *,
        actor: LocalActor,
        bank_id: UUID,
    ) -> QuestionBank:
        _require_admin(actor)
        bank = await QuestionRepository.get_bank_by_id(db, bank_id, lock=True)
        if bank is None:
            raise ValueError("Question bank does not exist")

        subject = await AcademicRepository.get_curriculum_subject_by_id(
            db,
            bank.curriculum_subject_id,
        )
        if subject is None or not subject.is_active:
            raise AcademicScopeError(
                "Question bank cannot be reactivated because its curriculum subject is unavailable"
            )

        if not bank.is_active:
            bank.is_active = True
            bank = await QuestionRepository.save_bank(db, bank)
        await db.commit()
        return bank

    @staticmethod
    async def delete_empty_question_bank(
        db: AsyncSession,
        *,
        actor: LocalActor,
        bank_id: UUID,
    ) -> None:
        _require_admin(actor)
        bank = await QuestionRepository.get_bank_by_id(db, bank_id, lock=True)
        if bank is None:
            raise ValueError("Question bank does not exist")

        if await QuestionRepository.count_questions_for_bank(db, bank.id) > 0:
            raise ValueError(
                "A question bank containing questions cannot be deleted; archive it instead"
            )

        if await ExamRepository.list_referenced_bank_ids(db, [bank.id]):
            raise ValueError(
                "A question bank used by an exam cannot be deleted; archive it instead"
            )

        await QuestionRepository.delete_bank(db, bank)
        await db.commit()

    @staticmethod
    async def create_single_choice_question(
        db: AsyncSession,
        *,
        actor: LocalActor,
        bank_id: UUID,
        payload: SingleChoiceQuestionCreate,
    ) -> Question:
        return await QuestionService._create_choice_question(
            db,
            actor=actor,
            bank_id=bank_id,
            prompt=payload.prompt,
            instruction=payload.instruction,
            image_asset_id=payload.image_asset_id,
            options=payload.options,
            question_type=QuestionType.SINGLE_CHOICE,
        )

    @staticmethod
    async def create_multiple_choice_question(
        db: AsyncSession,
        *,
        actor: LocalActor,
        bank_id: UUID,
        payload: MultipleChoiceQuestionCreate,
    ) -> Question:
        return await QuestionService._create_choice_question(
            db,
            actor=actor,
            bank_id=bank_id,
            prompt=payload.prompt,
            instruction=payload.instruction,
            image_asset_id=payload.image_asset_id,
            options=payload.options,
            question_type=QuestionType.MULTIPLE_CHOICE,
        )

    @staticmethod
    async def _create_choice_question(
        db: AsyncSession,
        *,
        actor: LocalActor,
        bank_id: UUID,
        prompt: str,
        instruction: str | None,
        image_asset_id: UUID | None,
        options: list[QuestionOptionCreate],
        question_type: QuestionType,
    ) -> Question:
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

        normalized_prompt = _normalize_required_text(prompt)
        if normalized_prompt is None:
            raise ValueError("Question prompt cannot be empty")

        resolved_image_id: UUID | None = None
        if image_asset_id is not None:
            resolved_image_id = await _resolve_new_question_image(
                db,
                actor=actor,
                image_asset_id=image_asset_id,
            )

        normalized_options = _normalize_and_validate_options(
            options,
            question_type=question_type,
        )
        normalized_options = await _resolve_created_option_images(
            db,
            actor=actor,
            normalized_options=normalized_options,
        )

        question = Question(
            bank_id=bank.id,
            question_type=question_type,
            prompt=normalized_prompt,
            instruction=_normalize_optional_text(instruction),
            image_asset_id=resolved_image_id,
            version=1,
            created_by_actor_id=actor.id,
            last_edited_by_actor_id=None,
            is_active=True,
        )
        question = await QuestionRepository.add_question(db, question)

        await QuestionRepository.add_options(
            db,
            [
                QuestionOption(
                    question_id=question.id,
                    position=position,
                    text=text,
                    image_asset_id=option_image_asset_id,
                    is_correct=is_correct,
                )
                for position, (text, option_image_asset_id, is_correct) in enumerate(
                    normalized_options,
                    start=1,
                )
            ],
        )

        await db.commit()
        return question

    @staticmethod
    async def list_actor_questions_for_bank(
        db: AsyncSession,
        *,
        actor: LocalActor,
        bank_id: UUID,
        active_only: bool = True,
    ) -> list[Question]:
        """Return the shared bank contents an actor is academically allowed to browse."""

        bank = await QuestionRepository.get_bank_by_id(db, bank_id)
        if bank is None:
            raise ValueError("Question bank does not exist")

        await AcademicAuthorizationService.require_can_author_curriculum_subject(
            db,
            actor=actor,
            curriculum_subject_id=bank.curriculum_subject_id,
        )

        return await QuestionRepository.list_questions_for_bank(
            db,
            bank.id,
            active_only=active_only,
        )

    @staticmethod
    async def list_actor_manageable_questions(
        db: AsyncSession,
        *,
        actor: LocalActor,
        bank_id: UUID | None = None,
        active_only: bool = False,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Question]:
        """Return only questions the actor is permitted to manage.

        Admins manage every question on the local node. Teachers manage only their
        own contributions and only while the containing bank remains in their
        current Weave-backed authoring scope.
        """

        if not actor.is_active:
            raise AcademicAuthorizationError("Active local actor is required")

        created_by_actor_id: UUID | None = None
        if actor.role == "admin":
            banks = await QuestionRepository.list_banks(db, active_only=False)
        elif actor.role == "teacher":
            banks = await QuestionService.list_actor_authorable_question_banks(
                db,
                actor=actor,
            )
            created_by_actor_id = actor.id
        else:
            raise AcademicAuthorizationError(
                "Only administrators and teachers can manage questions"
            )

        allowed_bank_ids = {bank.id for bank in banks}
        if bank_id is not None:
            if bank_id not in allowed_bank_ids:
                raise AcademicAuthorizationError(
                    "You are not allowed to manage questions in this bank"
                )
            bank_ids = [bank_id]
        else:
            bank_ids = list(allowed_bank_ids)

        return await QuestionRepository.list_questions_for_banks(
            db,
            bank_ids,
            created_by_actor_id=created_by_actor_id,
            active_only=active_only,
            offset=offset,
            limit=limit,
        )

    @staticmethod
    async def get_actor_question(
        db: AsyncSession,
        *,
        actor: LocalActor,
        question_id: UUID,
    ) -> Question:
        question = await QuestionRepository.get_question_by_id(db, question_id)
        if question is None:
            raise ValueError("Question does not exist")

        bank = await QuestionRepository.get_bank_by_id(db, question.bank_id)
        if bank is None:
            raise ValueError("Question bank does not exist")

        await AcademicAuthorizationService.require_can_author_curriculum_subject(
            db,
            actor=actor,
            curriculum_subject_id=bank.curriculum_subject_id,
        )
        return question

    @staticmethod
    async def get_actor_question_option(
        db: AsyncSession,
        *,
        actor: LocalActor,
        question_id: UUID,
        option_id: UUID,
    ) -> QuestionOption:
        question = await QuestionService.get_actor_question(
            db,
            actor=actor,
            question_id=question_id,
        )
        option = await QuestionRepository.get_option_by_id(db, option_id)
        if option is None or option.question_id != question.id:
            raise ValueError("Question option does not exist")
        return option

    @staticmethod
    async def update_question(
        db: AsyncSession,
        *,
        actor: LocalActor,
        question_id: UUID,
        payload: QuestionUpdate,
    ) -> Question:
        question = await QuestionRepository.get_question_by_id(
            db,
            question_id,
            lock=True,
        )
        if question is None:
            raise ValueError("Question does not exist")
        if not question.is_active:
            raise ValueError("Archived questions must be reactivated before editing")

        bank = await QuestionRepository.get_bank_by_id(db, question.bank_id)
        if bank is None:
            raise ValueError("Question bank does not exist")
        if not bank.is_active:
            raise ValueError("Questions inside an archived bank cannot be edited")

        await AcademicAuthorizationService.require_can_author_curriculum_subject(
            db,
            actor=actor,
            curriculum_subject_id=bank.curriculum_subject_id,
        )
        _require_can_manage_question(actor=actor, question=question)

        if (
            payload.expected_version is not None
            and payload.expected_version != question.version
        ):
            raise QuestionConflictError(
                "This question changed after you opened it. Refresh and review the latest version before saving again."
            )

        fields = payload.model_fields_set - {"expected_version"}
        changed = False
        old_image_asset_id = question.image_asset_id
        old_option_image_ids: set[UUID] = set()
        next_option_image_ids: set[UUID] = set()

        if "prompt" in fields:
            if payload.prompt is None:
                raise ValueError("Question prompt cannot be null")
            prompt = _normalize_required_text(payload.prompt)
            if prompt is None:
                raise ValueError("Question prompt cannot be empty")
            if prompt != question.prompt:
                question.prompt = prompt
                changed = True

        if "instruction" in fields:
            instruction = _normalize_optional_text(payload.instruction)
            if instruction != question.instruction:
                question.instruction = instruction
                changed = True

        if "image_asset_id" in fields:
            next_image_id = await _resolve_updated_question_image(
                db,
                actor=actor,
                question=question,
                requested_image_asset_id=payload.image_asset_id,
            )
            if next_image_id != question.image_asset_id:
                question.image_asset_id = next_image_id
                changed = True

        normalized_options: list[tuple[str | None, UUID | None, bool]] | None = None
        options_changed = False
        if "options" in fields:
            if payload.options is None:
                raise ValueError("Question options cannot be null")
            current_options = await QuestionRepository.list_options_for_question(
                db,
                question.id,
            )
            old_option_image_ids = {
                option.image_asset_id
                for option in current_options
                if option.image_asset_id is not None
            }
            normalized_options = _normalize_and_validate_options(
                payload.options,
                question_type=question.question_type,
            )
            normalized_options = await _resolve_updated_option_images(
                db,
                actor=actor,
                normalized_options=normalized_options,
                current_options=current_options,
            )
            next_option_image_ids = {
                image_asset_id
                for _, image_asset_id, _ in normalized_options
                if image_asset_id is not None
            }
            current_values = [
                (option.text, option.image_asset_id, option.is_correct)
                for option in current_options
            ]
            if normalized_options != current_values:
                options_changed = True
                changed = True

        if not changed:
            await db.commit()
            return question

        question.version += 1
        question.last_edited_by_actor_id = actor.id
        question = await QuestionRepository.save_question(db, question)

        if options_changed and normalized_options is not None:
            await QuestionRepository.remove_options_for_question(db, question.id)
            await QuestionRepository.add_options(
                db,
                [
                    QuestionOption(
                        question_id=question.id,
                        position=position,
                        text=text,
                        image_asset_id=option_image_asset_id,
                        is_correct=is_correct,
                    )
                    for position, (
                        text,
                        option_image_asset_id,
                        is_correct,
                    ) in enumerate(
                        normalized_options,
                        start=1,
                    )
                ],
            )

        await db.commit()

        cleanup_ids: set[UUID] = set()
        if (
            old_image_asset_id is not None
            and old_image_asset_id != question.image_asset_id
        ):
            cleanup_ids.add(old_image_asset_id)
        cleanup_ids.update(old_option_image_ids - next_option_image_ids)
        await _cleanup_unreferenced_media(
            db,
            asset_ids=cleanup_ids,
            log_context=f"updated question {question.id}",
        )

        return question

    @staticmethod
    async def archive_question(
        db: AsyncSession,
        *,
        actor: LocalActor,
        question_id: UUID,
    ) -> Question:
        question = await QuestionRepository.get_question_by_id(
            db,
            question_id,
            lock=True,
        )
        if question is None:
            raise ValueError("Question does not exist")

        bank = await QuestionRepository.get_bank_by_id(db, question.bank_id)
        if bank is None:
            raise ValueError("Question bank does not exist")

        await AcademicAuthorizationService.require_can_author_curriculum_subject(
            db,
            actor=actor,
            curriculum_subject_id=bank.curriculum_subject_id,
        )
        _require_can_manage_question(actor=actor, question=question)

        if question.is_active:
            question.is_active = False
            question = await QuestionRepository.save_question(db, question)
        await db.commit()
        return question

    @staticmethod
    async def reactivate_question(
        db: AsyncSession,
        *,
        actor: LocalActor,
        question_id: UUID,
    ) -> Question:
        question = await QuestionRepository.get_question_by_id(
            db,
            question_id,
            lock=True,
        )
        if question is None:
            raise ValueError("Question does not exist")

        bank = await QuestionRepository.get_bank_by_id(db, question.bank_id)
        if bank is None:
            raise ValueError("Question bank does not exist")
        if not bank.is_active:
            raise ValueError("A question cannot be reactivated inside an archived bank")

        await AcademicAuthorizationService.require_can_author_curriculum_subject(
            db,
            actor=actor,
            curriculum_subject_id=bank.curriculum_subject_id,
        )
        _require_can_manage_question(actor=actor, question=question)

        if not question.is_active:
            question.is_active = True
            question = await QuestionRepository.save_question(db, question)
        await db.commit()
        return question

    @staticmethod
    async def delete_unused_question(
        db: AsyncSession,
        *,
        actor: LocalActor,
        question_id: UUID,
    ) -> None:
        question = await QuestionRepository.get_question_by_id(
            db,
            question_id,
            lock=True,
        )
        if question is None:
            raise ValueError("Question does not exist")

        bank = await QuestionRepository.get_bank_by_id(db, question.bank_id)
        if bank is None:
            raise ValueError("Question bank does not exist")

        await AcademicAuthorizationService.require_can_author_curriculum_subject(
            db,
            actor=actor,
            curriculum_subject_id=bank.curriculum_subject_id,
        )
        _require_can_manage_question(actor=actor, question=question)

        if await ExamRepository.is_source_question_referenced(db, question.id):
            raise ValueError(
                "A question already used by an exam cannot be deleted; archive it instead"
            )

        options = await QuestionRepository.list_options_for_question(db, question.id)
        media_asset_ids = {
            option.image_asset_id
            for option in options
            if option.image_asset_id is not None
        }
        if question.image_asset_id is not None:
            media_asset_ids.add(question.image_asset_id)

        await QuestionRepository.delete_question(db, question)
        await db.commit()

        await _cleanup_unreferenced_media(
            db,
            asset_ids=media_asset_ids,
            log_context=f"deleted question {question_id}",
        )
