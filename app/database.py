from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

# Module-level engine; created once at import time so it can be reused
# across all requests within the same process.
_engine = None
_AsyncSessionLocal = None


def _get_engine():
    global _engine, _AsyncSessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
        )
        _AsyncSessionLocal = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _engine


def get_async_session_local() -> async_sessionmaker[AsyncSession]:
    _get_engine()
    return _AsyncSessionLocal


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an AsyncSession and closes it after the request."""
    session_factory = get_async_session_local()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def dispose_engine() -> None:
    """Dispose of the async engine's connection pool.

    Call this in the application shutdown lifecycle hook to cleanly release
    all database connections before the process exits.
    """
    global _engine, _AsyncSessionLocal
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _AsyncSessionLocal = None
