from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel


class URLCreateRequest(BaseModel):
    """Request body for POST /api/urls."""

    url: AnyHttpUrl  # Pydantic V2 AnyHttpUrl enforces http/https scheme


class URLResponse(BaseModel):
    """Response body for successful URL creation (201)."""

    id: int
    short_code: str
    url: str
    short_url: str
    created_at: datetime


class URLDetailResponse(URLResponse):
    """Response body for URL lookup (200), extends URLResponse with click count."""

    clicks: int
