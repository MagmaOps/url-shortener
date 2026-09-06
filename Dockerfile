# syntax=docker/dockerfile:1

# ---- Base image ----
FROM python:3.12-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ---- Create a non-root user ----
RUN groupadd --system appuser \
    && useradd --system --gid appuser --create-home --home-dir /home/appuser appuser

WORKDIR /app

# ---- Install dependencies first (better layer caching) ----
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---- Copy application code ----
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

# Ensure the non-root user owns the application files
RUN chown -R appuser:appuser /app

# ---- Run as the non-root user ----
USER appuser

# ---- Network ----
EXPOSE 8000

# ---- Start the application ----
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
