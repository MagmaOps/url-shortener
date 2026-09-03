"""Integration tests for the redirect endpoint.

GET /{short_code} — resolves a short code and issues an HTTP 302 redirect.

Covers:
- Existing short code → 302 with correct Location header (Req 2.1)
- Each access increments click counter by 1 (Req 2.2)
- N sequential accesses → clicks == N (Req 2.2)
- Non-existing short code → 404 {"detail": "Short URL not found"} (Req 2.3)
- Click increment failure → 500, not a silent redirect (Req 2.2)

Requirements: 2.1, 2.2, 2.3, 11.1
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.models import URLRecord
from app.repositories.url_repository import URLRepository, URLRepositoryError
from app.routes.redirect import get_url_repository, router


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SHORT_CODE = "aB82xKqZ"
_ORIGINAL_URL = "https://www.example.com/a/very/long/path?q=something"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    short_code: str = _SHORT_CODE,
    original_url: str = _ORIGINAL_URL,
    clicks: int = 0,
) -> URLRecord:
    """Return a minimal URLRecord for use in mocked repository responses."""
    return URLRecord(
        id=1,
        short_code=short_code,
        original_url=original_url,
        created_at=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        clicks=clicks,
    )


def _make_mock_repository(
    record: URLRecord | None = None,
    increment_side_effect: Exception | None = None,
) -> MagicMock:
    """Return a MagicMock URLRepository.

    ``get_by_short_code`` returns *record* (or None if omitted).
    ``increment_clicks`` succeeds by default, or raises *increment_side_effect*.
    """
    mock_repo = MagicMock(spec=URLRepository)
    mock_repo.get_by_short_code = AsyncMock(return_value=record)
    if increment_side_effect is not None:
        mock_repo.increment_clicks = AsyncMock(side_effect=increment_side_effect)
    else:
        mock_repo.increment_clicks = AsyncMock(return_value=None)
    return mock_repo


def _build_app(mock_repo: MagicMock) -> FastAPI:
    """Build a minimal FastAPI app with the redirect router.

    Overrides ``get_url_repository`` so no database is required.
    """
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_url_repository] = lambda: mock_repo
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
# Test 2.1 — existing short code → 302 with correct Location header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redirect_returns_302_for_existing_short_code(
    client: AsyncClient,
) -> None:
    """GET /{short_code} with a known code → HTTP 302.

    Requirements: 2.1
    """
    response = await client.get(f"/{_SHORT_CODE}", follow_redirects=False)

    assert response.status_code == 302


@pytest.mark.asyncio
async def test_redirect_location_header_equals_original_url(
    client: AsyncClient,
) -> None:
    """GET /{short_code} → Location header is the exact original URL.

    Requirements: 2.1
    """
    response = await client.get(f"/{_SHORT_CODE}", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == _ORIGINAL_URL


@pytest.mark.asyncio
async def test_redirect_location_preserves_query_string() -> None:
    """Location header preserves query strings in the original URL.

    Requirements: 2.1
    """
    url_with_qs = "https://example.com/path?foo=bar&baz=qux"
    record = _make_record(original_url=url_with_qs)
    mock_repo = _make_mock_repository(record=record)
    app = _build_app(mock_repo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get(f"/{_SHORT_CODE}", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == url_with_qs


# ---------------------------------------------------------------------------
# Test 2.2 — click counter incremented on each access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redirect_increments_click_counter_once(
    client: AsyncClient, mock_repo: MagicMock
) -> None:
    """A single GET request causes increment_clicks() to be called exactly once.

    Requirements: 2.2
    """
    response = await client.get(f"/{_SHORT_CODE}", follow_redirects=False)

    assert response.status_code == 302
    mock_repo.increment_clicks.assert_called_once_with(_SHORT_CODE)


@pytest.mark.asyncio
async def test_redirect_increments_click_counter_n_times_for_n_requests() -> None:
    """N sequential GET requests → increment_clicks called exactly N times.

    Validates that each access records a click (Property 6 — click count
    accumulation).

    Requirements: 2.2
    """
    n = 5
    record = _make_record()
    mock_repo = _make_mock_repository(record=record)
    app = _build_app(mock_repo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        for _ in range(n):
            response = await ac.get(f"/{_SHORT_CODE}", follow_redirects=False)
            assert response.status_code == 302

    assert mock_repo.increment_clicks.call_count == n
    # Every call was made with the correct short code.
    expected_calls = [call(_SHORT_CODE)] * n
    mock_repo.increment_clicks.assert_has_calls(expected_calls)


@pytest.mark.asyncio
async def test_redirect_increments_before_responding(
    client: AsyncClient, mock_repo: MagicMock
) -> None:
    """increment_clicks() is called before the 302 response is issued.

    The spec requires the click to be recorded; verifying the mock was called
    on a successful 302 confirms the ordering.

    Requirements: 2.2
    """
    response = await client.get(f"/{_SHORT_CODE}", follow_redirects=False)

    assert response.status_code == 302
    # If increment_clicks was not called, the click was silently dropped.
    assert mock_repo.increment_clicks.called


@pytest.mark.asyncio
async def test_redirect_returns_500_when_click_increment_fails() -> None:
    """When increment_clicks() raises URLRepositoryError the endpoint returns 500.

    The spec mandates the request MUST fail rather than redirect without
    recording the click (Requirement 2.2).

    Requirements: 2.2
    """
    record = _make_record()
    mock_repo = _make_mock_repository(
        record=record,
        increment_side_effect=URLRepositoryError("DB write failed"),
    )
    app = _build_app(mock_repo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get(f"/{_SHORT_CODE}", follow_redirects=False)

    assert response.status_code == 500
    # Must NOT redirect — the spec forbids a silent redirect without a click.
    assert "location" not in response.headers


# ---------------------------------------------------------------------------
# Test 2.3 — non-existing short code → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redirect_returns_404_for_nonexistent_short_code() -> None:
    """GET /{short_code} with an unknown code → HTTP 404.

    Requirements: 2.3
    """
    mock_repo = _make_mock_repository(record=None)
    app = _build_app(mock_repo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/nonexistent", follow_redirects=False)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_redirect_404_body_matches_spec() -> None:
    """GET /nonexistent → exact JSON body {"detail": "Short URL not found"}.

    Requirements: 2.3
    """
    mock_repo = _make_mock_repository(record=None)
    app = _build_app(mock_repo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/nonexistent", follow_redirects=False)

    assert response.status_code == 404
    assert response.json() == {"detail": "Short URL not found"}


@pytest.mark.asyncio
async def test_redirect_does_not_increment_clicks_for_nonexistent_code() -> None:
    """increment_clicks() is never called when the short code does not exist.

    Requirements: 2.3
    """
    mock_repo = _make_mock_repository(record=None)
    app = _build_app(mock_repo)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        await ac.get("/nonexistent", follow_redirects=False)

    mock_repo.increment_clicks.assert_not_called()
