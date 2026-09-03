"""Unit tests for URLService.

These tests use mocked repositories — no database required.

Covered scenarios:
- Success on first attempt
- Retry on DuplicateShortCodeError (validates Property 2 — returned code is
  not in the pre-collision set)
- ShortCodeGenerationError raised after all 10 attempts fail

Requirements: 1.2, 1.3
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import URLRecord
from app.repositories.url_repository import DuplicateShortCodeError
from app.services.url_service import ShortCodeGenerationError, URLService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_URL = "https://short.example.com"


def _make_record(short_code: str) -> URLRecord:
    """Return a minimal URLRecord with the given short_code."""
    return URLRecord(
        id=1,
        short_code=short_code,
        original_url="https://original.example.com/very/long/path",
        created_at=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
        clicks=0,
    )


def _make_service(mock_repo: AsyncMock) -> URLService:
    return URLService(repository=mock_repo, base_url=_BASE_URL)


# ---------------------------------------------------------------------------
# Test: success on first attempt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_short_url_success_on_first_attempt():
    """When create() succeeds immediately, the returned record is passed through
    and create() is called exactly once."""
    mock_repo = MagicMock()
    expected_code = "AbCd1234"
    expected_record = _make_record(expected_code)

    mock_repo.create = AsyncMock(return_value=expected_record)

    service = _make_service(mock_repo)
    result = await service.create_short_url("https://original.example.com/very/long/path")

    assert result is expected_record
    assert result.short_code == expected_code
    mock_repo.create.assert_called_once()


# ---------------------------------------------------------------------------
# Test: retry on collision — validates Property 2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_short_url_retries_on_collision_and_returns_unique_code():
    """When create() raises DuplicateShortCodeError for the first N attempts
    (N < 10), the service retries and eventually returns a record whose
    short_code is not in the pre-collision set.

    This validates Property 2: the returned short code is not a member of
    any pre-existing set (here represented by the codes that triggered
    collisions).
    Validates: Requirements 1.3
    """
    collision_count = 5  # first 5 calls fail, 6th succeeds
    mock_repo = MagicMock()

    # Track which short codes were passed to create() during collision attempts.
    colliding_codes: list[str] = []
    call_count = 0

    async def _create_side_effect(short_code: str, original_url: str) -> URLRecord:
        nonlocal call_count
        call_count += 1
        if call_count <= collision_count:
            colliding_codes.append(short_code)
            raise DuplicateShortCodeError(short_code)
        # On the (collision_count + 1)-th call, succeed.
        return _make_record(short_code)

    mock_repo.create = AsyncMock(side_effect=_create_side_effect)

    service = _make_service(mock_repo)
    result = await service.create_short_url("https://original.example.com/")

    # The service should have called create exactly collision_count + 1 times.
    assert mock_repo.create.call_count == collision_count + 1

    # The returned short_code must NOT be in the set that triggered collisions
    # (validates Property 2 — uniqueness after retry).
    assert result.short_code not in colliding_codes


@pytest.mark.asyncio
async def test_create_short_url_retries_single_collision():
    """A single collision triggers exactly one retry, returning on the second call."""
    mock_repo = MagicMock()
    success_code = "XyZ98765"
    success_record = _make_record(success_code)

    call_count = 0

    async def _create_side_effect(short_code: str, original_url: str) -> URLRecord:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise DuplicateShortCodeError(short_code)
        return success_record

    mock_repo.create = AsyncMock(side_effect=_create_side_effect)

    service = _make_service(mock_repo)
    result = await service.create_short_url("https://example.com/path")

    assert mock_repo.create.call_count == 2
    assert result is success_record


# ---------------------------------------------------------------------------
# Test: all 10 attempts fail → ShortCodeGenerationError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_short_url_raises_after_10_consecutive_failures():
    """When all 10 create() attempts raise DuplicateShortCodeError,
    create_short_url() raises ShortCodeGenerationError.

    Validates: Requirements 1.3
    """
    mock_repo = MagicMock()

    async def _always_collide(short_code: str, original_url: str) -> URLRecord:
        raise DuplicateShortCodeError(short_code)

    mock_repo.create = AsyncMock(side_effect=_always_collide)

    service = _make_service(mock_repo)

    with pytest.raises(ShortCodeGenerationError):
        await service.create_short_url("https://example.com/very/long/path")

    # Exactly 10 attempts should have been made (_MAX_RETRIES = 10).
    assert mock_repo.create.call_count == 10


@pytest.mark.asyncio
async def test_create_short_url_does_not_raise_on_ninth_failure():
    """Nine consecutive failures followed by a success should NOT raise;
    this acts as a boundary check just below the limit."""
    mock_repo = MagicMock()
    call_count = 0

    async def _create_side_effect(short_code: str, original_url: str) -> URLRecord:
        nonlocal call_count
        call_count += 1
        if call_count < 10:
            raise DuplicateShortCodeError(short_code)
        return _make_record(short_code)

    mock_repo.create = AsyncMock(side_effect=_create_side_effect)

    service = _make_service(mock_repo)
    result = await service.create_short_url("https://example.com/path")

    assert mock_repo.create.call_count == 10
    assert isinstance(result, URLRecord)
