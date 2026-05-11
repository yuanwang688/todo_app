import asyncio
from logging.config import fileConfig
from sqlalchemy import make_url, pool
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context

from app.config import settings
from app.database import Base
import app.models  # noqa: F401 — ensures models are registered on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Build engine the same way database.py does — avoids async_engine_from_config
# re-parsing the URL string and mangling the password.
def _make_migration_engine():
    url = make_url(settings.database_url)
    sslmode = url.query.get("sslmode", "")
    stripped = url.set(query={k: v for k, v in url.query.items() if k != "sslmode"})
    connect_args = {"ssl": "require"} if sslmode == "require" else {}
    return create_async_engine(stripped, poolclass=pool.NullPool, connect_args=connect_args)


def run_migrations_offline() -> None:
    url = make_url(settings.database_url)
    stripped = url.set(query={k: v for k, v in url.query.items() if k != "sslmode"})
    context.configure(
        url=str(stripped),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = _make_migration_engine()
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
