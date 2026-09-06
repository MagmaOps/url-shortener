"""FastAPI application factory and lifecycle management.

This module creates the FastAPI application, registers all routers, wires up
dependencies, configures the lifespan context manager, and installs a global
exception handler that prevents implementation details from leaking to clients.

Requirements: 9.1, 9.2, 10.1
"""

from __future__ import annotations

import logging
import traceback
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import generate_latest

from app.config import get_settings
from app.database import dispose_engine
from app.middleware.metrics import MetricsMiddleware, url_shortener_errors_total
from app.routes import health, redirect, urls

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown.

    Startup:
      - Validates that required configuration is present (Settings raises on
        missing DATABASE_URL / BASE_URL before the server accepts traffic).
      - Database connectivity is intentionally *not* required here — the
        /ready endpoint is responsible for that check.

    Shutdown:
      - Disposes the SQLAlchemy async engine to cleanly release all pooled
        database connections before the process exits.
    """
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info(
        "URL Shortener starting up (base_url=%s, log_level=%s)",
        settings.base_url,
        settings.log_level,
    )

    yield  # Application runs here

    logger.info("URL Shortener shutting down — disposing database engine")
    await dispose_engine()
    logger.info("Database engine disposed; shutdown complete")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="URL Shortener",
        description="A minimal URL shortener API built with FastAPI and PostgreSQL.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # Middleware
    # ------------------------------------------------------------------
    app.add_middleware(MetricsMiddleware)

    # ------------------------------------------------------------------
    # Prometheus scrape endpoint
    #
    # Registered BEFORE the routers so it takes precedence over the
    # ``GET /{short_code}`` catch-all redirect route (Starlette matches routes
    # in registration order — the catch-all would otherwise swallow /metrics).
    # ------------------------------------------------------------------

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        """Expose Prometheus metrics in the standard text exposition format.

        Requirements: 5.1, 5.2, 5.3
        """
        # Media type is the Prometheus text exposition format. Starlette
        # appends "; charset=utf-8" for text/* responses, yielding the
        # canonical "text/plain; version=0.0.4; charset=utf-8".
        return Response(
            content=generate_latest(),
            media_type="text/plain; version=0.0.4",
        )

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    app.include_router(health.router)
    app.include_router(urls.router)
    app.include_router(redirect.router)

    # ------------------------------------------------------------------
    # Global exception handler
    # ------------------------------------------------------------------

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Catch all unhandled exceptions and return a safe HTTP 500 response.

        - Logs the full traceback at ERROR level (server-side only).
        - Increments the ``url_shortener_errors_total`` Prometheus counter.
        - Returns ``{"detail": "Internal server error"}`` — no stack traces,
          SQL error text, or database connection details in the response body.

        Requirements: 9.1, 9.2
        """
        logger.error(
            "Unhandled exception on %s %s\n%s",
            request.method,
            request.url.path,
            traceback.format_exc(),
        )
        url_shortener_errors_total.inc()
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app


# Module-level app instance consumed by uvicorn:
#   uvicorn app.main:app --host 0.0.0.0 --port 8000
app = create_app()
