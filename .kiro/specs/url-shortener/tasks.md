# Implementation Plan: URL Shortener

## Overview

Incremental implementation of a FastAPI + PostgreSQL URL shortener. Tasks follow the layered architecture: project scaffolding → data layer → service logic → HTTP layer → middleware → testing → containerization. Each step is self-contained and wired into the application before moving forward.

---

## Tasks

- [x] 1. Project scaffolding and configuration
  - [x] 1.1 Create directory structure and stub files
    - Create `app/`, `app/middleware/`, `app/routes/`, `app/services/`, `app/repositories/`, `tests/`, `tests/properties/`, `alembic/versions/` directories with empty `__init__.py` files as needed
    - Add `requirements.txt` (or `pyproject.toml`) pinning: `fastapi`, `uvicorn[standard]`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pydantic-settings`, `prometheus-client`, `python-dotenv`; dev deps: `pytest`, `pytest-asyncio`, `httpx`, `hypothesis`
    - Add `.env.example` listing `DATABASE_URL`, `BASE_URL`, `LOG_LEVEL` with example values; add `.env` to `.gitignore`
    - _Requirements: 7.1, 7.3_

  - [x] 1.2 Implement `app/config.py`
    - Define `Settings(BaseSettings)` with fields `database_url: str`, `base_url: str`, `log_level: str = "INFO"` using `SettingsConfigDict(env_file=".env", extra="ignore")`
    - Expose a module-level `get_settings()` cached function
    - Raise a clear startup error when `DATABASE_URL` or `BASE_URL` are missing
    - _Requirements: 7.1, 7.2_

- [x] 2. Database layer — models, schema, and migrations
  - [x] 2.1 Implement `app/database.py`
    - Create async SQLAlchemy engine from `Settings.database_url` using `create_async_engine`
    - Expose `AsyncSessionLocal` session factory and a FastAPI dependency `get_session()` that yields a session and closes it after the request
    - Implement `dispose_engine()` coroutine for use in the shutdown lifecycle hook
    - _Requirements: 6.1, 6.2_

  - [x] 2.2 Implement `app/models.py`
    - Define `metadata` and `urls_table` using `sqlalchemy.Table` with columns: `id` (BigInteger PK autoincrement), `short_code` (String(8) NOT NULL UNIQUE), `original_url` (Text NOT NULL), `created_at` (DateTime timezone=True, server_default `func.now()` NOT NULL), `clicks` (BigInteger NOT NULL server_default "0")
    - Define `URLRecord` dataclass with fields matching the table
    - _Requirements: 6.1_

  - [x] 2.3 Create Alembic migration `alembic/versions/0001_initial_schema.py`
    - Initialize Alembic configuration (`alembic.ini`, `alembic/env.py`) pointing at `Settings.database_url`
    - Write `upgrade()` that issues the `CREATE TABLE urls` DDL matching the schema in Requirement 6.1
    - Write `downgrade()` that drops the `urls` table
    - Do NOT call `Base.metadata.create_all()` anywhere in application code
    - _Requirements: 6.1, 6.2, 6.3_

- [x] 3. Repository layer
  - [x] 3.1 Implement `app/repositories/url_repository.py`
    - Implement `URLRepository.__init__(self, session: AsyncSession)`
    - Implement `async create(short_code, original_url) -> URLRecord` — INSERT and return full row
    - Implement `async get_by_short_code(short_code) -> URLRecord | None` — SELECT by short_code
    - Implement `async increment_clicks(short_code) -> None` — single atomic `UPDATE urls SET clicks = clicks + 1 WHERE short_code = :code`; do NOT read-then-write
    - Raise domain-level exceptions (not raw SQLAlchemy errors) for caller handling
    - _Requirements: 2.2, 6.1_

  - [x] 3.2 Write unit tests for `URLRepository`
    - Test `create` inserts a row and returns a `URLRecord` with all fields populated
    - Test `get_by_short_code` returns `None` for a missing code
    - Test `increment_clicks` increments the counter atomically (issue N concurrent calls, assert final count == N)
    - _Requirements: 2.2, 11.1_

- [x] 4. Service layer
  - [x] 4.1 Implement `app/schemas.py`
    - Define `URLCreateRequest(BaseModel)` with `url: AnyHttpUrl`
    - Define `URLResponse(BaseModel)` with `id`, `short_code`, `url`, `short_url`, `created_at`
    - Define `URLDetailResponse(URLResponse)` adding `clicks: int`
    - _Requirements: 1.1, 3.1_

  - [x] 4.2 Implement `app/services/url_service.py`
    - Implement `URLService.__init__(self, repository: URLRepository, base_url: str)`
    - Implement `generate_short_code() -> str`: use `secrets.choice` over the explicit alphabet `string.ascii_letters + string.digits` to produce exactly 8 characters; never use `token_urlsafe` (which may produce padding or non-alphanumeric characters)
    - Implement `async create_short_url(original_url: str) -> URLRecord`: generate a code, attempt INSERT via repository; on unique-constraint violation retry up to 10 times; raise an internal error after 10 failed attempts
    - _Requirements: 1.2, 1.3_

  - [x] 4.3 Write property test for short code format (Property 1)
    - **Property 1: Short Code Format Invariant**
    - Generate arbitrary calls to `generate_short_code()` via Hypothesis; assert `len(code) == 8` and `re.fullmatch(r'[A-Za-z0-9]{8}', code)` holds for every generated example
    - **Validates: Requirements 1.2**

  - [x] 4.4 Write unit tests for `URLService`
    - Test that `create_short_url` retries on unique-constraint violation and returns a code not in the pre-existing set (validates Property 2)
    - Test that after 10 consecutive collision failures an internal error is raised
    - _Requirements: 1.2, 1.3_

- [x] 5. HTTP routes
  - [x] 5.1 Implement `app/routes/health.py`
    - `GET /health` — returns `{"status": "ok"}` with HTTP 200; no DB call
    - `GET /ready` — attempts a lightweight DB query; returns `{"status": "ready"}` / 200 on success, `{"status": "not_ready"}` / 503 on failure
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 5.2 Implement `app/routes/urls.py`
    - `POST /api/urls` — accepts `URLCreateRequest`, calls `URLService.create_short_url`, returns `URLResponse` with HTTP 201
    - `GET /api/urls/{short_code}` — calls `URLRepository.get_by_short_code`; returns `URLDetailResponse` / 200 if found, `{"detail": "Short URL not found"}` / 404 if not
    - _Requirements: 1.1, 1.4, 1.5, 3.1, 3.2_

  - [x] 5.3 Implement `app/routes/redirect.py`
    - `GET /{short_code}` — calls `URLRepository.get_by_short_code`; if found, calls `URLRepository.increment_clicks` to atomically increments the click counter and then returns HTTP 302 with `Location` header set to `original_url`. If the click counter update fails, the request SHALL fail with an appropriate 5xx response rather than returning a successful redirect without recording the click; if not found returns `{"detail": "Short URL not found"}` / 404
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 5.4 Write integration tests for health and readiness endpoints
    - Test `GET /health` → 200 `{"status": "ok"}`
    - Test `GET /ready` with DB available → 200 `{"status": "ready"}`
    - Test `GET /ready` with DB unavailable → 503 `{"status": "not_ready"}`
    - _Requirements: 4.1, 4.2, 4.3, 11.1_

  - [x] 5.5 Write integration tests for URL creation endpoint
    - Test `POST /api/urls` with valid HTTPS URL → 201, all response fields present, `short_url` equals `BASE_URL + "/" + short_code`
    - Test `POST /api/urls` with `ftp://bad` → 422
    - Test `POST /api/urls` with empty body → 422
    - _Requirements: 1.1, 1.4, 1.5, 9.2, 11.1_

  - [x] 5.6 Write property test for input validation (Property 4)
    - **Property 4: Input Validation Rejects Non-HTTP/HTTPS URLs**
    - Use Hypothesis to generate strings with non-http/https schemes and arbitrary non-URL strings; assert every submission to `POST /api/urls` returns 422
    - **Validates: Requirements 1.4, 1.5**

  - [x] 5.7 Write integration tests for redirect endpoint
    - Test `GET /{short_code}` → 302 with correct `Location` header
    - Test `GET /{short_code}` increments click count by 1 per access (issue N requests, assert `clicks == N`)
    - Test `GET /nonexistent` → 404 `{"detail": "Short URL not found"}`
    - _Requirements: 2.1, 2.2, 2.3, 11.1_

  - [x] 5.8 Write integration tests for URL lookup endpoint
    - Test `GET /api/urls/{short_code}` → 200 with all required fields (`id`, `short_code`, `url`, `short_url`, `created_at`, `clicks`)
    - Test `GET /api/urls/nonexistent` → 404 `{"detail": "Short URL not found"}`
    - _Requirements: 3.1, 3.2, 11.1_

