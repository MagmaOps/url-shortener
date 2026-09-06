"""Structured request logging middleware and logging configuration.

This module provides:

- ``configure_logging`` — configures the root logger to emit structured JSON
  log records to stdout, respecting ``Settings.log_level``. All application logs
  go to stdout so container runtimes / log aggregators can collect them without
  extra configuration; nothing is written to log files inside the container.
- ``LoggingMiddleware`` — a Starlette ``BaseHTTPMiddleware`` subclass that emits
  exactly one structured log entry per HTTP request containing ``timestamp``,
  ``level``, ``method``, ``path``, ``status_code``, and ``duration_ms``.

For safety, request bodies, ``Authorization`` headers, query strings, and the
raw ``DATABASE_URL`` are never logged — only the URL path (without the query
component) is recorded.

Requirements: 8.1, 8.2, 8.3
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

# Logger used for the per-request access log entries.
access_logger = logging.getLogger("app.access")

# Standard ``LogRecord`` attributes — everything else attached to a record is
# treated as a structured "extra" field and merged into the JSON output.
_RESERVED_LOG_RECORD_ATTRS = frozenset(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime"}


class JSONFormatter(logging.Formatter):
    """Format ``LogRecord`` instances as single-line JSON objects.

    Always includes ``timestamp`` (ISO 8601, UTC), ``level``, ``logger``, and
    ``message``. Any structured fields passed via ``extra=`` (for example the
    per-request ``method``/``path``/``status_code``/``duration_ms``) are merged
    into the top-level object.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Merge structured extras (skip reserved LogRecord attributes).
        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOG_RECORD_ATTRS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(log_level: str) -> None:
    """Configure the root logger to emit structured JSON logs to stdout.

    Replaces any existing handlers on the root logger with a single
    ``StreamHandler`` bound to ``sys.stdout`` using :class:`JSONFormatter`.
    This deliberately writes only to stdout — no file handlers are configured,
    so application logs are never written to files inside the container.

    ``log_level`` is matched case-insensitively against the standard logging
    levels; an unrecognized value falls back to ``INFO``.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


class LoggingMiddleware(BaseHTTPMiddleware):
    """Emit one structured log entry per HTTP request.

    The ``dispatch`` method records the start time, invokes the downstream
    handler, computes the request duration in milliseconds, and logs a single
    structured record with ``method``, ``path``, ``status_code``, and
    ``duration_ms``. The ``timestamp`` and ``level`` fields are supplied by the
    :class:`JSONFormatter`.

    Only the URL *path* is logged — the query string is intentionally excluded
    so that any credentials passed as query parameters are never written to the
    logs. Request bodies and ``Authorization`` headers are likewise never read
    or logged.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000.0

        access_logger.info(
            "request handled",
            extra={
                "method": request.method,
                # Only the path — never the query string (may carry credentials).
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 3),
            },
        )

        return response
