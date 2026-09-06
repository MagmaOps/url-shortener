"""Property-based and integration tests for error handling behavior.

Feature: url-shortener, Property 10: Safe Error Responses

Validates: Requirements 9.1
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.main import create_app
from app.routes.urls import get_url_service, router as urls_router
from app.services.url_service import URLService


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_BASE_URL = "http://short.example.com"

# SQL-flavoured strings that must never appear in client responses.
_SQL_FRAGMENTS = [
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "FROM",
    "WHERE",
    "postgresql",
    "asyncpg",
    "sqlalchemy",
    "psycopg",
]

# Python traceback markers that must never appear in client responses.
_TRACEBACK_MARKERS = [
    "Traceback",
    "File \"",
    "line ",
    "raise ",
    "Error:",
    "Exception:",
]


def _make_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test",
        base_url=_BASE_URL,
        log_level="INFO",
    )


def _make_exploding_service(exc: Exception) -> MagicMock:
    """Return a URLService mock whose create_short_url raises *exc*."""
    mock_service = MagicMock(spec=URLService)
    mock_service.create_short_url = AsyncMock(side_effect=exc)
    return mock_service


def _build_app_with_failing_service(exc: Exception) -> FastAPI:
    """Return the full app (with the global exception handler) wired to a
    service that raises *exc* on every call to create_short_url.

    Using ``create_app()`` ensures the global ``@app.exception_handler(Exception)``
    installed in main.py is present — a minimal FastAPI() would not have it.
    """
    app = create_app()

    exploding_service = _make_exploding_service(exc)
    app.dependency_overrides[get_url_service] = lambda: exploding_service
    app.dependency_overrides[get_settings] = _make_settings

    return app


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A variety of unexpected exceptions that could escape the service layer
_exception_strategy = st.one_of(
    st.builds(RuntimeError, st.text(max_size=120)),
    st.builds(ValueError, st.text(max_size=120)),
    st.builds(
        OSError,
        st.text(max_size=80),
    ),
    st.builds(
        Exception,
        st.text(max_size=120),
    ),
    # Simulate something that looks like a DB error leaking through
    st.builds(
        RuntimeError,
        st.just(
            "sqlalchemy.exc.OperationalError: (asyncpg.exceptions.ConnectionFailureError) "
            "connection to server at 'db:5432' failed"
        ),
    ),
    st.builds(
        RuntimeError,
        st.just(
            "psycopg2.OperationalError: FATAL: password authentication failed for user 'app'"
        ),
    ),
)


# ---------------------------------------------------------------------------
# Property 10 — Safe Error Responses
# ---------------------------------------------------------------------------


@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
@given(exc=_exception_strategy)
def test_safe_error_responses_status_and_body(exc: Exception) -> None:
    """Property 10: Safe Error Responses — status code and body shape.

    For any unhandled server-side exception propagated from the service layer,
    the HTTP response MUST be 500 with the exact body
    ``{"detail": "Internal server error"}``.

    Validates: Requirements 9.1

    Feature: url-shortener, Property 10: Safe Error Responses
    """
    app = _build_app_with_failing_service(exc)

    # Use a synchronous TestClient here so the test is compatible with
    # Hypothesis (which does not support async test functions directly).
    from fastapi.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/urls",
        json={"url": "https://example.com/some/long/path"},
    )

    assert response.status_code == 500, (
        f"Expected 500, got {response.status_code} for exception {exc!r}"
    )
    assert response.json() == {"detail": "Internal server error"}, (
        f"Unexpected response body: {response.json()!r}"
    )


@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
@given(exc=_exception_strategy)
def test_safe_error_responses_no_traceback_or_sql_in_body(exc: Exception) -> None:
    """Property 10: Safe Error Responses — no implementation details leaked.

    For any unhandled server-side exception, the response body MUST NOT
    contain Python traceback markers, SQL keywords, or database driver names.

    Validates: Requirements 9.1

    Feature: url-shortener, Property 10: Safe Error Responses
    """
    app = _build_app_with_failing_service(exc)

    from fastapi.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/urls",
        json={"url": "https://example.com/some/long/path"},
    )

    body_text = response.text

    for marker in _TRACEBACK_MARKERS:
        assert marker not in body_text, (
            f"Response body contains traceback marker {marker!r}: {body_text!r}"
        )

    for fragment in _SQL_FRAGMENTS:
        assert fragment not in body_text, (
            f"Response body contains SQL/DB fragment {fragment!r}: {body_text!r}"
        )


# ---------------------------------------------------------------------------
# Example-based integration tests for Property 10
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runtime_error_returns_500_safe_body() -> None:
    """RuntimeError in the service layer → 500 with exactly {"detail": "Internal server error"}.

    Validates: Requirements 9.1
    """
    app = _build_app_with_failing_service(RuntimeError("something went wrong internally"))

    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.post(
            "/api/urls",
            json={"url": "https://example.com/path"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


@pytest.mark.asyncio
async def test_value_error_returns_500_safe_body() -> None:
    """ValueError in the service layer → 500 with exactly {"detail": "Internal server error"}.

    Validates: Requirements 9.1
    """
    app = _build_app_with_failing_service(ValueError("unexpected value in processing"))

    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.post(
            "/api/urls",
            json={"url": "https://example.com/path"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


@pytest.mark.asyncio
async def test_db_error_string_not_in_response_body() -> None:
    """A DB-flavoured error message raised in the service layer must not leak into the response.

    Validates: Requirements 9.1
    """
    db_error = RuntimeError(
        "sqlalchemy.exc.OperationalError: (asyncpg.exceptions.TooManyConnectionsError) "
        "sorry, too many clients already\nDATABASE_URL=postgresql+asyncpg://user:secret@db/app"
    )
    app = _build_app_with_failing_service(db_error)

    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.post(
            "/api/urls",
            json={"url": "https://example.com/path"},
        )

    assert response.status_code == 500
    body_text = response.text
    # The raw exception message (with SQL and connection details) must not appear
    assert "sqlalchemy" not in body_text
    assert "DATABASE_URL" not in body_text
    assert "secret" not in body_text
    assert response.json() == {"detail": "Internal server error"}


@pytest.mark.asyncio
async def test_exception_with_traceback_not_in_response_body() -> None:
    """Python traceback text must never appear in the HTTP response body.

    Validates: Requirements 9.1
    """
    app = _build_app_with_failing_service(RuntimeError("boom"))

    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.post(
            "/api/urls",
            json={"url": "https://example.com/path"},
        )

    body_text = response.text
    assert "Traceback" not in body_text
    assert "raise " not in body_text
    assert response.status_code == 500