- [x] 6. Checkpoint — core routes working
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Application wiring and `main.py`
  - [x] 7.1 Implement `app/main.py` — app factory and lifecycle
    - Create `FastAPI` application instance, register all routers (`health`, `urls`, `redirect`)
    - Add `lifespan` context manager that initializes application resources on startup and calls `dispose_engine()` on shutdown. Database connectivity SHALL be checked by the `/ready` endpoint rather than being required for application process startup.
    - Register global `Exception` handler that logs the full traceback at ERROR level and returns `{"detail": "Internal server error"}` / 500; increments `url_shortener_errors_total`
    - Wire `get_session` dependency into routes; wire `URLRepository` and `URLService` through FastAPI `Depends`
    - _Requirements: 9.1, 9.2, 10.1_

  - [x] 7.2 Write integration test for global exception handler (Property 10)
    - **Property 10: Safe Error Responses**
    - Use a mock that raises an unexpected exception in the service layer; assert response is 500 with body exactly `{"detail": "Internal server error"}` and no stack trace or SQL text in body
    - **Validates: Requirements 9.1**

- [x] 8. Metrics middleware
  - [x] 8.1 Implement `app/middleware/metrics.py`
    - Subclass `BaseHTTPMiddleware`; define module-level Prometheus metrics: `http_requests_total` (Counter, labels: method, path, status), `http_request_duration_seconds` (Histogram, labels: method, path, status), `url_shortener_urls_created_total` (Counter), `url_shortener_redirects_total` (Counter), `url_shortener_errors_total` (Counter)
    - In `dispatch`: record start time, call `await call_next(request)`, record duration; skip incrementing `http_requests_total` and `http_request_duration_seconds` for paths `/metrics`, `/health`, `/ready`
    - HTTP request metrics SHALL use the matched FastAPI/Starlette route template (for example, /api/urls/{short_code}) rather than the raw request path, so individual short codes do not create separate Prometheus time series.
    - Increment `url_shortener_urls_created_total` on 201 responses from `POST /api/urls`; increment `url_shortener_redirects_total` on 302 responses; increment `url_shortener_errors_total` on 4xx/5xx responses
    - Register middleware in `app/main.py`
    - Add `GET /metrics` route that returns `generate_latest()` with content-type `text/plain; version=0.0.4`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 8.2 Write integration tests for metrics endpoint
    - Test `GET /metrics` response includes all five required metric names
    - Test that requests to `/metrics`, `/health`, `/ready` are excluded from `http_requests_total`
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 11.1_

