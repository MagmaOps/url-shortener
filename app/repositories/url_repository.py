"""Repository layer for URL records.

All database operations are isolated here. Callers receive domain-level
exceptions rather than raw SQLAlchemy errors.
"""

from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import URLRecord, urls_table


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class URLRepositoryError(Exception):
    """Base exception for all URLRepository errors."""


class DuplicateShortCodeError(URLRepositoryError):
    """Raised when a short_code already exists in the database."""

    def __init__(self, short_code: str) -> None:
        super().__init__(f"Short code already exists: {short_code!r}")
        self.short_code = short_code


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class URLRepository:
    """Async repository for the *urls* table.

    All methods use SQLAlchemy Core (not the ORM) and are compatible with the
    async engine / session factory set up in ``app.database``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(self, short_code: str, original_url: str) -> URLRecord:
        """Insert a new URL record and return the fully-populated ``URLRecord``.

        Raises:
            DuplicateShortCodeError: if *short_code* already exists (unique
                constraint violation).
            URLRepositoryError: for any other database-level error.
        """
        stmt = (
            insert(urls_table)
            .values(short_code=short_code, original_url=original_url)
            .returning(
                urls_table.c.id,
                urls_table.c.short_code,
                urls_table.c.original_url,
                urls_table.c.created_at,
                urls_table.c.clicks,
            )
        )
        try:
            result = await self._session.execute(stmt)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            # PostgreSQL unique-constraint violations surface as IntegrityError.
            raise DuplicateShortCodeError(short_code) from exc
        except Exception as exc:
            await self._session.rollback()
            raise URLRepositoryError("Failed to create URL record") from exc

        row = result.one()
        return URLRecord(
            id=row.id,
            short_code=row.short_code,
            original_url=row.original_url,
            created_at=row.created_at,
            clicks=row.clicks,
        )

    async def increment_clicks(self, short_code: str) -> None:
        """Atomically increment the click counter for *short_code*.

        Uses a single ``UPDATE … SET clicks = clicks + 1`` statement — no
        read-then-write.

        Raises:
            URLRepositoryError: for any database-level error.
        """
        stmt = (
            update(urls_table)
            .where(urls_table.c.short_code == short_code)
            .values(clicks=urls_table.c.clicks + 1)
        )
        try:
            await self._session.execute(stmt)
            await self._session.commit()
        except Exception as exc:
            await self._session.rollback()
            raise URLRepositoryError(
                f"Failed to increment clicks for short_code {short_code!r}"
            ) from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_short_code(self, short_code: str) -> URLRecord | None:
        """Return the ``URLRecord`` matching *short_code*, or ``None``.

        Raises:
            URLRepositoryError: for any database-level error.
        """
        stmt = select(urls_table).where(urls_table.c.short_code == short_code)
        try:
            result = await self._session.execute(stmt)
        except Exception as exc:
            raise URLRepositoryError(
                f"Failed to look up short_code {short_code!r}"
            ) from exc

        row = result.one_or_none()
        if row is None:
            return None

        return URLRecord(
            id=row.id,
            short_code=row.short_code,
            original_url=row.original_url,
            created_at=row.created_at,
            clicks=row.clicks,
        )
