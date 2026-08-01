# Directory Structure

A tour of every file in the repo, grouped by directory. See `DESIGN.md` for architecture and
data-model detail, `AI_ASSISTANT_PLAN.md` for the todo-assistant feature plan, and `TRIAGE.md`
for the assistant's triage policy.

> ⚠️ `scratch` at the repo root contains real production secrets in plaintext (a Neon
> `DATABASE_URL` with password, a Google OAuth client secret) and, unlike `.env`, **is not
> gitignored**. Delete it or move it outside the repo — don't `git add -A` while it exists.

## Top level

```
todo_app/
├── README.md            — placeholder ("# todo_app"), effectively unused
├── CLAUDE.md             — instructions for Claude Code: stack, local dev, testing rules
├── DESIGN.md              — the living architecture doc: data model, REST API, auth flow,
│                            deployment pipeline, cost estimate, phased build history
├── DEPLOY.md             — ops runbook: manual migrations, manual deploys, secret rotation
├── AI_ASSISTANT_PLAN.md — the todo-assistant feature plan (Phases A–E), updated as each ships
├── TRIAGE.md             — the assistant's triage policy spec (Eisenhower matrix, writable
│                            fields, guardrails) — TRIAGE.md, app/triage.py, and the eval
│                            graders are three views of the same rules and must stay in sync
├── DIRECTORY_STRUCTURE.md — this file
├── WALKTHROUGH.md        — an earlier "new engineer tour" doc; predates the assistant work,
│                            so treat it as possibly stale next to DESIGN.md
├── scratch                — ⚠️ personal scratch notes containing real secrets, not gitignored
├── .gitignore
├── .claude/settings.local.json — Claude Code's accumulated local permission allowlist
└── .github/workflows/
    ├── backend.yml   — on push to main (paths: backend/**): test → build+push Docker image →
    │                   migrate production DB → deploy to Cloud Run (--set-secrets declares
    │                   all 5 secrets) → smoke test
    └── frontend.yml  — on push to main (paths: frontend/**): build → deploy to Firebase Hosting
```

## `backend/` — FastAPI + SQLAlchemy (async) + Alembic + pytest

```
backend/
├── Dockerfile / .dockerignore   — multi-stage Python 3.12-slim build for Cloud Run
├── .env / .env.example          — local config (DB URL, OAuth creds, JWT secret,
│                                   ANTHROPIC_API_KEY); .env is gitignored
├── requirements.txt              — prod deps (fastapi, sqlalchemy, alembic, authlib, anthropic…)
├── requirements-test.txt         — adds pytest, pytest-asyncio, aiosqlite, pyyaml
├── pytest.ini                    — testpaths=tests only; evals/ is opt-in (costs real money)
├── alembic.ini
├── google-cloud-cli-linux-x86_64.tar.gz  — stray installer artifact, gitignored, deletable
│
├── alembic/
│   ├── env.py, script.py.mako
│   └── versions/
│       ├── 001_initial.py                    — users, todos
│       ├── 002_add_todo_fields.py             — category, dates, estimated_effort
│       ├── 003_add_is_focus.py                — the "current focus" star
│       ├── 004_add_importance_and_locked.py   — assistant's triage fields
│       └── 005_add_conversations_messages_agent_runs.py  — assistant's chat + cost/latency log
│
├── app/
│   ├── main.py         — FastAPI app, CORS, router registration, /api/health
│   ├── config.py        — pydantic-settings Settings (reads .env)
│   ├── database.py      — async engine/session factory, declarative Base
│   ├── models.py        — ORM: User, Todo, Conversation, Message, AgentRun
│   ├── schemas.py        — Pydantic request/response schemas for Todo CRUD
│   ├── auth.py           — Google OAuth login/callback/logout, JWT, session cookie,
│   │                       get_current_user dependency, + /auth/dev-login (local-only shortcut)
│   ├── triage.py         — deterministic triage engine: urgency/quadrant/workload math and the
│   │                       agent's writable-field whitelist — the executable form of TRIAGE.md
│   ├── agent_schemas.py  — the Proposal/ProposalItem contract for assistant-written changes
│   │                       (Phase C — schema exists, no tool uses it yet)
│   ├── routers/
│   │   ├── todos.py   — todo CRUD endpoints
│   │   ├── users.py   — /api/me
│   │   └── chat.py    — GET /api/chat (history), POST /api/chat/messages (SSE stream)
│   └── agent/
│       ├── prompt.py   — the frozen system prompt + cached user-preferences block
│       ├── tools.py    — search_todos / get_todo_details / get_workload_summary
│       └── service.py  — the model↔tool loop: streaming, persistence, agent_runs logging
│
├── scripts/
│   └── seed_local_dev.py  — seeds 25 example tasks for local testing (drawn from eval fixtures)
│
├── evals/                  — behavior tests for the assistant; NOT in the default pytest run
│   ├── README.md
│   ├── fixtures.py         — named DB seeds: mixed_40, overloaded_week, duplicates
│   ├── graders.py          — ~19 deterministic assertion functions
│   ├── runner.py           — scenario loader + executor
│   ├── agent_adapter.py    — the one seam connecting evals to the real agent service
│   ├── conftest.py, test_scenarios.py
│   └── scenarios/*.yaml    — 10 scenario definitions (one per eval case)
│
└── tests/                   — the regular unit/integration suite (pytest default)
    ├── conftest.py
    ├── test_health.py, test_todos.py, test_users.py
    ├── test_triage.py           — unit tests for the deterministic triage/workload math
    ├── test_eval_harness.py     — tests the eval graders themselves, not the scenarios
    ├── test_agent_service.py    — tests the agent loop against a fake Anthropic client
    └── test_dev_login.py
```

