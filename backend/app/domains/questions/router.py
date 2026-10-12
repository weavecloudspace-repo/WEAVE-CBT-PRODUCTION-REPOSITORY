from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from app.core.database import DbSession
from app.core.exceptions import AcademicAuthorizationError, AcademicScopeError
from app.domains.auth.dependencies import CurrentLocalActor, CurrentLocalAdmin
from app.domains.media.service import MediaService
from app.domains.questions.response_builder import (
    build_question_bank_responses,
    build_question_response,
    build_question_responses,
)
from app.domains.questions.schemas import (
    MultipleChoiceQuestionCreate,
    QuestionBankCreate,
    QuestionBankResponse,
    QuestionBankUpdate,
    QuestionResponse,
    QuestionUpdate,
    SingleChoiceQuestionCreate,
)
from app.domains.questions.service import QuestionService

router = APIRouter(
    prefix="/questions",
    tags=["Questions"],
)


def _domain_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AcademicAuthorizationError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )

    if isinstance(exc, AcademicScopeError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    detail = str(exc)
    lowered = detail.lower()

    if "does not exist" in lowered:
        code = status.HTTP_404_NOT_FOUND
    elif any(
        marker in lowered
        for marker in (
            "cannot",
            "inactive",
            "archived",
            "already used",
            "containing questions",
        )
    ):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST

    return HTTPException(status_code=code, detail=detail)


@router.post(
    "/banks/{curriculum_subject_id}",
    response_model=QuestionBankResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_question_bank(
    curriculum_subject_id: UUID,
    payload: QuestionBankCreate,
    db: DbSession,
    actor: CurrentLocalAdmin,
) -> QuestionBankResponse:
    try:
        bank = await QuestionService.create_question_bank(
            db,
            actor=actor,
            curriculum_subject_id=curriculum_subject_id,
            payload=payload,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return (await build_question_bank_responses(db, [bank], request_actor=actor))[0]


@router.get(
    "/banks/authorable",
    response_model=list[QuestionBankResponse],
)
async def list_authorable_question_banks(
    db: DbSession,
    actor: CurrentLocalActor,
) -> list[QuestionBankResponse]:
    try:
        banks = await QuestionService.list_actor_authorable_question_banks(
            db,
            actor=actor,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return await build_question_bank_responses(db, banks, request_actor=actor)


@router.get(
    "/banks",
    response_model=list[QuestionBankResponse],
)
async def list_admin_question_banks(
    db: DbSession,
    actor: CurrentLocalAdmin,
    curriculum_subject_id: UUID | None = None,
    include_archived: bool = False,
) -> list[QuestionBankResponse]:
    """Admin management list; archived banks remain discoverable for reactivation."""

    try:
        banks = await QuestionService.list_admin_question_banks(
            db,
            actor=actor,
            curriculum_subject_id=curriculum_subject_id,
            include_archived=include_archived,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return await build_question_bank_responses(db, banks, request_actor=actor)


@router.patch(
    "/banks/{bank_id}",
    response_model=QuestionBankResponse,
)
async def update_question_bank(
    bank_id: UUID,
    payload: QuestionBankUpdate,
    db: DbSession,
    actor: CurrentLocalAdmin,
) -> QuestionBankResponse:
    try:
        bank = await QuestionService.update_question_bank(
            db,
            actor=actor,
            bank_id=bank_id,
            payload=payload,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return (await build_question_bank_responses(db, [bank], request_actor=actor))[0]


@router.post(
    "/banks/{bank_id}/archive",
    response_model=QuestionBankResponse,
)
async def archive_question_bank(
    bank_id: UUID,
    db: DbSession,
    actor: CurrentLocalAdmin,
) -> QuestionBankResponse:
    try:
        bank = await QuestionService.archive_question_bank(
            db,
            actor=actor,
            bank_id=bank_id,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return (await build_question_bank_responses(db, [bank], request_actor=actor))[0]


@router.post(
    "/banks/{bank_id}/reactivate",
    response_model=QuestionBankResponse,
)
async def reactivate_question_bank(
    bank_id: UUID,
    db: DbSession,
    actor: CurrentLocalAdmin,
) -> QuestionBankResponse:
    try:
        bank = await QuestionService.reactivate_question_bank(
            db,
            actor=actor,
            bank_id=bank_id,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return (await build_question_bank_responses(db, [bank], request_actor=actor))[0]


@router.delete(
    "/banks/{bank_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_empty_question_bank(
    bank_id: UUID,
    db: DbSession,
    actor: CurrentLocalAdmin,
) -> Response:
    try:
        await QuestionService.delete_empty_question_bank(
            db,
            actor=actor,
            bank_id=bank_id,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/banks/{bank_id}/single-choice",
    response_model=QuestionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_single_choice_question(
    bank_id: UUID,
    payload: SingleChoiceQuestionCreate,
    db: DbSession,
    actor: CurrentLocalActor,
) -> QuestionResponse:
    try:
        question = await QuestionService.create_single_choice_question(
            db,
            actor=actor,
            bank_id=bank_id,
            payload=payload,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return await build_question_response(db, question, request_actor=actor)


@router.post(
    "/banks/{bank_id}/multiple-choice",
    response_model=QuestionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_multiple_choice_question(
    bank_id: UUID,
    payload: MultipleChoiceQuestionCreate,
    db: DbSession,
    actor: CurrentLocalActor,
) -> QuestionResponse:
    try:
        question = await QuestionService.create_multiple_choice_question(
            db,
            actor=actor,
            bank_id=bank_id,
            payload=payload,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return await build_question_response(db, question, request_actor=actor)


@router.get(
    "/banks/{bank_id}/items",
    response_model=list[QuestionResponse],
)
async def list_questions_for_bank(
    bank_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
    include_archived: bool = False,
) -> list[QuestionResponse]:
    try:
        questions = await QuestionService.list_actor_questions_for_bank(
            db,
            actor=actor,
            bank_id=bank_id,
            active_only=not include_archived,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return await build_question_responses(db, questions, request_actor=actor)


@router.get(
    "/{question_id}",
    response_model=QuestionResponse,
)
async def get_question(
    question_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> QuestionResponse:
    try:
        question = await QuestionService.get_actor_question(
            db,
            actor=actor,
            question_id=question_id,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return await build_question_response(db, question, request_actor=actor)


@router.get("/{question_id}/image")
async def get_question_image(
    question_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> Response:
    try:
        question = await QuestionService.get_actor_question(
            db,
            actor=actor,
            question_id=question_id,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    if question.image_asset_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question does not have an image.",
        )

    content = await MediaService.load_asset_content(
        db,
        asset_id=question.image_asset_id,
    )

    # This URL identifies the mutable source question rather than the immutable
    # asset. Do not cache it across edits or a replaced image can look stale.
    return Response(
        content=content.data,
        media_type=content.mime_type,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{question_id}/options/{option_id}/image")
async def get_question_option_image(
    question_id: UUID,
    option_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> Response:
    try:
        option = await QuestionService.get_actor_question_option(
            db,
            actor=actor,
            question_id=question_id,
            option_id=option_id,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    if option.image_asset_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question option does not have an image.",
        )

    content = await MediaService.load_asset_content(db, asset_id=option.image_asset_id)
    return Response(
        content=content.data,
        media_type=content.mime_type,
        headers={"Cache-Control": "no-store"},
    )


@router.patch(
    "/{question_id}",
    response_model=QuestionResponse,
)
async def update_question(
    question_id: UUID,
    payload: QuestionUpdate,
    db: DbSession,
    actor: CurrentLocalActor,
) -> QuestionResponse:
    try:
        question = await QuestionService.update_question(
            db,
            actor=actor,
            question_id=question_id,
            payload=payload,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return await build_question_response(db, question, request_actor=actor)


@router.post(
    "/{question_id}/archive",
    response_model=QuestionResponse,
)
async def archive_question(
    question_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> QuestionResponse:
    try:
        question = await QuestionService.archive_question(
            db,
            actor=actor,
            question_id=question_id,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return await build_question_response(db, question, request_actor=actor)


@router.post(
    "/{question_id}/reactivate",
    response_model=QuestionResponse,
)
async def reactivate_question(
    question_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> QuestionResponse:
    try:
        question = await QuestionService.reactivate_question(
            db,
            actor=actor,
            question_id=question_id,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return await build_question_response(db, question, request_actor=actor)


@router.delete(
    "/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_unused_question(
    question_id: UUID,
    db: DbSession,
    actor: CurrentLocalActor,
) -> Response:
    try:
        await QuestionService.delete_unused_question(
            db,
            actor=actor,
            question_id=question_id,
        )
    except (AcademicAuthorizationError, AcademicScopeError, ValueError) as exc:
        raise _domain_http_error(exc) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)
