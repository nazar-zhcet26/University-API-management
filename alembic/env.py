"""
alembic/env.py
--------------
Alembic environment configuration.

This file tells Alembic:
1. How to connect to the database (reads from our config, not alembic.ini)
2. Which models to look at when autogenerating migrations
3. How to run migrations (async mode for asyncpg)

The key thing here: we import our Base and all models so Alembic can
compare the current model definitions against the database state.
If you add a new model and don't import it here, Alembic won't see it.
"""

import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
import os
import sys

# Add project root to path so we can import our app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import Base
# Import ALL models here — Alembic needs to see them to detect changes
from app.models.models import (
    User, Program, Student, Faculty, Course, Enrollment, Book, Borrowing
)
from app.models.api_key import ApiKey
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# This is the metadata Alembic uses for autogenerate
target_metadata = Base.metadata


def get_url():
    """
    Read database URL from environment variable.
    Falls back to alembic.ini value for local dev without .env file.
    Never hardcode credentials.
    """
    return os.getenv(
        "DATABASE_URL",
        config.get_main_option("sqlalchemy.url")
    )
    # Alembic's sync runner needs postgresql:// not postgresql+asyncpg://


def run_migrations_offline() -> None:
    """
    Run migrations without a live database connection.
    Useful for generating SQL scripts to review before applying.
    
    Usage: alembic upgrade head --sql > migration.sql
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,        # detect column type changes
        compare_server_default=True,  # detect default value changes
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Run migrations using async engine — required for asyncpg.
    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # no pooling for migrations
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
