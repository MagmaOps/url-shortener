"""Integration tests for the URL creation endpoint.

POST /api/urls — shorten a URL.

Covers:
- Valid HTTPS URL → 201, all response fields present, short_url format correct
- Valid HTTP URL → 201 (AnyHttpUrl accepts both schemes)
- Invalid scheme (ftp://) → 422
- Empty request body → 422
- Missing url field → 422
- Plaintext (non-URL) string → 422
- Null url value → 422
- Response uses 201 (not 200)

Requirements: 1.1, 1.4, 1.5, 9.2, 11.1
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.models import URLRecord
from app.routes.urls import get_url_service, router
from app.services.url_service import URLService


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "http://short.example.com"
_ORIGINAL_URL = "https://www.example.com/a/very/long/path?q=something"
_SHORT_CODE = "aB82xKqZ"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(short_code: str = _SHORT_CODE, original_url: str = _ORIGINAL_URL) -> URLRecord:
    """Return a minimal URLRecord suitable for mocking service responses."""
    return URLRecord(
        id=1,
        short_code=short_code,
        original_url=original_url,
        created_at=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        clicks=0,
    )


def _make_settings() -> Settings:
    """Return a Settings object with test values (no .env file or env vars needed)."""
    return Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test",
        base_url=_BASE_URL,
        log_level="INFO",
    )


def _make_mock_service(record: URLRecord | None = None) -> MagicMock:
    """Return a MagicMock URLService whose create_short_url returns *record*."""
    mock_service = MagicMock(spec=URLService)
    mock_service.create_short_url = AsyncMock(return_value=record or _make_record())
    return mock_service


def _build_app(mock_service: MagicMock) -> FastAPI:
    """Build a minimal FastAPI app with the urls router.

    Overrides both ``get_url_service`` (to avoid DB) and ``get_settings``
    (to avoid requiring DATABASE_URL / BASE_URL env vars at test time).
    """
    app = FastAPI()
    app.include_router(router)

    test_settings = _make_settings()
    app.dependency_overrides[get_url_service] = lambda: mock_service
    app.dependency_overrides[get_settings] = lambda: test_settings
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def record() -> URLRecord:
    return _make_record()


@pytest.fixture()
def mock_service(record: URLRecord) -> MagicMock:
    return _make_mock_service(record)


@pytest.fixture()
def app(mock_service: MagicMock) -> FastAPI:
    return _build_app(mock_service)


@pytest.fixture()
async def client(app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Test 1.1 — valid HTTPS URL → 201 with all required fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_short_url_returns_201_with_all_fields(
    client: AsyncClient, record: URLRecord
) -> None:
    """POST /api/urls with a valid HTTPS URL → 201 with all response fields.

    Asserts:
    - HTTP 201 status code
    - Response body contains: id, short_code, url, short_url, created_at
    - Field values match the mocked URLRecord

    Requirements: 1.1
    """
    response = await client.post("/api/urls", json={"url": _ORIGINAL_URL})

    assert response.status_code == 201

    body = response.json()
    assert "id" in body
    assert "short_code" in body
    assert "url" in body
    assert "short_url" in body
    assert "created_at" in body

    assert body["id"] == record.id
    assert body["short_code"] == record.short_code
    assert body["url"] == record.original_url
    assert body["created_at"] is not None


@pytest.mark.asyncio
async def test_create_short_url_short_url_equals_base_url_plus_short_code(
    client: AsyncClient, record: URLRecord
) -> None:
    """short_url in the response equals BASE_URL + "/" + short_code.

    Requirements: 1.1
    """
    response = await client.post("/api/urls", json={"url": _ORIGINAL_URL})

    assert response.status_code == 201
    body = response.json()

    expected_short_url = f"{_BASE_URL.rstrip('/')}/{record.short_code}"
    assert body["short_url"] == expected_short_url


@pytest.mark.asyncio
async def test_create_short_url_accepts_http_url(record: URLRecord) -> None:
    """POST /api/urls with a valid HTTP (non-HTTPS) URL → 201.

    AnyHttpUrl accepts both http:// and https:// schemes.

    Requirements: 1.1
    """
    http_url = "http://example.com/path"
    http_record = _make_record(original_url=http_url)
    mock_service = _make_mock_service(http_record)

    app = _build_app(mock_service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/urls", json={"url": http_url})

    assert response.status_code == 201
    assert response.json()["url"] == http_url


@pytest.mark.asyncio
async def test_create_short_url_service_called_with_original_url(
    client: AsyncClient, mock_service: MagicMock
) -> None:
    """The service receives the original URL string from the request body.

    Pydantic V2 AnyHttpUrl may normalise the URL slightly (e.g. add trailing
    slash for bare hostnames), so we verify scheme and host rather than exact
    string equality.

    Requirements: 1.1
    """
    await client.post("/api/urls", json={"url": _ORIGINAL_URL})

    mock_service.create_short_url.assert_called_once()
    called_url: str = mock_service.create_short_url.call_args[0][0]
    assert called_url.startswith("https://")
    assert "example.com" in called_url


# ---------------------------------------------------------------------------
# Test 1.4 — non-HTTP/HTTPS scheme → 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_short_url_rejects_ftp_scheme(client: AsyncClient) -> None:
    """POST /api/urls with ftp:// scheme → 422 validation error.

    Requirements: 1.4
    """
    response = await client.post("/api/urls", json={"url": "ftp://bad.example.com/file"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_short_url_rejects_javascript_scheme(client: AsyncClient) -> None:
    """POST /api/urls with javascript: scheme → 422 validation error.

    Requirements: 1.4
    """
    response = await client.post("/api/urls", json={"url": "javascript:alert(1)"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_short_url_rejects_mailto_scheme(client: AsyncClient) -> None:
    """POST /api/urls with mailto: scheme → 422 validation error.

    Requirements: 1.4
    """
    response = await client.post("/api/urls", json={"url": "mailto:user@example.com"})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Test 1.5 — missing or malformed body → 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_short_url_rejects_empty_body(client: AsyncClient) -> None:
    """POST /api/urls with an empty body → 422 validation error.

    Requirements: 1.5
    """
    response = await client.post(
        "/api/urls",
        content=b"",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_short_url_rejects_missing_url_field(client: AsyncClient) -> None:
    """POST /api/urls with a JSON body that omits the url field → 422.

    Requirements: 1.5
    """
    response = await client.post("/api/urls", json={"other_field": "value"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_short_url_rejects_plaintext_body(client: AsyncClient) -> None:
    """POST /api/urls with a non-URL string as the url value → 422.

    Requirements: 1.5
    """
    response = await client.post("/api/urls", json={"url": "not-a-url-at-all"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_short_url_rejects_null_url(client: AsyncClient) -> None:
    """POST /api/urls with url set to null → 422 validation error.

    Requirements: 1.5
    """
    response = await client.post("/api/urls", json={"url": None})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Test 9.2 — correct HTTP status codes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_short_url_uses_201_not_200(client: AsyncClient) -> None:
    """Successful URL creation MUST return 201 Created, not 200 OK.

    Requirements: 9.2
    """
    response = await client.post("/api/urls", json={"url": _ORIGINAL_URL})

    assert response.status_code == 201
    assert response.status_code != 200
