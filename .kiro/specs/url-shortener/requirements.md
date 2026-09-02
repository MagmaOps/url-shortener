# Requirements Document

## Introduction

A minimal URL shortener API built with FastAPI and PostgreSQL. Users submit a long URL and receive a short URL. When the short URL is accessed, the application redirects to the original URL. The application is containerized with Docker, exposes Prometheus metrics, and is configured entirely through environment variables. V1 prioritizes simplicity, clean code, and observability groundwork for future Kubernetes deployment.

## Glossary

- **URL Shortener**: The application service that creates and resolves short URLs
- **Short Code**: A 6–8 character, URL-safe, cryptographically random string that uniquely identifies a shortened URL
- **Short URL**: The full URL composed of BASE_URL + "/" + Short Code (e.g. `http://localhost:8000/aB82xK`)
- **Original URL**: The long URL submitted by the client to be shortened
- **Click**: A single successful redirect event triggered by accessing a Short Code
- **BASE_URL**: The publicly accessible root URL of the URL Shortener, provided via environment variable
- **DATABASE_URL**: The PostgreSQL connection string, provided via environment variable
- **Alembic**: The database migration tool used to manage schema changes
- **Prometheus**: An open-source monitoring system; the URL Shortener exposes metrics in Prometheus exposition format
- **Health Endpoint**: An endpoint that confirms the application process is running
- **Readiness Endpoint**: An endpoint that confirms the application can serve traffic, including database connectivity

---

## Requirements

### Requirement 1 — URL Creation

**User Story:** As an API client, I want to submit a long URL and receive a unique short URL, so that I can share a compact link that redirects to the original.

#### Acceptance Criteria

1. WHEN a client sends a POST request to `/api/urls` with a valid HTTP or HTTPS URL in the request body, THE URL Shortener SHALL return HTTP 201 with a JSON response containing `id`, `short_code`, `url`, `short_url`, and `created_at`.
2. WHEN the URL Shortener generates a Short Code, THE URL Shortener SHALL produce a cryptographically random, URL-safe string of 6 to 8 characters.
3. WHEN a generated Short Code already exists in the database, THE URL Shortener SHALL generate a new Short Code and retry until a unique code is found.
4. WHEN a client submits a URL that does not use the HTTP or HTTPS scheme (e.g. `ftp://`, `javascript:`), THE URL Shortener SHALL return HTTP 422 with a JSON error body.
5. WHEN a client sends a POST request to `/api/urls` with a malformed or missing URL field, THE URL Shortener SHALL return HTTP 422 with a JSON error body.

---

### Requirement 2 — URL Redirect

**User Story:** As a user following a short link, I want the short URL to redirect me to the original URL, so that I reach the intended destination transparently.

#### Acceptance Criteria

1. WHEN a client sends a GET request to `/{short_code}` and the Short Code exists in the database, THE URL Shortener SHALL return HTTP 302 with a `Location` header set to the Original URL.
2. WHEN a client sends a GET request to `/{short_code}` and the Short Code exists in the database, THE URL Shortener SHALL increment the click counter for that URL record by 1.
3. WHEN a client sends a GET request to `/{short_code}` and the Short Code does not exist in the database, THE URL Shortener SHALL return HTTP 404 with the JSON body `{"detail": "Short URL not found"}`.

---

### Requirement 3 — URL Lookup

**User Story:** As a developer, I want to retrieve metadata about a shortened URL by its short code, so that I can inspect creation details and click counts during development and testing.

#### Acceptance Criteria

1. WHEN a client sends a GET request to `/api/urls/{short_code}` and the Short Code exists, THE URL Shortener SHALL return HTTP 200 with a JSON response containing `id`, `short_code`, `url`, `short_url`, `created_at`, and `clicks`.
2. WHEN a client sends a GET request to `/api/urls/{short_code}` and the Short Code does not exist, THE URL Shortener SHALL return HTTP 404 with the JSON body `{"detail": "Short URL not found"}`.

---

### Requirement 4 — Health and Readiness

**User Story:** As an operator, I want HTTP health and readiness endpoints, so that infrastructure tooling can determine whether the application is alive and ready to serve traffic.

#### Acceptance Criteria

1. WHEN a client sends a GET request to `/health`, THE URL Shortener SHALL return HTTP 200 with the JSON body `{"status": "ok"}` without requiring a database connection.
2. WHEN a client sends a GET request to `/ready` and the PostgreSQL database is reachable, THE URL Shortener SHALL return HTTP 200 with the JSON body `{"status": "ready"}`.
3. WHEN a client sends a GET request to `/ready` and the PostgreSQL database is unreachable, THE URL Shortener SHALL return HTTP 503 with the JSON body `{"status": "not_ready"}`.

---

### Requirement 5 — Metrics

**User Story:** As an operator, I want Prometheus-compatible metrics exposed at `/metrics`, so that I can monitor application behavior and track key operational signals.

#### Acceptance Criteria

