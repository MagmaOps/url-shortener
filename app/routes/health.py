"""Health and readiness check endpoints.

GET /health  — liveness probe; no database call.
GET /ready   — readiness probe; executes ``SELECT 1`` against the database.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> JSONResponse:
    """Liveness probe — returns 200 without touching the database.

    Requirements: 4.1
    """
    return JSONResponse({"status": "ok"})


@router.get("/ready")
async def ready(session: AsyncSession = Depends(get_session)) -> JSONResponse:
    """Readiness probe — verifies database connectivity with a lightweight query.

    Returns 200 when the database is reachable, 503 otherwise.

    Requirements: 4.2, 4.3
    """
    try:
        await session.execute(text("SELECT 1"))
        return JSONResponse({"status": "ready"})
    except Exception:
        logger.exception("Readiness check failed — database is unreachable")
        return JSONResponse({"status": "not_ready"}, status_code=503)
