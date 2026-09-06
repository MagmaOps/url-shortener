"""Integration tests for the Prometheus metrics endpoint and middleware.

Covers:
- GET /metrics → 200 with the Prometheus text exposition content type, and the
  response body includes all five required metric names.
- Requests to /metrics, /health, /ready are excluded from http_requests_total,
  while a normal (non-excluded) route is included.

These tests build a minimal FastAPI app that mirrors the wiring in
``app.main.create_app`` (MetricsMiddleware + a /metrics route) but avoids
requiring a live database or environment configuration. The Prometheus metrics
are module-level singletons shared across the process, so assertions target the
*presence or absence of specific label sets* (which path labels appear) rather
than absolute counter values, keeping the tests robust to metric state that
accumulates across the test session.

Requirements: 5.1, 5.2, 5.3, 5.5, 11.1
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from prometheus_client import generate_latest
from starlette.responses import Response

from app.database import get_session
from app.middleware.metrics import (
    MetricsMiddleware,
    http_requests_total,
)
from app.routes.health import router as health_router


# The five metric names that MUST be exposed by GET /metrics (Requirement 5.1).
_REQUIRED_METRIC_NAMES = (
    "http_requests_total",
    "http_request_duration_seconds",
    "url_shortener_urls_created_total",
    "url_shortener_redirects_total",
    "url_shortener_errors_total",
)

# Paths that MUST be excluded from http_requests_total (Requirement 5.5).
_EXCLUDED_PATHS = ("/metrics", "/health", "/ready")

# A normal route used to prove non-excluded requests ARE counted.
_NORMAL_PATH = "/ping"


# ---------------------------------------------------------------------------
# App / client fixtures
# ---------------------------------------------------------------------------


def _build_app() -> FastAPI:
    """Build a minimal app wired like ``app.main.create_app``.

    Registers the MetricsMiddleware, the /metrics scrape route, the health
    router (so /health and /ready can be exercised), and a trivial /ping route
    that stands in for a normal, non-excluded application endpoint. No database
    or environment configuration is required.
    """
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(
            content=generate_latest(),
            media_type="text/plain; version=0.0.4",
        )

    @app.get(_NORMAL_PATH)
    async def ping() -> dict[str, str]:
        return {"status": "pong"}

    app.include_router(health_router)

    # Override get_session with a mock so /ready resolves without a live DB or
    # environment configuration. The exclusion behaviour under test depends only
    # on the request path, not on the readiness response outcome.
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=None)

    async def _mock_session():
        yield mock_session

    app.dependency_overrides[get_session] = _mock_session
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
# Helpers
# ---------------------------------------------------------------------------


def _http_requests_total_path_labels() -> set[str]:
    """Return the set of ``path`` label values currently present on
    ``http_requests_total`` across the shared process registry."""
    labels: set[str] = set()
    for metric in http_requests_total.collect():
        for sample in metric.samples:
            path = sample.labels.get("path")
            if path is not None:
                labels.add(path)
    return labels


# ---------------------------------------------------------------------------
# Test 5.1 — /metrics exposes all five required metric names
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_200(client: AsyncClient) -> None:
    """GET /metrics → 200 with the Prometheus text exposition content type.

    Requirements: 5.1, 5.2, 5.3
    """
    response = await client.get("/metrics")

    assert response.status_code == 200
    # Starlette appends "; charset=utf-8" to text/* media types.
    assert response.headers["content-type"].startswith("text/plain; version=0.0.4")


@pytest.mark.asyncio
async def test_metrics_endpoint_includes_all_five_metric_names(
    client: AsyncClient,
) -> None:
    """GET /metrics response body includes all five required metric names.

    Requirements: 5.1
    """
    response = await client.get("/metrics")

    assert response.status_code == 200
    body = response.text

    for metric_name in _REQUIRED_METRIC_NAMES:
        assert metric_name in body, f"metric {metric_name!r} missing from /metrics output"


# ---------------------------------------------------------------------------
# Test 5.5 — excluded paths are not counted in http_requests_total
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_excluded_paths_not_counted_in_http_requests_total(
    client: AsyncClient,
) -> None:
    """Requests to /metrics, /health, /ready are excluded from http_requests_total.

    Exercises each excluded path and asserts none of them ever appear as a
    ``path`` label on http_requests_total. Because the metric is a shared
    process-level singleton, we assert on the *absence of these specific labels*
    rather than on absolute counts.

    Requirements: 5.5
    """
    # Hit each excluded path. /ready may return 200 or 503 depending on the DB
    # dependency resolving; either way it must not be counted.
    await client.get("/metrics")
    await client.get("/health")
    await client.get("/ready")

    path_labels = _http_requests_total_path_labels()

    for excluded in _EXCLUDED_PATHS:
        assert (
            excluded not in path_labels
        ), f"excluded path {excluded!r} was counted in http_requests_total"


@pytest.mark.asyncio
async def test_non_excluded_path_is_counted_in_http_requests_total(
    client: AsyncClient,
) -> None:
    """A normal (non-excluded) request IS counted in http_requests_total.

    This is the positive counterpart to the exclusion test: it confirms the
    middleware records ordinary traffic, so the exclusion assertions above are
    meaningful rather than trivially true.

    Requirements: 5.2, 5.5
    """
    await client.get(_NORMAL_PATH)

    path_labels = _http_requests_total_path_labels()

    assert _NORMAL_PATH in path_labels
