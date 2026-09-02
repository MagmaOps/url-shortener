"""URL management endpoints.

POST /api/urls                — shorten a URL.
GET  /api/urls/{short_code}   — look up metadata for a short code.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.repositories.url_repository import URLRepository
from app.schemas import URLCreateRequest, URLDetailResponse, URLResponse
from app.services.url_service import URLService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/urls", tags=["urls"])


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------


def get_url_repository(session: AsyncSession = Depends(get_session)) -> URLRepository:
    """FastAPI dependency that provides a ``URLRepository`` bound to the current session."""
    return URLRepository(session)


def get_url_service(
    repository: URLRepository = Depends(get_url_repository),
) -> URLService:
    """FastAPI dependency that provides a ``URLService`` with the current repository."""
    settings = get_settings()
    return URLService(repository=repository, base_url=settings.base_url)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=URLResponse)
async def create_short_url(
    body: URLCreateRequest,
    service: URLService = Depends(get_url_service),
    settings=Depends(get_settings),
) -> URLResponse:
    """Shorten a URL and return the created record.

    - Accepts a JSON body with ``url`` (HTTP or HTTPS only).
    - Returns HTTP 201 on success with ``id``, ``short_code``, ``url``,
      ``short_url``, and ``created_at``.
    - FastAPI / Pydantic returns 422 automatically for invalid or missing input.

    Requirements: 1.1, 1.4, 1.5
    """
    original_url = str(body.url)
    record = await service.create_short_url(original_url)
    base_url = settings.base_url.rstrip("/")
    return URLResponse(
        id=record.id,
        short_code=record.short_code,
        url=record.original_url,
        short_url=f"{base_url}/{record.short_code}",
        created_at=record.created_at,
    )


@router.get("/{short_code}", response_model=URLDetailResponse)
async def get_url_detail(
    short_code: str,
    repository: URLRepository = Depends(get_url_repository),
    settings=Depends(get_settings),
) -> URLDetailResponse:
    """Return metadata for a short code, including click count.

    - Returns 200 with ``id``, ``short_code``, ``url``, ``short_url``,
      ``created_at``, and ``clicks`` when the short code exists.
    - Returns 404 when the short code is not found.

    Requirements: 3.1, 3.2
    """
    record = await repository.get_by_short_code(short_code)
    if record is None:
        raise HTTPException(status_code=404, detail="Short URL not found")

    base_url = settings.base_url.rstrip("/")
    return URLDetailResponse(
        id=record.id,
        short_code=record.short_code,
        url=record.original_url,
        short_url=f"{base_url}/{record.short_code}",
        created_at=record.created_at,
        clicks=record.clicks,
    )
