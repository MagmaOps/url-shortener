# URL Shortener

A minimal URL shortener API built with FastAPI and PostgreSQL. Clients submit a long URL and receive a short URL; accessing the short URL issues a redirect to the original. The service is configured entirely through environment variables, exposes Prometheus metrics, and is packaged as a stateless, production-oriented Docker container.

## Configuration

All runtime configuration is supplied through environment variables:

| Variable | Required | Description | Example |
| --- | --- | --- | --- |
| `DATABASE_URL` | Yes | PostgreSQL connection string (async driver) | `postgresql+asyncpg://postgres:password@db:5432/url_shortener` |
| `BASE_URL` | Yes | Publicly accessible root URL of the service, no trailing slash | `http://localhost:8000` |
| `LOG_LEVEL` | No | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). Defaults to `INFO`. | `INFO` |

See [`.env.example`](.env.example) for a template. Do not commit a populated `.env` file.

## Docker

The application ships with a `Dockerfile` that uses `python:3.12-slim`, runs as a non-root user, exposes port `8000`, and starts the app with `uvicorn`. The image is stateless and contains no secrets or environment-specific configuration — all configuration is provided at runtime via environment variables.

### Local development database

For local/manual testing you can run PostgreSQL in a container. This keeps your
machine free of a `createdb`/`psql` install and matches the versions used in CI.

```bash
docker run --name url-shortener-postgres \
  -e POSTGRES_USER=url_shortener_dev \
  -e POSTGRES_PASSWORD=url_shortener_dev \
  -e POSTGRES_DB=url_shortener_local \
  -p 5433:5432 \
  -d postgres:14-alpine
```

This maps host port `5433` to the container's `5432`. Use a dedicated
`url_shortener_local` database for manual testing — keep it separate from the
`url_shortener_test` database, whose schema is torn down by the test suite on
every run.

If the container is already running and you only need the extra database:

```bash
docker exec url-shortener-postgres \
  psql -U url_shortener_dev -d postgres \
  -c "CREATE DATABASE url_shortener_local OWNER url_shortener_dev;"
```


### Build the image

```bash
docker build -t url-shortener:latest .
```

### Run the container

Provide the required environment variables at runtime and publish the container port. Use your own values in place of the examples below.

```bash
docker run --rm \
  -e DATABASE_URL="postgresql+asyncpg://url_shortener_dev:url_shortener_dev@host.docker.internal:5433/url_shortener_local" \
  -e BASE_URL="http://localhost:8000" \
  -e LOG_LEVEL="INFO" \
  -p 8000:8000 \
  url-shortener:latest
```

- `-e DATABASE_URL=...` (required) — PostgreSQL connection string. The example values above are placeholders; supply your own credentials and host.
- `-e BASE_URL=...` (required) — the public root URL used to build returned short URLs.
- `-e LOG_LEVEL=...` (optional) — defaults to `INFO` when omitted.
- `-p 8000:8000` — maps the container's exposed port `8000` to the host.

Application logs are written to stdout/stderr, so container runtimes and log aggregators can collect them without extra configuration.

> **Connecting to a database on your host machine:** inside a container, `localhost` refers to the container itself, not your host. If your PostgreSQL runs on the host (e.g. mapped to `localhost:5433`), use `host.docker.internal` as the host in `DATABASE_URL` on Docker Desktop (Windows/macOS):
>
> ```
> DATABASE_URL="postgresql+asyncpg://user:pass@host.docker.internal:5433/url_shortener"
> ```
>
> On plain Linux Docker, add `--add-host=host.docker.internal:host-gateway` to the `docker run` command, or run PostgreSQL in a container on a shared Docker network and use its container name as the host.

### Database migrations

The application container **does not** run database migrations automatically on startup. You must apply migrations separately, before (or independently of) starting the application, so schema changes are explicit and controlled.

Run Alembic migrations against your database using the same image:

```bash
docker run --rm \
  -e DATABASE_URL="postgresql+asyncpg://url_shortener_dev:url_shortener_dev@host.docker.internal:5433/url_shortener_local" \
  url-shortener:latest \
  alembic upgrade head
```

This runs `alembic upgrade head` inside a one-off container and exits. Migrations only require `DATABASE_URL` — `BASE_URL` is not needed to run them. Apply migrations first, then start the application container as shown above. Docker Compose is not required to build or run the service.
