import os

# Must be set before any app imports so pydantic-settings picks them up.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("JWT_SECRET", "test-secret-key-at-least-32-bytes!!")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("BACKEND_URL", "http://localhost:8000")

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import User

# Intentionally standalone rather than importing from tests/conftest.py: the eval
# harness needs a fresh, unauthenticated DB per scenario and nothing else, and
# keeping the two independent means a change here can't break the unit tests.
_EVAL_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def eval_engine():
    engine = create_async_engine(
        _EVAL_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def eval_db(eval_engine):
    async with async_sessionmaker(eval_engine, expire_on_commit=False)() as session:
        yield session


@pytest_asyncio.fixture
async def eval_user(eval_db):
    u = User(google_id="google-eval-001", email="eval@example.com", name="Eval User")
    eval_db.add(u)
    await eval_db.commit()
    await eval_db.refresh(u)
    return u
