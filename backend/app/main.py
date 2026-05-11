from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from .config import settings
from .database import AsyncSessionLocal
from .routers import todos
from .routers.todos import TEMP_USER_ID


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Seed the temp user so the todos FK is satisfied in Phase 2.
    # Remove this block in Phase 3 once real auth is in place.
    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            INSERT INTO users (id, google_id, email, name)
            VALUES (:id, 'temp', 'temp@example.com', 'Temp User')
            ON CONFLICT (id) DO NOTHING
        """), {"id": str(TEMP_USER_ID)})
        await db.commit()
    yield


app = FastAPI(title="Todo API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(todos.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
