"""Local read endpoints for the cached effective CBT branding."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.database import DbSession
from app.domains.branding.schemas import BrandingResponse
from app.domains.branding.service import branding_service

router = APIRouter(prefix="/branding", tags=["Branding"])


@router.get("", response_model=BrandingResponse)
async def get_branding(
    db: DbSession,
    response: Response,
) -> BrandingResponse:
    """Return local branding even when Weave Cloud is unavailable."""

    response.headers["Cache-Control"] = "no-store"
    return await branding_service.get_effective(db)


@router.get("/logo")
async def get_branding_logo(
    db: DbSession,
    request: Request,
) -> Response:
    """Serve the locally cached tenant logo; never proxy the browser to Weave."""

    logo = await branding_service.get_cached_logo(db)
    if logo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No tenant logo is cached on this CBT server.",
        )

    etag = f'"{logo.sha256}"'
    headers = {
        "Cache-Control": "public, max-age=3600",
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    return Response(
        content=logo.content,
        media_type=logo.mime_type,
        headers=headers,
    )
