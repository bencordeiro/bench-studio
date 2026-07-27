#!/usr/bin/env bash
# LocalBench Studio — Linux setup.
# Creates the Python venv, installs backend deps, and installs/builds the frontend.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"

step() { printf '\033[36m==> %s\033[0m\n' "$1"; }

# 1. Verify Python (3.11+).
step "Checking Python..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Install Python 3.11+ (e.g. sudo apt install python3.12 python3.12-venv)." >&2
  exit 1
fi
PYVER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "  Python $PYVER detected."
PYMAJOR="$(python3 -c 'import sys; print(sys.version_info.major)')"
PYMINOR="$(python3 -c 'import sys; print(sys.version_info.minor)')"
if [ "$PYMAJOR" -lt 3 ] || { [ "$PYMAJOR" -eq 3 ] && [ "$PYMINOR" -lt 11 ]; }; then
  echo "ERROR: Python 3.11+ required (found $PYVER)." >&2
  exit 1
fi

# 2. Create venv.
if [ ! -f "$VENV/bin/python" ]; then
  step "Creating virtual environment..."
  python3 -m venv "$VENV"
fi

# 3. Install backend deps.
step "Installing backend dependencies..."
"$VENV/bin/python" -m pip install --upgrade pip -q
"$VENV/bin/python" -m pip install -e "$BACKEND[dev]" -q

# 4. Install + build frontend.
step "Checking Node.js..."
if ! command -v node >/dev/null 2>&1; then
  echo "ERROR: node not found. Install Node 18+ (e.g. via your package manager or https://nodejs.org/)." >&2
  exit 1
fi
if [ ! -d "$FRONTEND/node_modules" ]; then
  step "Installing frontend dependencies..."
  (cd "$FRONTEND" && npm install)
fi
step "Building frontend (production)..."
(cd "$FRONTEND" && npm run build)

echo ""
echo -e '\033[32mSetup complete.\033[0m'
echo "Run the application with: ./run-linux.sh"
