"""Property-based and example tests for the request logging middleware.

Feature: url-shortener, Property 11: Request Log Completeness

Every emitted request log entry MUST contain ``timestamp``, ``level``,
``method``, ``path``, ``status_code``, and ``duration_ms``; and no log entry
may contain the ``DATABASE_URL`` value, passwords, or request body content.

Validates: Requirements 8.2, 8.3
"""

from __future__ import annotations

import json
import logging
from typing import List

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from starlette.testclient import TestClient

from app.middleware.logging import (
    JSONFormatter,
    LoggingMiddleware,
    access_logger,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The six fields every request log entry MUST contain (Requirement 8.2).
_REQUIRED_LOG_FIELDS = (
    "timestamp",
    "level",
    "method",
    "path",
    "status_code",
    "duration_ms",
)

# A DATABASE_URL value (with an embedded password) that must never be logged
# by the request access log (Requirement 8.3).
_SECRET_DB_URL = "postgresql+asyncpg://app_user:sup3rs3cr3tpw@db.internal:5432/urls"
_SECRET_PASSWORD = "sup3rs3cr3tpw"

# A password-shaped value submitted in a request body — must never be logged.
_BODY_SECRET = "hunter2-body-secret"


# ---------------------------------------------------------------------------
# Log capture helper
# ---------------------------------------------------------------------------


class _JSONLogCapture(logging.Handler):
    """A logging handler that captures both the parsed record fields and the
    fully formatted JSON string produced by :class:`JSONFormatter`.

    Capturing the *formatted* output (not just the ``LogRecord``) lets us assert
    the no-leak property against exactly what would be written to stdout.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.setFormatter(JSONFormatter())
        self.records: List[logging.LogRecord] = []
        self.formatted: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        self.formatted.append(self.format(record))

    @property
    def entries(self) -> List[dict]:
        """Return each captured log line parsed back into a dict."""
        return [json.loads(line) for line in self.formatted]


def _build_app() -> FastAPI:
    """Build a minimal app wrapped with only the LoggingMiddleware.

    Routes cover a normal success path, a path that echoes a request body
    (so we can prove bodies are never logged), and an error path (so we can
    prove non-2xx statuses are still logged completely). No database or
    environment configuration is required.
    """
    app = FastAPI()
    app.add_middleware(LoggingMiddleware)

    @app.get("/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/echo")
    async def echo(payload: dict) -> dict:
        # The handler *reads* the body, but the middleware must not log it.
        return {"received": True}

    @app.get("/boom")
    async def boom() -> JSONResponse:
        # Return a 500 (rather than raising) so the middleware observes the
        # final response and still emits its access-log entry. The embedded
        # secret is in the *body* — which the access log must never contain.
        return JSONResponse(
            status_code=500,
            content={"error": f"secret in error: {_SECRET_DB_URL}"},
        )

    return app


def _capture() -> _JSONLogCapture:
    """Attach a capture handler to the access logger and return it.

    Caller is responsible for detaching via :func:`_detach`.
    """
    handler = _JSONLogCapture()
    access_logger.addHandler(handler)
    # Ensure INFO-level access records are not filtered out.
    access_logger.setLevel(logging.INFO)
    # Let records reach our handler regardless of ancestor configuration.
    access_logger.propagate = False
    return handler


def _detach(handler: logging.Handler) -> None:
    access_logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# Property 11 — Request Log Completeness (property-based)
# ---------------------------------------------------------------------------

# Path segments Hypothesis will assemble into request paths. Constrained to a
# safe URL-ish alphabet so the generated paths remain routable/parseable. Each
# segment is non-empty (``min_size=1``) so joining with a single leading slash
# always yields a client-sendable path beginning with exactly one "/" (never
# "//"). httpx's TestClient rejects authority-less paths that start with "//"
# before the request is sent, which would bypass the middleware entirely; a
# non-empty-segment constraint keeps every generated path exercising the
# middleware while still covering multi-segment paths.
_segment = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_",
    min_size=1,
    max_size=12,
)
_path_strategy = st.lists(_segment, min_size=1, max_size=4).map(
    lambda parts: "/" + "/".join(parts)
)


@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
@given(path=_path_strategy)
def test_every_request_log_entry_is_complete(path: str) -> None:
    """Property 11: Request Log Completeness.

    For any request path, the single access-log entry emitted for the request
    contains all six required fields with sensible values.

    Validates: Requirements 8.2

    Feature: url-shortener, Property 11: Request Log Completeness
    """
    app = _build_app()
    handler = _capture()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            client.get(path)

        # Exactly one access-log entry should be emitted per request.
        assert len(handler.entries) == 1, (
            f"expected exactly one log entry, got {len(handler.entries)}"
        )

        entry = handler.entries[0]
        for field in _REQUIRED_LOG_FIELDS:
            assert field in entry, (
                f"log entry missing required field {field!r}: {entry!r}"
            )

        assert entry["method"] == "GET"
        # The path field is present and is a non-empty string that starts with
        # "/". We do not assert exact equality with the generated path because
        # the ASGI server normalizes paths (e.g. collapsing "//" to "/"); the
        # completeness property only requires the field be recorded.
        assert isinstance(entry["path"], str) and entry["path"].startswith("/")
        assert isinstance(entry["status_code"], int)
        assert isinstance(entry["duration_ms"], (int, float))
        assert entry["duration_ms"] >= 0
    finally:
        _detach(handler)


# Distinctive secret-shaped tokens. A fixed, recognizable prefix ensures the
# generated value cannot collide incidentally with the log's structural
# content (timestamps, numeric durations, field names), so any match is a real
# leak of body content rather than a false positive.
_body_secret_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    min_size=1,
    max_size=32,
).map(lambda s: f"BODYSECRET_{s}_XYZZY")


@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
@given(secret=_body_secret_strategy)
def test_request_body_content_never_appears_in_logs(secret: str) -> None:
    """Property 11: no request body content leaks into the access log.

    For arbitrary secret-shaped body content posted to an endpoint, the emitted
    access-log line must not contain that content.

    Validates: Requirements 8.3

    Feature: url-shortener, Property 11: Request Log Completeness
    """
    app = _build_app()
    handler = _capture()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            client.post("/echo", json={"password": secret, "token": secret})

        assert len(handler.entries) == 1
        line = handler.formatted[0]
        assert secret not in line, (
            f"request body secret leaked into log line: {line!r}"
        )
    finally:
        _detach(handler)


# ---------------------------------------------------------------------------
# Property 11 — No-leak (example-based)
# ---------------------------------------------------------------------------


def test_database_url_and_password_never_logged() -> None:
    """The DATABASE_URL value and its embedded password must never be logged.

    Passes the secret as a query string (a common leak vector) and asserts it
    appears in neither the parsed ``path`` field nor the raw formatted line.

    Validates: Requirements 8.3

    Feature: url-shortener, Property 11: Request Log Completeness
    """
    app = _build_app()
    handler = _capture()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            client.get(f"/ok?db={_SECRET_DB_URL}&password={_SECRET_PASSWORD}")

        assert len(handler.entries) == 1
        entry = handler.entries[0]
        line = handler.formatted[0]

        # Only the path (no query string) should be logged.
        assert entry["path"] == "/ok"
        assert "?" not in entry["path"]

        assert _SECRET_DB_URL not in line
        assert _SECRET_PASSWORD not in line
        assert "DATABASE_URL" not in line
    finally:
        _detach(handler)


def test_error_response_still_logged_completely_without_leak() -> None:
    """A request that triggers a 500 still produces one complete log entry
    that does not leak the secret embedded in the raised exception.

    Validates: Requirements 8.2, 8.3

    Feature: url-shortener, Property 11: Request Log Completeness
    """
    app = _build_app()
    handler = _capture()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom")

        assert response.status_code == 500
        assert len(handler.entries) == 1
        entry = handler.entries[0]
        line = handler.formatted[0]

        for field in _REQUIRED_LOG_FIELDS:
            assert field in entry, f"missing field {field!r}: {entry!r}"

        assert entry["status_code"] == 500
        assert entry["path"] == "/boom"
        # The exception text (which embeds the DB URL) must not be in the
        # request access-log line.
        assert _SECRET_DB_URL not in line
        assert _SECRET_PASSWORD not in line
    finally:
        _detach(handler)


def test_successful_request_logs_expected_field_values() -> None:
    """A simple GET /ok produces a complete, well-formed access-log entry.

    Validates: Requirements 8.2

    Feature: url-shortener, Property 11: Request Log Completeness
    """
    app = _build_app()
    handler = _capture()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/ok")

        assert response.status_code == 200
        assert len(handler.entries) == 1
        entry = handler.entries[0]

        assert set(_REQUIRED_LOG_FIELDS).issubset(entry.keys())
        assert entry["method"] == "GET"
        assert entry["path"] == "/ok"
        assert entry["status_code"] == 200
        assert entry["level"] == "INFO"
        assert isinstance(entry["duration_ms"], (int, float))
        assert entry["duration_ms"] >= 0
        # ISO-8601 timestamp with timezone offset.
        assert isinstance(entry["timestamp"], str) and "T" in entry["timestamp"]
    finally:
        _detach(handler)