- [ ] 9. Logging middleware
  - [ ] 9.1 Implement `app/middleware/logging.py`
    - Subclass `BaseHTTPMiddleware`; configure application `logging` to emit structured JSON logs to stdout/stderr. Logging configuration SHALL NOT write application logs to files inside the container; respect `Settings.log_level`
    - In `dispatch`: record start time, call `await call_next(request)`, compute `duration_ms`; emit one structured log entry per request with fields: `timestamp`, `level`, `method`, `path`, `status_code`, `duration_ms`
    - Do NOT log request bodies, `Authorization` headers, query strings containing credentials, or the raw `DATABASE_URL`
    - Register middleware in `app/main.py` (before metrics middleware so logging wraps everything)
    - _Requirements: 8.1, 8.2, 8.3_

  - [ ]* 9.2 Write unit tests for logging middleware (Property 11)
    - **Property 11: Request Log Completeness**
    - Capture log output during test requests; assert every emitted request log entry contains `timestamp`, `level`, `method`, `path`, `status_code`, `duration_ms`
    - Assert no log entry contains `DATABASE_URL` value, passwords, or request body content
    - **Validates: Requirements 8.2, 8.3**

- [ ] 10. Test infrastructure (`tests/conftest.py`)
  - [ ] 10.1 Implement `tests/conftest.py`
    - Create async SQLAlchemy engine pointed at a test database URL (read from `TEST_DATABASE_URL` env var or derived from `DATABASE_URL`)
    - Run Alembic migrations against the test database at session start
    - Provide `async_client` fixture: an `httpx.AsyncClient` wrapping the FastAPI app with `base_url="http://test"`
    - Use a dedicated test PostgreSQL database. Tests MAY clean up data between tests using truncation or transaction isolation, but the implementation SHALL prioritize reliable integration tests over a complex transaction-sharing fixture.
    - _Requirements: 11.2_

