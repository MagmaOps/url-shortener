"""Property-based tests for URL lifecycle behaviors.

Feature: url-shortener, Property 4: Input Validation Rejects Non-HTTP/HTTPS URLs

Validates: Requirements 1.4, 1.5
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.config import Settings, get_settings
from app.routes.urls import get_url_service, router
from app.services.url_service import URLService


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_BASE_URL = "http://short.example.com"


def _make_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test",
        base_url=_BASE_URL,
        log_level="INFO",
    )


def _make_mock_service() -> MagicMock:
    """Return a URLService mock.

    Validation happens at the Pydantic layer, so the service should never
    be called when invalid input is submitted. The side_effect here would
    expose a bug if that assumption were violated.
    """
    mock_service = MagicMock(spec=URLService)
    mock_service.create_short_url = AsyncMock(
        side_effect=AssertionError("Service must not be called for invalid input")
    )
    return mock_service


def _build_test_client() -> TestClient:
    """Build a FastAPI TestClient with the urls router and mocked dependencies."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_url_service] = _make_mock_service
    app.dependency_overrides[get_settings] = _make_settings
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Schemes that are explicitly NOT http or https
_NON_HTTP_SCHEMES = st.sampled_from([
    "ftp",
    "ftps",
    "mailto",
    "javascript",
    "file",
    "data",
    "ssh",
    "sftp",
    "telnet",
    "irc",
    "ldap",
    "ldaps",
    "ws",
    "wss",
    "git",
    "svn",
    "magnet",
    "blob",
])

# "scheme://..." strings whose scheme is not http or https
_non_http_url_strategy = st.builds(
    lambda scheme, rest: f"{scheme}://{rest}",
    scheme=_NON_HTTP_SCHEMES,
    rest=st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters=".-/_?=&",
        ),
        min_size=1,
        max_size=60,
    ),
)

# Arbitrary strings that are clearly not valid HTTP/HTTPS URLs
_arbitrary_non_url_strategy = st.one_of(
    st.text(max_size=200),                                    # fully random text
    st.from_regex(r"[A-Za-z0-9_\-]{1,40}", fullmatch=True),  # identifier-like strings
    st.just(""),                                              # empty string
    st.just("not-a-url"),
    st.just("//missing-scheme.com"),
    st.just("://no-scheme"),
    st.just("12345"),
    st.just("http"),                                          # scheme only, no authority
    st.just("https"),
)

# Combined: either a non-http-scheme URL or an arbitrary non-URL string
_invalid_url_strategy = st.one_of(_non_http_url_strategy, _arbitrary_non_url_strategy)


# ---------------------------------------------------------------------------
# Property 4 — Input Validation Rejects Non-HTTP/HTTPS URLs
# ---------------------------------------------------------------------------

# Build a single client once; Hypothesis re-uses the same process so this is safe.
_client = _build_test_client()


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(invalid_url=_invalid_url_strategy)
def test_input_validation_rejects_non_http_https_urls(invalid_url: str) -> None:
    """Property 4: Input Validation Rejects Non-HTTP/HTTPS URLs.

    For any URL string whose scheme is not http or https (including ftp://,
    javascript:, mailto:, arbitrary strings, or empty input), submitting it
    to POST /api/urls always returns HTTP 422.

    Validates: Requirements 1.4, 1.5
    """
    # Feature: url-shortener, Property 4: Input Validation Rejects Non-HTTP/HTTPS URLs
    response = _client.post("/api/urls", json={"url": invalid_url})

    assert response.status_code == 422, (
        f"Expected 422 for invalid URL {invalid_url!r}, got {response.status_code}"
    )
