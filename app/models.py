from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    func,
)

metadata = MetaData()

urls_table = Table(
    "urls",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("short_code", String(8), nullable=False, unique=True),
    Column("original_url", Text, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
    Column("clicks", BigInteger, nullable=False, server_default="0"),
)


@dataclass
class URLRecord:
    id: int
    short_code: str
    original_url: str
    created_at: datetime
    clicks: int
