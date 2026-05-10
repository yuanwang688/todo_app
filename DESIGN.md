# Todo App — Requirements & Design Document

## 1. Goals

Build a web-based todo list application with:
- Full CRUD operations on todo items per authenticated user
- Google OAuth login (no separate username/password)
- Cloud hosting on GCP, accessible via browser
- Simple, responsive UI

---

## 2. Functional Requirements

### Authentication
- Users log in exclusively via Google OAuth 2.0 (Gmail credentials)
- Sessions persist across browser refreshes (JWT cookie)
- Users can log out

### Todo Items
- Create a todo item with a title and optional description
- Edit an existing todo item's title or description
- Mark a todo item as complete / incomplete (checkbox)
- Delete a todo item
- View all items, filterable by status (all / active / completed)
- Items are scoped to the authenticated user — no cross-user visibility

### General
- All state persists in a backend database (not localStorage)
- The app works on desktop and mobile browsers

---

## 3. Non-Functional Requirements

| Concern | Requirement |
|---|---|
| Availability | 99.5%+ uptime (acceptable for personal/small-team tool) |
| Latency | API responses < 300ms p95 under light load |
| Security | HTTPS only; OAuth tokens never exposed to client |
| Scalability | Designed for low traffic (<1,000 DAU); horizontal scale if needed |
| Cost | Minimize idle cost; scale-to-zero wherever possible |
| Maintainability | Small codebase, minimal dependencies |

---

## 4. Architecture

```
Browser
  └─► Firebase Hosting (static React build, CDN-delivered)
        └─► Cloud Run (FastAPI, containerized, scale-to-zero)
              ├─► Neon (serverless PostgreSQL, connection pooling via Neon proxy)
              └─► Google OAuth 2.0 (Authlib, server-side token exchange)
```

**Firebase Hosting** serves the compiled React bundle over a global CDN and rewrites `/api/*` requests to the Cloud Run service URL — the browser always talks to a single origin, avoiding CORS complexity.

**Cloud Run** hosts the FastAPI application in a Docker container. It scales to zero when idle (zero cost) and scales out under load. Managed HTTPS and custom domain mapping are handled by GCP.

**Neon** provides serverless PostgreSQL with a connection pooler (PgBouncer) built in, which is important for Cloud Run's ephemeral execution model where new container instances cannot maintain persistent connection pools. The Neon free tier covers this workload at no cost.

**Google OAuth 2.0** is handled entirely server-side: the browser never sees the client secret or raw tokens. A signed JWT is issued after login and stored in an `httpOnly` cookie.

---

## 5. Technology Stack

| Layer | Choice |
|---|---|
| Frontend | React + TypeScript |
| Styling | Tailwind CSS |
| Backend | Python 3.12 + FastAPI |
| ORM / Migrations | SQLAlchemy 2.0 (async) + Alembic |
| Database | PostgreSQL 16 via Neon (serverless) |
| Auth library | Authlib (Google OAuth 2.0) + python-jose (JWT) |
| Hosting — Frontend | Firebase Hosting |
| Hosting — Backend | Cloud Run (Docker container) |
| Container registry | GCP Artifact Registry |
| Secrets | GCP Secret Manager |
| CI/CD | GitHub Actions (build + push + deploy on merge to `main`) |

---

## 6. Repository Structure

```
todo_app/
├── frontend/               # React + TypeScript app
│   ├── src/
│   │   ├── components/     # TodoItem, TodoList, LoginButton, etc.
│   │   ├── hooks/          # useAuth, useTodos
│   │   ├── api/            # Typed fetch wrappers for each endpoint
│   │   └── main.tsx
│   ├── index.html
│   └── package.json
├── backend/                # FastAPI application
│   ├── app/
│   │   ├── main.py         # FastAPI app, router registration, CORS
│   │   ├── auth.py         # OAuth flow, JWT issue/verify, session cookie
│   │   ├── models.py       # SQLAlchemy ORM models
│   │   ├── schemas.py      # Pydantic request/response schemas
│   │   ├── database.py     # Async engine, session factory
│   │   └── routers/
│   │       ├── todos.py    # CRUD endpoints
│   │       └── users.py    # /api/me
│   ├── alembic/            # DB migrations
│   ├── Dockerfile
│   └── requirements.txt
├── .github/
│   └── workflows/
│       └── deploy.yml      # CI/CD pipeline
└── DESIGN.md
```

---

## 7. Data Model

