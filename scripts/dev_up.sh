#!/usr/bin/env bash
# Brings up a local instance of the todo app for testing the chat assistant:
# a local Postgres (Docker, data persists across runs), migrated, seeded with
# 25 example tasks, plus the backend and frontend dev servers. Never touches
# the production Neon database — DATABASE_URL is overridden for every step.
#
# Usage:
#   scripts/dev_up.sh            # reuse existing local DB and seed data
#   scripts/dev_up.sh --fresh    # wipe the local DB and reseed from scratch
#   scripts/dev_up.sh --ollama   # run the assistant on a local model (Ollama in
#                                # Docker) instead of the Claude API — free, but
#                                # far weaker; for testing plumbing, not quality.
#                                # Uses the NVIDIA GPU if Docker can reach it, and
#                                # keeps the model loaded until Ctrl+C.
#                                # OLLAMA_MODEL=<tag> picks the model (default
#                                # qwen2.5:7b with a GPU, qwen2.5:3b without);
#                                # the first run downloads it.
#
# Ctrl+C stops the backend, frontend, and the Postgres (and Ollama) containers
# (the Docker volumes — your seeded data, downloaded models — are kept).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

FRESH=false
OLLAMA=false
for arg in "$@"; do
  case "$arg" in
    --fresh) FRESH=true ;;
    --ollama) OLLAMA=true ;;
    -h|--help)
      sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg (use --fresh, --ollama, or --help)" >&2
      exit 1
      ;;
  esac
done

DB_CONTAINER="todo-app-local-db"
DB_VOLUME="todo-app-local-pgdata"
DB_PORT=55432
LOCAL_DATABASE_URL="postgresql+asyncpg://postgres:localdev@localhost:${DB_PORT}/todo"
BACKEND_PORT=8000
OLLAMA_CONTAINER="todo-app-ollama"
OLLAMA_VOLUME="todo-app-ollama-models"
OLLAMA_PORT=11434
OLLAMA_MODEL="${OLLAMA_MODEL:-}"  # default depends on GPU — see below
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

if [ "$OLLAMA" = false ] && ! grep -q "^ANTHROPIC_API_KEY=..*" "$BACKEND_DIR/.env" 2>/dev/null; then
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

