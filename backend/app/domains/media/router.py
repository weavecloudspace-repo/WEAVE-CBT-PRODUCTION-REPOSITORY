from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.core.database import DbSession
from app.core.settings import settings
from app.domains.auth.dependencies import CurrentLocalActor
from app.domains.media.schemas import MediaAssetResponse
from app.domains.media.service import MediaService

router = APIRouter(
    prefix="/media",
    tags=["Media"],
)


@router.post(
    "/question-images",
    response_model=MediaAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_question_image(
    db: DbSession,
    actor: CurrentLocalActor,
    file: Annotated[UploadFile, File(...)],
) -> MediaAssetResponse:
    """Upload and normalize one locally stored question image."""

    try:
        data = await file.read(settings.MEDIA_MAX_IMAGE_SIZE_BYTES + 1)

        if len(data) > settings.MEDIA_MAX_IMAGE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Uploaded image exceeds the maximum allowed size.",
            )

        try:
            asset = await MediaService.upload_question_image(
                db,
                actor=actor,
                original_filename=file.filename,
                data=data,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        return MediaAssetResponse.model_validate(asset)

    finally:
        await file.close()
