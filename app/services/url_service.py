"""Service layer for URL shortening operations.

Contains short code generation and URL creation logic, including
retry handling for short code collisions.
"""

from __future__ import annotations

import logging
import secrets
import string

from app.models import URLRecord
from app.repositories.url_repository import DuplicateShortCodeError, URLRepository

logger = logging.getLogger(__name__)

# Explicit alphanumeric alphabet: A-Z, a-z, 0-9 — no padding, no special chars.
_ALPHABET = string.ascii_letters + string.digits  # 62 characters

_SHORT_CODE_LENGTH = 8
_MAX_RETRIES = 10


class URLServiceError(Exception):
    """Base exception for URLService errors."""


class ShortCodeGenerationError(URLServiceError):
    """Raised when a unique short code cannot be generated after max retries."""

    def __init__(self) -> None:
        super().__init__(
            f"Failed to generate a unique short code after {_MAX_RETRIES} attempts"
        )


class URLService:
    """Business logic for creating and managing shortened URLs."""

    def __init__(self, repository: URLRepository, base_url: str) -> None:
        self._repository = repository
        # Strip trailing slash so short_url construction is consistent.
        self._base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Short code generation
    # ------------------------------------------------------------------

    def generate_short_code(self) -> str:
        """Return a cryptographically random 8-character alphanumeric string.

        Uses ``secrets.choice`` over the explicit alphabet
        ``string.ascii_letters + string.digits`` (A-Z, a-z, 0-9).
        ``token_urlsafe`` is intentionally avoided because it may produce
        Base64 padding characters (``=``, ``+``, ``/``) that are not
        URL-safe alphanumeric.
        """
        return "".join(secrets.choice(_ALPHABET) for _ in range(_SHORT_CODE_LENGTH))

    # ------------------------------------------------------------------
    # URL creation
    # ------------------------------------------------------------------

    async def create_short_url(self, original_url: str) -> URLRecord:
        """Generate a unique short code, persist the URL, and return the record.

        Retries up to ``_MAX_RETRIES`` times on short code collisions.

        Args:
            original_url: The full HTTP/HTTPS URL to shorten.

        Returns:
            A ``URLRecord`` containing the persisted row data.

        Raises:
            ShortCodeGenerationError: if a unique code cannot be found after
                ``_MAX_RETRIES`` attempts (astronomically unlikely in practice).
            URLServiceError: for any other unexpected failure.
        """
        for attempt in range(1, _MAX_RETRIES + 1):
            short_code = self.generate_short_code()
            try:
                record = await self._repository.create(
                    short_code=short_code,
                    original_url=original_url,
                )
                logger.debug(
                    "Created short URL",
                    extra={
                        "short_code": short_code,
                        "original_url": original_url,
                        "attempt": attempt,
                    },
                )
                return record
            except DuplicateShortCodeError:
                logger.warning(
                    "Short code collision on attempt %d/%d: %r",
                    attempt,
                    _MAX_RETRIES,
                    short_code,
                )
                # Continue to the next attempt with a freshly generated code.
                continue

        raise ShortCodeGenerationError()