```sql
-- Users are created (or updated) on first OAuth login
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    google_id   TEXT UNIQUE NOT NULL,   -- Google "sub" claim from id_token
    email       TEXT UNIQUE NOT NULL,
    name        TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE todos (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT,
    completed   BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON todos(user_id);
```

A `updated_at` trigger (or SQLAlchemy `onupdate`) keeps the timestamp current on every PATCH.

---

## 8. REST API Design

All `/api/*` routes require a valid `session` cookie (JWT). Requests without a valid token receive `401 Unauthorized`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/auth/google` | Redirect to Google OAuth consent screen |
| `GET` | `/auth/google/callback` | OAuth callback; sets `session` cookie; redirects to frontend |
| `POST` | `/auth/logout` | Clears the session cookie |
| `GET` | `/api/me` | Returns `{ id, email, name }` for the current user |
| `GET` | `/api/todos` | Lists todos for current user (`?status=active\|completed\|all`) |
| `POST` | `/api/todos` | Creates a todo (`{ title, description? }`) |
| `PATCH` | `/api/todos/{id}` | Updates `title`, `description`, and/or `completed` |
| `DELETE` | `/api/todos/{id}` | Deletes a todo |

All responses are JSON. Errors follow `{ "detail": "<message>" }` (FastAPI default).

---

## 9. Authentication Flow

```
1.  User clicks "Sign in with Google"
2.  Browser  →  GET /auth/google
3.  Server generates a random `state` token, stores it in a short-lived cookie,
    and redirects to accounts.google.com with client_id + redirect_uri + state
4.  User consents on Google
5.  Google  →  GET /auth/google/callback?code=...&state=...
6.  Server validates state (CSRF protection), then POSTs to Google token endpoint
7.  Google returns id_token + access_token (server-side only — never sent to browser)
8.  Server verifies id_token signature, extracts { sub, email, name }
9.  Server upserts user row in DB (insert on first login, update name/email on subsequent)
10. Server mints a signed JWT { user_id, exp } with HS256 using JWT_SECRET
11. JWT is set as httpOnly, Secure, SameSite=Lax cookie named `session`
12. Browser is redirected to the React app — all subsequent API calls carry the cookie
```

**Security notes:**
- `state` parameter prevents CSRF on the OAuth callback
- `httpOnly` cookie blocks JavaScript access to the JWT (XSS mitigation)
- All PATCH/DELETE handlers verify the todo's `user_id` matches the JWT's `user_id` before acting

---

## 10. Deployment Pipeline

```
GitHub (push to main)
  └─► GitHub Actions: deploy.yml
        ├─► docker build backend/  →  push to Artifact Registry
        ├─► gcloud run deploy      →  Cloud Run (zero-downtime rolling update)
        └─► npm run build          →  firebase deploy  (Firebase Hosting)

Cloud Run service config:
  - Min instances: 0  (scale to zero)
  - Max instances: 3
  - Memory: 512 MB
  - Env vars injected from GCP Secret Manager:
      DATABASE_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, JWT_SECRET
```

**Required GCP setup (one-time):**
1. Enable APIs: Cloud Run, Artifact Registry, Secret Manager
2. Create OAuth 2.0 credentials in Google Cloud Console; add callback URI
3. Store secrets in Secret Manager; grant Cloud Run service account `secretAccessor` role
4. Configure Firebase Hosting rewrite: `/api/**` → Cloud Run service URL
5. Add Cloud Run service URL as authorised redirect URI in GCP OAuth config

---

## 11. Local Development

```
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Set env vars: DATABASE_URL (Neon dev branch), GOOGLE_CLIENT_ID/SECRET, JWT_SECRET
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev          # Vite dev server on :5173, proxies /api/* to localhost:8000
```

Neon provides free branching — use a separate Neon branch for local dev so migrations can be tested without touching the production database.

---

## 12. Cost Estimate (GCP, low traffic)

| Service | Cost |
|---|---|
| Cloud Run | ~$0/month (free tier: 2M requests, 360K GB-seconds) |
| Firebase Hosting | ~$0/month (free tier: 10 GB storage, 360 MB/day transfer) |
| Artifact Registry | ~$0/month (free tier: 0.5 GB) |
| Secret Manager | ~$0/month (free tier: 6 active versions) |
| Neon PostgreSQL | ~$0/month (free tier: 0.5 GB storage, auto-suspend) |
| **Total** | **~$0/month** |

The only cost trigger is sustained high traffic beyond GCP free-tier limits.