## `frontend/` — React + TypeScript + Vite + Tailwind

```
frontend/
├── index.html
├── package.json / package-lock.json
├── vite.config.ts        — dev server; proxies /api and /auth to localhost:8000
├── tsconfig*.json          — TS project config (root/app/node)
├── tailwind.config.js, postcss.config.js
├── firebase.json, .firebaserc — Hosting config: serves dist/, rewrites /api/** and /auth/**
│                                  to Cloud Run, SPA fallback to index.html
│
└── src/
    ├── main.tsx        — React entry point
    ├── App.tsx          — top-level: auth gating, tab/filter state, todo list, chat toggle
    ├── index.css         — Tailwind directives
    ├── vite-env.d.ts      — Vite's ambient TS types
    │
    ├── api/
    │   ├── todos.ts   — Todo types + CRUD fetch wrappers
    │   └── chat.ts     — chat history fetch + SSE-streaming generator
    │
    ├── hooks/
    │   ├── useAuth.ts   — fetches /api/me, exposes user/loading/logout
    │   └── useTodos.ts  — fetches/mutates the todo list, keeps local state in sync
    │
    └── components/
        ├── Header.tsx       — top bar: user name + sign out
        ├── LoginButton.tsx  — "Sign in with Google"
        ├── AddTodoForm.tsx  — the "+ Add task…" trigger
        ├── TodoList.tsx      — renders TodoItem rows
        ├── TodoItem.tsx       — one task: checkbox, badges, focus star, lock toggle, edit/delete
        ├── TodoModal.tsx      — create/edit form (title, category, effort, importance, dates)
        └── ChatPanel.tsx      — the assistant drawer: history, streamed replies, tool-call chips
```

## `scripts/`

```
scripts/dev_up.sh  — one-command local dev instance: Dockerized Postgres, migrate, seed 25
                      tasks, start both servers, one-click /auth/dev-login. Never touches
                      the production Neon database.
```

## The shape worth noticing

`todos.*` (models/schemas/router/frontend) is the original CRUD app; everything under
`app/agent/`, `app/triage.py`, `evals/`, and `ChatPanel`/`chat.ts` is the assistant, built as
an additive layer on top rather than a rewrite — it reads the same `todos` table and reuses
the same auth, but the assistant's write path (`propose_changes`) hasn't shipped yet, which is
why `agent_schemas.py` exists with nothing calling it.
