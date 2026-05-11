from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from .config import settings


def _make_engine():
    url = make_url(settings.database_url)
    if url.drivername.startswith("sqlite"):
        return create_async_engine(url, echo=False)
    # asyncpg uses connect_args ssl= instead of the sslmode URL param
    sslmode = url.query.get("sslmode", "")
    stripped = url.set(query={k: v for k, v in url.query.items() if k != "sslmode"})
    connect_args = {"ssl": "require"} if sslmode == "require" else {}
    return create_async_engine(stripped, connect_args=connect_args, echo=False)


engine = _make_engine()
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
