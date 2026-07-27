#!/usr/bin/env bash
# LocalBench Studio — Linux launcher.
# Verifies deps, builds frontend if missing, applies migrations on startup,
# and starts the local application. Bound to 127.0.0.1 by default.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"

HOST="${LOCALBENCH_HOST:-127.0.0.1}"
PORT="${LOCALBENCH_PORT:-8765}"
SKIP_BUILD="${LOCALBENCH_SKIP_BUILD:-0}"

step() { printf '\033[36m==> %s\033[0m\n' "$1"; }

# Security warning if binding to a non-local interface.
if [ "$HOST" != "127.0.0.1" ] && [ "$HOST" != "localhost" ]; then
  echo "WARNING: binding to $HOST exposes the application on other network interfaces." >&2
  echo "WARNING: LocalBench Studio has NO multi-user authentication. Only do this on a trusted private network." >&2
fi

# 1. Verify dependencies.
if [ ! -f "$VENV/bin/python" ]; then
  echo "ERROR: virtual environment not found. Run ./setup-linux.sh first." >&2
  exit 1
fi

# 2. Build frontend if not already built.
if [ ! -f "$FRONTEND/dist/index.html" ] && [ "$SKIP_BUILD" != "1" ]; then
  step "Building frontend..."
  (cd "$FRONTEND" && npm run build)
fi

# 3. Start the application.
export LOCALBENCH_HOST="$HOST"
export LOCALBENCH_PORT="$PORT"

URL="http://$HOST:$PORT"
step "Starting LocalBench Studio..."
echo -e "  \033[32mOpen: $URL\033[0m"
echo "  Press Ctrl+C to stop."
echo ""

# Run from the backend directory so relative paths (alembic/) resolve.
cd "$BACKEND"
exec "$VENV/bin/python" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
