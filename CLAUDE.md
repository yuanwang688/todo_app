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
See `DIRECTORY_STRUCTURE.md` for a file-by-file tour of the repo.

**Keep `DESIGN.md` in sync with the code.** Any time behaviour changes — new fields, modified API endpoints, auth flow changes, new UI views — update the relevant section of `DESIGN.md` in the same commit.

## Local Development

**Quick start (todo assistant testing):** `scripts/dev_up.sh` brings up a local Postgres
(Docker), migrates it, seeds 25 example tasks, and starts both dev servers — then visit
`http://localhost:5173/auth/dev-login` for a one-click login, no Google OAuth needed. Never
touches the production Neon database. `--fresh` wipes and reseeds; Ctrl+C stops everything
(seed data persists). See the script's header comment for details.

For the manual setup (real OAuth, your own data):

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

## Testing After Changes

After making any change, test it before reporting done:

- **UI / behavior change** — open the app in a browser and verify the feature works end-to-end, including edge cases. Use the browser automation tools available in the session.
- **Refactor (no behavior change)** — run the relevant unit/integration tests to confirm nothing broke: `cd backend && pytest -v` for backend, `cd frontend && npm test` for frontend (once tests exist).

If neither test suite exists yet, say so explicitly rather than claiming success.

## Project Structure

See `DIRECTORY_STRUCTURE.md` for the full, file-by-file tour — keep it in sync the same way
as `DESIGN.md` when files move or new top-level pieces (routers, agent tools, evals) appear.