# Overrides for the backend's assistant settings. Env vars beat backend/.env in
# pydantic-settings, so these win over whatever ANTHROPIC_* values .env has.
BACKEND_LLM_ENV=()
if [ "$OLLAMA" = true ]; then
  # Use the NVIDIA GPU when Docker can reach it (needs nvidia-container-toolkit);
  # otherwise Ollama runs on CPU, which is several times slower.
  OLLAMA_GPU_ARGS=()
  OLLAMA_GPU=no
  if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q nvidia; then
    OLLAMA_GPU_ARGS=(--gpus all)
    OLLAMA_GPU=yes
    echo "==> Starting local Ollama ($OLLAMA_CONTAINER, port $OLLAMA_PORT, GPU)"
  else
    echo "==> Starting local Ollama ($OLLAMA_CONTAINER, port $OLLAMA_PORT, CPU only — no NVIDIA runtime in Docker)"
  fi
  # The 7B answers noticeably better (e.g. gets "what's overdue?" right) and
  # takes a few seconds per turn on a 6 GB GPU; on CPU it's minutes, so fall
  # back to the 3B there.
  if [ -z "$OLLAMA_MODEL" ]; then
    if [ "$OLLAMA_GPU" = yes ]; then OLLAMA_MODEL=qwen2.5:7b; else OLLAMA_MODEL=qwen2.5:3b; fi
  fi
  # GPU access and env vars are fixed at container creation, so the container
  # is labelled with the config it was made with and recreated when that
  # changes (e.g. the NVIDIA toolkit was installed since). Models live in the
  # volume, so nothing is re-downloaded.
  OLLAMA_CONFIG="gpu=${OLLAMA_GPU};keep_alive=-1"
  if docker ps -a --format '{{.Names}}' | grep -qx "$OLLAMA_CONTAINER"; then
    current=$(docker inspect -f '{{index .Config.Labels "todo-app.ollama-config"}}' "$OLLAMA_CONTAINER")
    if [ "$current" != "$OLLAMA_CONFIG" ]; then
      docker rm -f "$OLLAMA_CONTAINER" >/dev/null
    fi
  fi
  if docker ps -a --format '{{.Names}}' | grep -qx "$OLLAMA_CONTAINER"; then
    docker start "$OLLAMA_CONTAINER" >/dev/null
  else
    # OLLAMA_KEEP_ALIVE=-1: never unload the model while the container runs.
    # Ollama's default unloads it after 5 idle minutes, and reloading costs
    # ~1 min on the next message. The container stops with this script, which
    # frees the GPU memory.
    docker run -d --name "$OLLAMA_CONTAINER" "${OLLAMA_GPU_ARGS[@]}" \
      --label "todo-app.ollama-config=$OLLAMA_CONFIG" \
      -e OLLAMA_KEEP_ALIVE=-1 \
      -v "${OLLAMA_VOLUME}:/root/.ollama" \
      -p "${OLLAMA_PORT}:11434" \
      ollama/ollama >/dev/null
  fi
  ollama_ok=false
  for _ in $(seq 1 30); do
    curl -s -o /dev/null "http://localhost:${OLLAMA_PORT}/api/version" && { ollama_ok=true; break; }
    sleep 1
  done
  [ "$ollama_ok" = true ] || { echo "Ollama didn't come up in time." >&2; docker logs "$OLLAMA_CONTAINER" | tail -20 >&2; exit 1; }
  if ! docker exec "$OLLAMA_CONTAINER" ollama show "$OLLAMA_MODEL" >/dev/null 2>&1; then
    echo "    Pulling $OLLAMA_MODEL (first run only — can take a while)..."
    docker exec "$OLLAMA_CONTAINER" ollama pull "$OLLAMA_MODEL"
  fi
  # Load the model now, in the background while the rest starts up, so the
  # first chat message doesn't pay for it. A one-token generation (not just a
  # load) also gets the GPU's first-run warm-up out of the way.
  echo "    Loading $OLLAMA_MODEL into memory in the background..."
  curl -s -o /dev/null "http://localhost:${OLLAMA_PORT}/api/generate" \
    -d "{\"model\": \"$OLLAMA_MODEL\", \"prompt\": \"hi\", \"stream\": false, \"options\": {\"num_predict\": 1}}" &
  # Ollama ignores the key, but the SDK and the backend's is_configured() need one.
  BACKEND_LLM_ENV=(
    ANTHROPIC_BASE_URL="http://localhost:${OLLAMA_PORT}"
    ANTHROPIC_API_KEY=ollama
    ANTHROPIC_MODEL="$OLLAMA_MODEL"
  )
fi

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
  if [ "$OLLAMA" = true ]; then
    echo "==> Stopping local Ollama (models kept in the '$OLLAMA_VOLUME' volume)"
    docker stop "$OLLAMA_CONTAINER" >/dev/null 2>&1 || true
  fi
}
# EXIT alone is enough — bash runs it on a signal-induced exit too. Trapping
# INT/TERM as well would fire cleanup, let the script resume past `wait`,
# hit its own end, and fire EXIT a second time.
trap cleanup EXIT

echo "==> Starting backend on :$BACKEND_PORT"
# `exec` replaces the subshell with uvicorn itself, so $! is uvicorn's own
# PID — without it, `kill "$BACKEND_PID"` kills an empty wrapper shell and
# leaves uvicorn running as an orphan.
# `env` (rather than export) because BACKEND_LLM_ENV is usually empty, and env
# execs into uvicorn, so the PID is still uvicorn's.
( cd "$BACKEND_DIR" && DATABASE_URL="$LOCAL_DATABASE_URL" ENVIRONMENT=development \
    exec env "${BACKEND_LLM_ENV[@]}" ./.venv/bin/uvicorn app.main:app --port "$BACKEND_PORT" ) &
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