1. WHEN a client sends a GET request to `/metrics`, THE URL Shortener SHALL return a response in the Prometheus text exposition format using the `prometheus-client` library.
2. THE URL Shortener SHALL expose the counters `http_requests_total`, `url_shortener_urls_created_total`, `url_shortener_redirects_total`, and `url_shortener_errors_total`.
3. THE URL Shortener SHALL expose the histogram `http_request_duration_seconds`.
4. WHILE recording HTTP metrics, THE URL Shortener SHALL include only the labels `method`, `path`, and `status`, and SHALL NOT include full URLs, short codes, IP addresses, or other high-cardinality values as label values.
5. WHEN recording HTTP metrics, THE URL Shortener SHALL exclude requests to `/metrics`, `/health` and `/ready` from `http_requests_total` and `http_request_duration_seconds` to avoid self-referential metric pollution.

---

### Requirement 6 — Database and Migrations

**User Story:** As a developer, I want the database schema managed through Alembic migrations, so that schema changes are versioned, repeatable, and safe across environments.

#### Acceptance Criteria

1. THE URL Shortener SHALL use a PostgreSQL `urls` table with columns: `id` (BIGSERIAL PRIMARY KEY), `short_code` (VARCHAR(16) NOT NULL UNIQUE), `original_url` (TEXT NOT NULL), `created_at` (TIMESTAMPTZ NOT NULL DEFAULT NOW()), and `clicks` (BIGINT NOT NULL DEFAULT 0).
2. THE URL Shortener SHALL manage all schema changes through Alembic migrations and SHALL NOT use SQLAlchemy `create_all()` in production code paths.
3. WHEN the URL Shortener is started, THE URL Shortener SHALL NOT automatically apply database migrations without an explicit migration command.

---

### Requirement 7 — Configuration

**User Story:** As an operator, I want all environment-specific configuration supplied through environment variables, so that the same container image runs correctly in any environment without code changes.

#### Acceptance Criteria

1. THE URL Shortener SHALL read `DATABASE_URL`, `BASE_URL`, and `LOG_LEVEL` from environment variables at startup.
2. THE URL Shortener SHALL NOT contain hardcoded database credentials, hostnames, database names, or public base URLs in source code.
3. THE URL Shortener SHALL provide a `.env.example` file listing all required environment variables with example values, and SHALL NOT commit a populated `.env` file to version control.

---

### Requirement 8 — Logging

**User Story:** As an operator, I want structured application logs emitted to stdout, so that container runtimes and log aggregators can collect them without additional configuration.

#### Acceptance Criteria

1. THE URL Shortener SHALL emit all application logs to stdout or stderr using Python's standard `logging` module.
2. WHEN processing any HTTP request, THE URL Shortener SHALL emit a log entry containing at minimum: timestamp, level, HTTP method, path, response status code, and request duration.
3. THE URL Shortener SHALL NOT log database passwords, connection strings containing passwords, or complete request bodies.

---

### Requirement 9 — Error Handling

**User Story:** As an API client, I want well-formed error responses with appropriate HTTP status codes, so that I can handle failures programmatically without receiving internal implementation details.

#### Acceptance Criteria

1. WHEN an unhandled server-side error occurs, THE URL Shortener SHALL return HTTP 500 with the JSON body `{"detail": "Internal server error"}` and SHALL NOT include Python stack traces or database error details in the response body.
2. THE URL Shortener SHALL use HTTP 201 for successful creation, 302 for redirects, 404 for missing resources, 422 for validation failures, 500 for unexpected server errors, and 503 for service unavailability.

---

### Requirement 10 — Containerization

**User Story:** As a developer, I want the application packaged in a production-oriented Docker container so that it can be deployed and operated in Kubernetes.

#### Acceptance Criteria

1. THE URL Shortener SHALL provide a `Dockerfile` that:
   * uses a small production-appropriate base image;
   * runs the application as a non-root user;
   * exposes port `8000`;
   * starts the application with:
     `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
2. THE URL Shortener SHALL be buildable as a Docker image using:
   ```bash
   docker build -t url-shortener:latest .
   ```
3. WHEN running inside Docker, THE URL Shortener SHALL accept all runtime configuration through environment variables.
4. WHEN running inside Docker, THE URL Shortener SHALL write application logs to stdout or stderr and SHALL NOT require log files inside the container.
5. THE Docker image SHALL NOT contain application secrets, database credentials, or environment-specific configuration.
6. THE container SHALL be stateless. Application data SHALL NOT be stored inside the container filesystem.
7. THE container SHALL start successfully when provided with a valid `DATABASE_URL` and `BASE_URL`.
8. THE URL Shortener SHALL provide documentation explaining how to build and run the container.
9. Docker Compose SHALL NOT be required for V1.

---

### Requirement 11 — Testing

**User Story:** As a developer, I want an automated test suite covering core API behavior, so that I can verify correctness and catch regressions safely.

#### Acceptance Criteria

1. THE URL Shortener SHALL include pytest-based tests covering: `/health` returning 200, `/ready` returning 200 when the database is available, successful URL creation, Short Code format validation, duplicate Short Code handling, invalid URL rejection, redirect returning 302 with correct `Location` header, click count incrementing on redirect, and nonexistent Short Code returning 404.
2. WHEN tests run, THE URL Shortener test suite SHALL use an isolated test database or equivalent setup so tests do not affect production or development data.
