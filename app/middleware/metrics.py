"""Prometheus metrics middleware and metric definitions.

This module defines the application's Prometheus metrics and a Starlette
``BaseHTTPMiddleware`` subclass that records per-request metrics.

Metrics are defined at module level so they register exactly once against the
default Prometheus registry. ``url_shortener_errors_total`` is imported by
``app.main`` for use inside the global exception handler — it must be the same
object here to avoid a duplicate-registration ``ValueError``.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""

from __future__ import annotations

import time

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

# ---------------------------------------------------------------------------
# Metric definitions (module level — registered once)
# ---------------------------------------------------------------------------

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests (excludes /metrics, /health, /ready)",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds (excludes /metrics, /health, /ready)",
    ["method", "path", "status"],
)

url_shortener_urls_created_total = Counter(
    "url_shortener_urls_created_total",
    "Total number of URLs shortened",
)

url_shortener_redirects_total = Counter(
    "url_shortener_redirects_total",
    "Total number of successful redirects",
)

url_shortener_errors_total = Counter(
    "url_shortener_errors_total",
    "Total number of error responses returned by the URL Shortener",
)

# Paths excluded from generic HTTP request/duration metrics.
_EXCLUDED_PATHS = frozenset({"/metrics", "/health", "/ready"})


def _route_template(request: Request) -> str:
    """Return the matched route template for a request.

    Using the route template (e.g. ``/api/urls/{short_code}``) rather than the
    raw request path keeps Prometheus label cardinality bounded — individual
    short codes do not each create a distinct time series.

    Falls back to the raw path when no route matched (e.g. a 404 that never hit
    a registered route).
    """
    route = request.scope.get("route")
    path_format = getattr(route, "path_format", None) or getattr(route, "path", None)
    if path_format:
        return path_format
    return request.url.path


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records Prometheus metrics for each HTTP request.

    - Times the request and records ``http_request_duration_seconds``.
    - Increments ``http_requests_total`` labelled by method, route template,
      and status. Both metrics skip the ``/metrics``, ``/health``, and
      ``/ready`` paths.
    - Increments ``url_shortener_urls_created_total`` on a 201 from
      ``POST /api/urls``.
    - Increments ``url_shortener_redirects_total`` on any 302 response.
    - Increments ``url_shortener_errors_total`` on any 4xx/5xx response.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        raw_path = request.url.path
        method = request.method
        status = response.status_code

        # Generic HTTP metrics — excluded for infra/observability endpoints.
        if raw_path not in _EXCLUDED_PATHS:
            path_label = _route_template(request)
            status_label = str(status)
            http_requests_total.labels(
                method=method, path=path_label, status=status_label
            ).inc()
            http_request_duration_seconds.labels(
                method=method, path=path_label, status=status_label
            ).observe(duration)

        # Domain-specific counters.
        if status == 201 and method == "POST" and raw_path == "/api/urls":
            url_shortener_urls_created_total.inc()

        if status == 302:
            url_shortener_redirects_total.inc()

        if status >= 400:
            url_shortener_errors_total.inc()

        return response
