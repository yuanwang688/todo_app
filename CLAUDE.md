# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack

- **Frontend:** React + TypeScript, Tailwind CSS, Vite — `frontend/`
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic — `backend/`
- **Database:** PostgreSQL 16 via Neon (serverless)
- **Auth:** Google OAuth 2.0 (Authlib) + JWT in httpOnly cookie
- **Hosting:** Firebase Hosting (frontend) + GCP Cloud Run (backend)
- **CI/CD:** GitHub Actions

See `DESIGN.md` for full architecture, data model, API design, and phased implementation plan.

## Local Development

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in values
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev            # Vite dev server on :5173
```

The Vite dev server proxies `/api/*` and `/auth/*` to `http://localhost:8000`, so both services must be running for the full app to work.

### Run a single backend test (once tests exist)

```bash
cd backend
pytest tests/test_todos.py::test_create_todo -v
```

## Project Structure

```
backend/
  app/
    main.py        # FastAPI app entry point, router registration, CORS
    auth.py        # OAuth flow, JWT issue/verify, session cookie (Phase 3)
    models.py      # SQLAlchemy ORM models (Phase 2)
    schemas.py     # Pydantic request/response schemas (Phase 2)
    database.py    # Async engine + session factory (Phase 2)
    routers/
      todos.py     # CRUD endpoints (Phase 2)
      users.py     # /api/me (Phase 3)
  alembic/         # DB migrations (Phase 2)
  Dockerfile
  requirements.txt

frontend/
  src/
    api/           # Typed fetch wrappers per endpoint (Phase 2)
    components/    # TodoItem, TodoList, AddTodoForm, etc. (Phase 2)
    hooks/         # useAuth, useTodos (Phase 2+)
    App.tsx
    main.tsx
  vite.config.ts   # Proxy config
  tailwind.config.js
```
