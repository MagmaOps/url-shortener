"""Unit tests for URLRepository.

These tests run against a real PostgreSQL test database. Set the
TEST_DATABASE_URL environment variable before running (or DATABASE_URL will
be used as a fallback):

    TEST_DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/url_shortener_test

The ``urls`` table is created at module start via SQLAlchemy metadata and
dropped at module teardown, keeping tests isolated from any other schema.
Each test that inserts rows cleans up after itself.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import URLRecord, metadata, urls_table
from app.repositories.url_repository import (
    DuplicateShortCodeError,
    URLRepository,
)

# ---------------------------------------------------------------------------
# Test database URL
# ---------------------------------------------------------------------------

_TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:password@localhost:5432/url_shortener_test",
    ),
)

# ---------------------------------------------------------------------------
# Module-scoped event loop (required by pytest-asyncio 0.21 for module-scoped
# async fixtures)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def event_loop():
    """Provide a module-scoped event loop.

    pytest-asyncio 0.21 defaults to function scope; we need module scope to
    match the ``db_engine`` fixture.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Module-scoped engine — created once, torn down after all tests in the module
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="module")
async def db_engine():
    """Create the async engine and the *urls* table; drop it after the module."""
    engine = create_async_engine(_TEST_DB_URL, echo=False, pool_pre_ping=True)

    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)

    await engine.dispose()


# ---------------------------------------------------------------------------
# Helper: fresh session factory
# ---------------------------------------------------------------------------


def _session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Tests — create()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_returns_url_record(db_engine):
    """create() inserts a row and returns a fully-populated URLRecord."""
    factory = _session_factory(db_engine)
    async with factory() as session:
        repo = URLRepository(session)
        record = await repo.create("abc12345", "https://example.com/long/path")

    try:
        assert isinstance(record, URLRecord)
        assert record.short_code == "abc12345"
        assert record.original_url == "https://example.com/long/path"
        assert isinstance(record.id, int)
        assert record.id > 0
        assert isinstance(record.created_at, datetime)
        assert record.clicks == 0
    finally:
        async with db_engine.begin() as conn:
            await conn.execute(
                delete(urls_table).where(urls_table.c.short_code == "abc12345")
            )


@pytest.mark.asyncio
async def test_create_persists_row(db_engine):
    """The row created by create() can be read back in a fresh session."""
    factory = _session_factory(db_engine)

    async with factory() as session:
        repo = URLRepository(session)
        created = await repo.create("persist1", "https://persist.example.com")

    try:
        async with factory() as fresh_session:
            fresh_repo = URLRepository(fresh_session)
            fetched = await fresh_repo.get_by_short_code("persist1")

        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.short_code == "persist1"
        assert fetched.original_url == "https://persist.example.com"
        assert fetched.clicks == 0
    finally:
        async with db_engine.begin() as conn:
            await conn.execute(
                delete(urls_table).where(urls_table.c.short_code == "persist1")
            )


@pytest.mark.asyncio
async def test_create_raises_on_duplicate_short_code(db_engine):
    """create() raises DuplicateShortCodeError when short_code already exists."""
    factory = _session_factory(db_engine)

    # Seed the first row directly.
    async with db_engine.begin() as conn:
        await conn.execute(
            insert(urls_table).values(
                short_code="dup00001",
                original_url="https://first.example.com",
            )
        )

    try:
        async with factory() as session:
            repo = URLRepository(session)
            with pytest.raises(DuplicateShortCodeError) as exc_info:
                await repo.create("dup00001", "https://second.example.com")

        assert exc_info.value.short_code == "dup00001"
    finally:
        async with db_engine.begin() as conn:
            await conn.execute(
                delete(urls_table).where(urls_table.c.short_code == "dup00001")
            )


# ---------------------------------------------------------------------------
# Tests — get_by_short_code()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_by_short_code_returns_none_for_missing(db_engine):
    """get_by_short_code() returns None when the code does not exist."""
    factory = _session_factory(db_engine)
    async with factory() as session:
        repo = URLRepository(session)
        result = await repo.get_by_short_code("notfound")

    assert result is None


@pytest.mark.asyncio
async def test_get_by_short_code_returns_record(db_engine):
    """get_by_short_code() returns a matching URLRecord for an existing code."""
    factory = _session_factory(db_engine)

    async with factory() as session:
        repo = URLRepository(session)
        created = await repo.create("gettest1", "https://get.example.com")

    try:
        async with factory() as session:
            repo = URLRepository(session)
            fetched = await repo.get_by_short_code("gettest1")

        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.short_code == "gettest1"
        assert fetched.original_url == "https://get.example.com"
        assert isinstance(fetched.created_at, datetime)
        assert fetched.clicks == 0
    finally:
        async with db_engine.begin() as conn:
            await conn.execute(
                delete(urls_table).where(urls_table.c.short_code == "gettest1")
            )


# ---------------------------------------------------------------------------
# Tests — increment_clicks()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_increment_clicks_increases_count_by_one(db_engine):
    """increment_clicks() atomically increments the click counter by 1."""
    factory = _session_factory(db_engine)

    async with db_engine.begin() as conn:
        await conn.execute(
            insert(urls_table).values(
                short_code="click001",
                original_url="https://click.example.com",
            )
        )

    try:
        async with factory() as session:
            repo = URLRepository(session)
            await repo.increment_clicks("click001")

        async with factory() as session:
            repo = URLRepository(session)
            record = await repo.get_by_short_code("click001")

        assert record is not None
        assert record.clicks == 1
    finally:
        async with db_engine.begin() as conn:
            await conn.execute(
                delete(urls_table).where(urls_table.c.short_code == "click001")
            )


@pytest.mark.asyncio
async def test_increment_clicks_concurrent_atomicity(db_engine):
    """N concurrent increment_clicks() calls result in clicks == N.

    Verifies the atomic UPDATE (clicks = clicks + 1) prevents lost updates
    under concurrent access. A read-modify-write pattern would produce a
    final count less than N.
    """
    factory = _session_factory(db_engine)
    short_code = "concurr1"
    n = 20

    async with db_engine.begin() as conn:
        await conn.execute(
            insert(urls_table).values(
                short_code=short_code,
                original_url="https://concurrent.example.com",
            )
        )

    try:
        async def do_increment() -> None:
            async with factory() as session:
                repo = URLRepository(session)
                await repo.increment_clicks(short_code)

        # Fire N concurrent increments and wait for all to complete.
        await asyncio.gather(*[do_increment() for _ in range(n)])

        # Read the final count.
        async with factory() as session:
            repo = URLRepository(session)
            record = await repo.get_by_short_code(short_code)

        assert record is not None
        assert record.clicks == n, (
            f"Expected {n} clicks after {n} concurrent increments, "
            f"got {record.clicks}"
        )
    finally:
        async with db_engine.begin() as conn:
            await conn.execute(
                delete(urls_table).where(urls_table.c.short_code == short_code)
            )
