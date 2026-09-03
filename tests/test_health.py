"""Integration tests for health and readiness endpoints.

Covers:
- GET /health → 200 {"status": "ok"}
- GET /ready  → 200 {"status": "ready"}   (database reachable)
- GET /ready  → 503 {"status": "not_ready"} (database unreachable)

Requirements: 4.1, 4.2, 4.3, 11.1
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from app.routes.health import router


# ---------------------------------------------------------------------------
# Minimal app fixture — health router only, no DB connection at import time.
# We override the `get_session` dependency per-test so we never need a live DB
# for the health endpoint and can fully control the readiness probe behaviour.
# ---------------------------------------------------------------------------


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture()
def app() -> FastAPI:
    return _build_app()


@pytest.fixture()
async def client(app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Test 4.1 — /health returns 200 {"status": "ok"} without DB involvement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_200_ok(client: AsyncClient) -> None:
    """GET /health → 200 {"status": "ok"} regardless of database state.

    Requirements: 4.1
    """
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Test 4.2 — /ready returns 200 {"status": "ready"} when DB is reachable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ready_returns_200_when_db_is_reachable(app: FastAPI) -> None:
    """GET /ready → 200 {"status": "ready"} when the database is reachable.

    The get_session dependency is overridden to yield a mock session whose
    execute() succeeds (simulating a live DB responding to SELECT 1).

    Requirements: 4.2
    """
    # Build a mock async session whose execute() call succeeds silently.
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=None)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    async def _good_session():
        yield mock_session

    from app.database import get_session

    app.dependency_overrides[get_session] = _good_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


# ---------------------------------------------------------------------------
# Test 4.3 — /ready returns 503 {"status": "not_ready"} when DB is unreachable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ready_returns_503_when_db_is_unreachable(app: FastAPI) -> None:
    """GET /ready → 503 {"status": "not_ready"} when the database is unreachable.

    The get_session dependency is overridden to yield a mock session whose
    execute() raises an OperationalError (simulating a broken DB connection).

    Requirements: 4.3
    """
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        side_effect=OperationalError("connection refused", None, None)
    )
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    async def _bad_session():
        yield mock_session

    from app.database import get_session

    app.dependency_overrides[get_session] = _bad_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
