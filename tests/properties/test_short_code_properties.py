"""Property-based tests for short code generation.

Feature: url-shortener, Property 1: Short Code Format Invariant

Validates: Requirements 1.2
"""

from __future__ import annotations

import re

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.services.url_service import URLService


# URLService requires a repository and base_url, but generate_short_code
# does not use either — pass minimal stubs so construction succeeds.
_service = URLService(repository=None, base_url="http://localhost:8000")  # type: ignore[arg-type]


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(st.none())
def test_short_code_format_invariant(_: None) -> None:
    """Property 1: Short Code Format Invariant.

    For any invocation of generate_short_code(), the result is a string of
    exactly 8 characters and every character is ASCII alphanumeric (A-Z, a-z,
    or 0-9).

    Validates: Requirements 1.2
    """
    # Feature: url-shortener, Property 1: Short Code Format Invariant
    code = _service.generate_short_code()

    assert len(code) == 8, f"Expected length 8, got {len(code)!r} for code {code!r}"
    assert re.fullmatch(r"[A-Za-z0-9]{8}", code) is not None, (
        f"Code {code!r} contains characters outside [A-Za-z0-9]"
    )
