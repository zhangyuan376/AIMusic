#!/usr/bin/env bash
# Launch the local browser web UI on Linux/macOS.
# Windows users: use run_singing_web.bat instead.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "Virtual environment not found at $PYTHON" >&2
  echo "Run: bash setup_env.sh" >&2
  exit 1
fi

PORT="${PORT:-7860}"

# Best-effort: free the port if an old server is still listening.
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
elif command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
  if [ -n "$PIDS" ]; then
    echo "Stopping old web server on port $PORT (PIDs: $PIDS)"
    kill $PIDS 2>/dev/null || true
  fi
fi

exec "$PYTHON" -m singing_app.main web "$@"
