"""Integration tests for the URL lookup endpoint.

GET /api/urls/{short_code} — retrieve metadata for a shortened URL.

Covers:
- Existing short code → 200 with all required fields (Req 3.1)
- All field values match the stored record (Req 3.1)
- short_url == BASE_URL + "/" + short_code (Req 3.1)
- clicks field reflects stored count (Req 3.1)
- Non-existing short code → 404 {"detail": "Short URL not found"} (Req 3.2)

Requirements: 3.1, 3.2, 11.1
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.models import URLRecord
from app.repositories.url_repository import URLRepository
from app.routes.urls import get_url_repository, router


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "http://short.example.com"
_ORIGINAL_URL = "https://www.example.com/a/very/long/path?q=something"
_SHORT_CODE = "aB82xKqZ"
_CLICK_COUNT = 7


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    short_code: str = _SHORT_CODE,
    original_url: str = _ORIGINAL_URL,
    clicks: int = _CLICK_COUNT,
) -> URLRecord:
    """Return a URLRecord matching the default test constants."""
    return URLRecord(
        id=42,
        short_code=short_code,
        original_url=original_url,
        created_at=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        clicks=clicks,
    )


def _make_settings() -> Settings:
    """Return a Settings object with test values (no .env file required)."""
    return Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test",
        base_url=_BASE_URL,
        log_level="INFO",
    )


def _make_mock_repository(record: URLRecord | None) -> MagicMock:
    """Return a MagicMock URLRepository whose get_by_short_code returns *record*."""
    mock_repo = MagicMock(spec=URLRepository)
    mock_repo.get_by_short_code = AsyncMock(return_value=record)
    return mock_repo


def _build_app(mock_repo: MagicMock) -> FastAPI:
    """Build a minimal FastAPI app with the urls router.

    Overrides ``get_url_repository`` and ``get_settings`` so no database or
    environment variables are needed during testing.
    """
    app = FastAPI()
    app.include_router(router)

    test_settings = _make_settings()
    app.dependency_overrides[get_url_repository] = lambda: mock_repo
    app.dependency_overrides[get_settings] = lambda: test_settings
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def record() -> URLRecord:
    return _make_record()


@pytest.fixture()
def mock_repo(record: URLRecord) -> MagicMock:
    return _make_mock_repository(record=record)


@pytest.fixture()
def app(mock_repo: MagicMock) -> FastAPI:
    return _build_app(mock_repo)


@pytest.fixture()
async def client(app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Test 3.1 — existing short code → 200 with all required fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_returns_200_for_existing_short_code(
    client: AsyncClient,
) -> None:
    """GET /api/urls/{short_code} with a known code → HTTP 200.

    Requirements: 3.1
    """
    response = await client.get(f"/api/urls/{_SHORT_CODE}")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_lookup_response_contains_all_required_fields(
    client: AsyncClient,
) -> None:
    """Response body contains id, short_code, url, short_url, created_at, clicks.

    Requirements: 3.1
    """
    response = await client.get(f"/api/urls/{_SHORT_CODE}")

    assert response.status_code == 200
    body = response.json()

    for field in ("id", "short_code", "url", "short_url", "created_at", "clicks"):
        assert field in body, f"Missing required field: {field}"


@pytest.mark.asyncio
async def test_lookup_field_values_match_stored_record(
    client: AsyncClient, record: URLRecord
) -> None:
    """Field values in the response match the values from the stored URLRecord.

    Requirements: 3.1
    """
    response = await client.get(f"/api/urls/{_SHORT_CODE}")

    assert response.status_code == 200
    body = response.json()

    assert body["id"] == record.id
    assert body["short_code"] == record.short_code
    assert body["url"] == record.original_url
    assert body["clicks"] == record.clicks
    assert body["created_at"] is not None


@pytest.mark.asyncio
async def test_lookup_short_url_equals_base_url_plus_short_code(
    client: AsyncClient, record: URLRecord
) -> None:
    """short_url in the response equals BASE_URL + "/" + short_code.

    Requirements: 3.1
    """
    response = await client.get(f"/api/urls/{_SHORT_CODE}")

    assert response.status_code == 200
    expected_short_url = f"{_BASE_URL.rstrip('/')}/{record.short_code}"
    assert response.json()["short_url"] == expected_short_url


@pytest.mark.asyncio
async def test_lookup_clicks_field_reflects_stored_count() -> None:
    """The clicks field returns whatever count is stored in the URLRecord.

    Tests with a non-zero click count to ensure the value is passed through.

    Requirements: 3.1
    """
    click_count = 42
    record = _make_record(clicks=click_count)
    mock_repo = _make_mock_repository(record=record)
    app = _build_app(mock_repo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get(f"/api/urls/{_SHORT_CODE}")

    assert response.status_code == 200
    assert response.json()["clicks"] == click_count


@pytest.mark.asyncio
async def test_lookup_clicks_zero_for_new_url() -> None:
    """A newly created URL with zero clicks returns clicks == 0.

    Requirements: 3.1
    """
    record = _make_record(clicks=0)
    mock_repo = _make_mock_repository(record=record)
    app = _build_app(mock_repo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get(f"/api/urls/{_SHORT_CODE}")

    assert response.status_code == 200
    assert response.json()["clicks"] == 0


@pytest.mark.asyncio
async def test_lookup_queries_repository_with_correct_short_code(
    client: AsyncClient, mock_repo: MagicMock
) -> None:
    """The repository is queried with the exact short code from the URL path.

    Requirements: 3.1
    """
    await client.get(f"/api/urls/{_SHORT_CODE}")

    mock_repo.get_by_short_code.assert_called_once_with(_SHORT_CODE)


# ---------------------------------------------------------------------------
# Test 3.2 — non-existing short code → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_returns_404_for_nonexistent_short_code() -> None:
    """GET /api/urls/{short_code} with an unknown code → HTTP 404.

    Requirements: 3.2
    """
    mock_repo = _make_mock_repository(record=None)
    app = _build_app(mock_repo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/urls/nonexistent")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_lookup_404_body_matches_spec() -> None:
    """GET /api/urls/nonexistent → exact JSON body {"detail": "Short URL not found"}.

    Requirements: 3.2
    """
    mock_repo = _make_mock_repository(record=None)
    app = _build_app(mock_repo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/urls/nonexistent")

    assert response.status_code == 404
    assert response.json() == {"detail": "Short URL not found"}


@pytest.mark.asyncio
async def test_lookup_404_different_short_codes_all_return_404() -> None:
    """Any unregistered short code consistently returns 404.

    Requirements: 3.2
    """
    mock_repo = _make_mock_repository(record=None)
    app = _build_app(mock_repo)

    codes = ["unknown1", "AAAAAAAA", "12345678", "zzzzzzzz"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        for code in codes:
            response = await ac.get(f"/api/urls/{code}")
            assert response.status_code == 404, f"Expected 404 for code '{code}'"
            assert response.json() == {"detail": "Short URL not found"}
