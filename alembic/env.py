import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Import metadata so Alembic can compare against the current schema (used
# for autogenerate; harmless when not using autogenerate).
from app.models import metadata

# Alembic Config object — provides access to values in alembic.ini
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set the target metadata for autogenerate support
target_metadata = metadata


def get_url() -> str:
    """Return the database URL for migrations.

    Migrations only need DATABASE_URL. Read it directly from the environment
    rather than through the full application Settings object, so running
    migrations does not require BASE_URL (which is only needed to serve
    requests). This keeps migrations decoupled from application-serving config.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is required to run migrations"
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    In this mode we configure the context with just a URL.  No engine or
    connection is needed.  Calls to context.execute() emit the given string to
    the script output.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations against the async engine."""
    connectable = create_async_engine(get_url())

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using the async engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
