"""Short code redirect endpoint.

GET /{short_code} — resolves a short code and issues an HTTP 302 redirect.

The click counter is incremented atomically *before* the redirect is issued.
If the increment fails, the request returns a 5xx error rather than redirecting
without recording the click (as required by Requirement 2.2 / 2.3).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.repositories.url_repository import URLRepository, URLRepositoryError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["redirect"])


def get_url_repository(session: AsyncSession = Depends(get_session)) -> URLRepository:
    """FastAPI dependency that provides a ``URLRepository`` bound to the current session."""
    return URLRepository(session)


@router.get("/{short_code}")
async def redirect_short_code(
    short_code: str,
    repository: URLRepository = Depends(get_url_repository),
) -> RedirectResponse:
    """Redirect a short code to the original URL.

    1. Looks up the short code in the database.
    2. Returns 404 if not found.
    3. Atomically increments the click counter.
    4. Returns HTTP 302 with ``Location`` set to the original URL.

    If the click counter update fails, the request fails with HTTP 500 rather
    than silently redirecting without recording the click.

    Requirements: 2.1, 2.2, 2.3
    """
    record = await repository.get_by_short_code(short_code)
    if record is None:
        raise HTTPException(status_code=404, detail="Short URL not found")

    try:
        await repository.increment_clicks(short_code)
    except URLRepositoryError:
        logger.exception(
            "Failed to increment click counter for short_code %r — aborting redirect",
            short_code,
        )
        # Surface as 500: the spec requires the request to fail rather than
        # redirect without recording the click (Requirement 2.2).
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        )

    return RedirectResponse(url=record.original_url, status_code=302)
