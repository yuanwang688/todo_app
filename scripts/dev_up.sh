#!/usr/bin/env bash
# Brings up a local instance of the todo app for testing the chat assistant:
# a local Postgres (Docker, data persists across runs), migrated, seeded with
# 25 example tasks, plus the backend and frontend dev servers. Never touches
# the production Neon database — DATABASE_URL is overridden for every step.
#
# Usage:
#   scripts/dev_up.sh            # reuse existing local DB and seed data
#   scripts/dev_up.sh --fresh    # wipe the local DB and reseed from scratch
#
# Ctrl+C stops the backend, frontend, and the Postgres container (the Docker
# volume — and your seeded data — is left alone either way).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

FRESH=false
for arg in "$@"; do
  case "$arg" in
    --fresh) FRESH=true ;;
    -h|--help)
      sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg (use --fresh or --help)" >&2
      exit 1
      ;;
  esac
done

DB_CONTAINER="todo-app-local-db"
DB_VOLUME="todo-app-local-pgdata"
DB_PORT=55432
LOCAL_DATABASE_URL="postgresql+asyncpg://postgres:localdev@localhost:${DB_PORT}/todo"
BACKEND_PORT=8000
FRONTEND_PORT=5173

port_in_use() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&-; return 0; } || return 1
}

echo "==> Checking prerequisites"
command -v docker >/dev/null || { echo "docker is required — install it and try again." >&2; exit 1; }
[ -d "$BACKEND_DIR/.venv" ] || {
  echo "backend/.venv not found — run:" >&2
  echo "  cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-test.txt" >&2
  exit 1
}
[ -d "$FRONTEND_DIR/node_modules" ] || { echo "frontend/node_modules not found — run: cd frontend && npm install" >&2; exit 1; }
[ -f "$BACKEND_DIR/.env" ] || { echo "backend/.env not found — copy backend/.env.example to backend/.env and fill it in." >&2; exit 1; }

if ! grep -q "^ANTHROPIC_API_KEY=..*" "$BACKEND_DIR/.env" 2>/dev/null; then
  echo "    Note: ANTHROPIC_API_KEY isn't set in backend/.env — todos will work, but the" >&2
  echo "    assistant panel will show 'not configured' until you add one." >&2
fi

for p in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if port_in_use "$p"; then
    echo "Port $p is already in use — stop whatever's running there (maybe a previous" >&2
    echo "un-closed run of this script?) and try again." >&2
    exit 1
  fi
done

echo "==> Starting local Postgres ($DB_CONTAINER, port $DB_PORT)"
if [ "$FRESH" = true ]; then
  docker rm -f "$DB_CONTAINER" >/dev/null 2>&1 || true
  docker volume rm "$DB_VOLUME" >/dev/null 2>&1 || true
fi

if docker ps -a --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
  docker start "$DB_CONTAINER" >/dev/null
else
  docker run -d --name "$DB_CONTAINER" \
    -e POSTGRES_PASSWORD=localdev -e POSTGRES_DB=todo \
    -v "${DB_VOLUME}:/var/lib/postgresql/data" \
    -p "${DB_PORT}:5432" \
    postgres:16 >/dev/null
fi

echo "    Waiting for Postgres..."
ready=false
for _ in $(seq 1 30); do
  if docker exec "$DB_CONTAINER" pg_isready -U postgres >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
[ "$ready" = true ] || { echo "Postgres didn't become ready in time." >&2; docker logs "$DB_CONTAINER" | tail -20 >&2; exit 1; }

echo "==> Running migrations"
( cd "$BACKEND_DIR" && DATABASE_URL="$LOCAL_DATABASE_URL" ENVIRONMENT=development ./.venv/bin/alembic upgrade head )

echo "==> Seeding tasks"
SEED_ARGS=()
[ "$FRESH" = true ] && SEED_ARGS+=(--fresh)
( cd "$BACKEND_DIR" && DATABASE_URL="$LOCAL_DATABASE_URL" ENVIRONMENT=development \
    ./.venv/bin/python scripts/seed_local_dev.py "${SEED_ARGS[@]}" )

BACKEND_PID=""
FRONTEND_PID=""
CLEANED_UP=false
cleanup() {
  [ "$CLEANED_UP" = true ] && return
  CLEANED_UP=true
  echo
  echo "==> Stopping backend and frontend"
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  [ -n "$BACKEND_PID" ] && wait "$BACKEND_PID" 2>/dev/null || true
  [ -n "$FRONTEND_PID" ] && wait "$FRONTEND_PID" 2>/dev/null || true
  echo "==> Stopping local Postgres (data kept in the '$DB_VOLUME' volume)"
  docker stop "$DB_CONTAINER" >/dev/null 2>&1 || true
}
# EXIT alone is enough — bash runs it on a signal-induced exit too. Trapping
# INT/TERM as well would fire cleanup, let the script resume past `wait`,
# hit its own end, and fire EXIT a second time.
trap cleanup EXIT

echo "==> Starting backend on :$BACKEND_PORT"
# `exec` replaces the subshell with uvicorn itself, so $! is uvicorn's own
# PID — without it, `kill "$BACKEND_PID"` kills an empty wrapper shell and
# leaves uvicorn running as an orphan.
( cd "$BACKEND_DIR" && DATABASE_URL="$LOCAL_DATABASE_URL" ENVIRONMENT=development \
    exec ./.venv/bin/uvicorn app.main:app --port "$BACKEND_PORT" ) &
BACKEND_PID=$!

echo "==> Starting frontend on :$FRONTEND_PORT"
# Invoke vite directly (not `npm run dev`) — npm forks vite as a child of
# itself, so killing npm's PID doesn't reliably kill vite too. `exec` here
# for the same reason as the backend.
( cd "$FRONTEND_DIR" && exec ./node_modules/.bin/vite --port "$FRONTEND_PORT" ) &
FRONTEND_PID=$!

echo "    Waiting for both to come up..."
backend_ok=false
for _ in $(seq 1 20); do
  curl -s -o /dev/null "http://localhost:${BACKEND_PORT}/api/health" && { backend_ok=true; break; }
  sleep 1
done
[ "$backend_ok" = true ] || { echo "Backend didn't start — check the output above." >&2; exit 1; }

frontend_ok=false
for _ in $(seq 1 20); do
  curl -s -o /dev/null "http://localhost:${FRONTEND_PORT}" && { frontend_ok=true; break; }
  sleep 1
done
[ "$frontend_ok" = true ] || { echo "Frontend didn't start — check the output above." >&2; exit 1; }

cat <<EOF

────────────────────────────────────────────────────────────────────
  Local instance is up.

  1. Open http://localhost:${FRONTEND_PORT}/auth/dev-login
     — logs you straight in as the local dev test account, no Google
     OAuth needed.
  2. Click the 💬 Assistant button (bottom right) and try:
       "What's overdue?"
       "I've got half an hour before my next meeting. What can I knock out?"
       "Am I overcommitted today?"
       "I think I've entered some things twice. Can you tidy that up?"
       "Clear out my week — I'm overloaded. Push whatever isn't essential."
     (the last one needs Phase C's propose_changes tool, which hasn't
     shipped yet — the assistant will say so rather than pretend to help)

  Seed data persists across runs. Use --fresh to wipe and reseed.
  Press Ctrl+C to stop everything (your data is kept either way).
────────────────────────────────────────────────────────────────────
EOF

wait
