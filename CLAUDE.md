# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack

- **Frontend:** React + TypeScript, Tailwind CSS, Vite
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic
- **Database:** PostgreSQL 16 via Neon (serverless)
- **Auth:** Google OAuth 2.0 (Authlib) + JWT in httpOnly cookie
- **Hosting:** Firebase Hosting (frontend) + GCP Cloud Run (backend)
- **CI/CD:** GitHub Actions

See `DESIGN.md` for full architecture, data model, and API design.