- [ ] 11. Checkpoint — all tests passing
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Containerization
  - [ ] 12.1 Write `Dockerfile`
    - Create a `.dockerignore` that excludes development files, virtual environments, tests, Git metadata, caches, `.env`, and other files not required to run the application.
    - Use `python:3.12-slim` as base image
    - Create a non-root user (e.g. `appuser`) and run the application as that user
    - Copy `requirements.txt` and install dependencies before copying application code (layer caching)
    - Copy `app/` and `alembic/` and `alembic.ini`
    - Expose port `8000`
    - Set `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`
    - Do NOT copy `.env` or any file containing secrets into the image
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

  - [ ] 12.2 Write container documentation in `README.md`
    - Document `docker build -t url-shortener:latest .`
    - Document `docker run` with required `-e DATABASE_URL=...` and `-e BASE_URL=...` flags
    - Document how to run Alembic migrations separately from application startup. The application container SHALL NOT automatically run database migrations on every startup.
    - _Requirements: 10.8_

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Checkpoints (tasks 6 and 11) ensure incremental validation before proceeding
- Property tests (Properties 1, 4, 10, 11) use Hypothesis; Properties 2, 3, 5, 6, 7, 8, 9 are covered by conventional integration tests as specified in the design's testing strategy
- The click counter MUST use a single atomic SQL UPDATE (`clicks = clicks + 1`) — never a read-modify-write pattern
- The short code MUST use `secrets.choice` over an explicit `[A-Za-z0-9]` alphabet to guarantee exactly 8 characters with no padding; `token_urlsafe` is explicitly prohibited

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2", "4.1"] },
    { "id": 2, "tasks": ["2.3", "3.1"] },
    { "id": 3, "tasks": ["3.2", "4.2"] },
    { "id": 4, "tasks": ["4.3", "4.4", "5.1", "5.2", "5.3"] },
    { "id": 5, "tasks": ["5.4", "5.5", "5.6", "5.7", "5.8", "7.1"] },
    { "id": 6, "tasks": ["7.2", "8.1"] },
    { "id": 7, "tasks": ["8.2", "9.1"] },
    { "id": 8, "tasks": ["9.2", "10.1"] },
    { "id": 9, "tasks": ["12.1"] },
    { "id": 10, "tasks": ["12.2"] }
  ]
}
```
