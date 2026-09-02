"""initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-15 00:00:00.000000

"""
from __future__ import annotations

from typing import Optional, Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Optional[str] = None
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    """Create the urls table."""
    op.create_table(
        "urls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("short_code", sa.String(length=8), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "clicks",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("short_code", name="uq_urls_short_code"),
    )


def downgrade() -> None:
    """Drop the urls table."""
    op.drop_table("urls")
