"""Shared pytest fixtures for the URL shortener test suite.

This module provides the integration-test infrastructure:

- A session-scoped async SQLAlchemy engine pointed at a dedicated test
  database (``TEST_DATABASE_URL`` env var, falling back to ``DATABASE_URL``,
  then a sensible local default).
- Alembic migrations run against that test database once at session start so
  the schema matches production exactly (we deliberately do NOT use
  ``metadata.create_all`` here — the migrations are the source of truth).
- An ``async_client`` fixture: an ``httpx.AsyncClient`` wrapping the real
  FastAPI application (``app.main.app``) with ``base_url="http://test"``.

Isolation strategy: rather than a complex transaction-sharing fixture, each
test that uses ``async_client`` runs against the shared migrated database and
the ``urls`` table is truncated before each test. This keeps the integration
tests simple and reliable, which the spec explicitly prioritises over a
clever transaction-rollback fixture.

Requirements: 11.2
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import get_session
from app.main import app
from app.models import urls_table

# ---------------------------------------------------------------------------
# Test database URL resolution
#
# Prefer an explicit TEST_DATABASE_URL so integration tests never touch a
# developer's real database. Fall back to DATABASE_URL, then to a conventional
# local default matching the one used by the repository unit tests.
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:password@localhost:5432/url_shortener_test",
    ),
)

# Repository root (one level up from the tests/ directory) — used to locate
# alembic.ini regardless of the current working directory.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ALEMBIC_INI = os.path.join(_PROJECT_ROOT, "alembic.ini")


def _make_alembic_config() -> Config:
    """Build an Alembic Config pointing at the project's migration scripts.

    The database URL is supplied through the ``DATABASE_URL`` environment
    variable (see below), which ``alembic/env.py`` reads via ``get_settings()``.
    """
    cfg = Config(_ALEMBIC_INI)
    cfg.set_main_option("script_location", os.path.join(_PROJECT_ROOT, "alembic"))
    return cfg


# ---------------------------------------------------------------------------
# Session-scoped schema setup — run Alembic migrations against the test DB
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _apply_migrations():
    """Run Alembic migrations against the test database at session start.

    This fixture is intentionally NOT autouse: only tests that use a real
    database (via the ``async_client`` fixture, which depends on it) trigger
    the migration. Mock-based unit tests never touch the database and must not
    require a live PostgreSQL instance or the DATABASE_URL/BASE_URL env vars.

    ``alembic/env.py`` resolves the database URL from application settings,
    which read ``DATABASE_URL``. We point that at the test database for the
    duration of migration so the migrations run against the dedicated test DB
    and not a real one. The original environment is restored afterwards.
    """
    original_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

    # get_settings() is lru_cached; clear it so the overridden DATABASE_URL is
    # picked up when alembic/env.py imports application settings.
    from app.config import get_settings

    get_settings.cache_clear()

    try:
        config = _make_alembic_config()
        command.upgrade(config, "head")
        yield
        # Roll the schema back so a re-run starts from a clean slate.
        command.downgrade(config, "base")
    finally:
        if original_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_database_url
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Session-scoped async engine + session factory against the test database
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create the async engine for the test database; dispose it at the end."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def test_session_factory(
    test_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Session factory bound to the test engine."""
    return async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )


# ---------------------------------------------------------------------------
# Per-test data cleanup — truncate the urls table before each test
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def _clean_tables(
    test_engine: AsyncEngine,
) -> AsyncGenerator[None, None]:
    """Truncate the ``urls`` table before each test for isolation.

    Requested explicitly by ``async_client`` (not autouse), so only
    database-backed integration tests pay the truncation cost.

    TRUNCATE ... RESTART IDENTITY resets the primary-key sequence too, so each
    test sees a predictable starting state.
    """
    async with test_engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE TABLE {urls_table.name} RESTART IDENTITY CASCADE")
        )
    yield


# ---------------------------------------------------------------------------
# async_client — httpx.AsyncClient wrapping the real FastAPI app
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def async_client(
    _apply_migrations: None,
    _clean_tables: None,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncClient, None]:
    """Yield an ``httpx.AsyncClient`` bound to the FastAPI app.

    Depends on ``_apply_migrations`` (schema is migrated once per session) and
    ``_clean_tables`` (the urls table is truncated before this test) so every
    integration test starts from a known, migrated, empty database.

    The ``get_session`` dependency is overridden so request handlers use the
    test database's session factory. The client uses ``base_url="http://test"``
    per the ASGI transport convention.
    """

    async def _get_test_session() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_session] = _get_test_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)
