"""Alembic environment for the async PostgreSQL/Neon connection."""
from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.db import make_database_url
from app.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    settings = Settings.from_env()
    url, _ = make_database_url(settings.database_url)
    context.configure(
        url=url.render_as_string(hide_password=True),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    settings = Settings.from_env()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required to run migrations")
    url, connect_args = make_database_url(settings.database_url)
    engine = create_async_engine(url, pool_pre_ping=True, connect_args=connect_args)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
