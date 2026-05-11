from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from . import auth
from .routers import todos, users

app = FastAPI(title="Todo API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(todos.router)
app.include_router(users.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
