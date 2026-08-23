#!/usr/bin/env bash
# Start the AI Video Editor.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
PYTHON="${PYTHON:-python3}"
[ -d .venv ] && PYTHON=".venv/bin/python"
HOST="${HOST:-127.0.0.1}"; PORT="${PORT:-8000}"
echo "AI Video Editor  ->  http://$HOST:$PORT"
exec "$PYTHON" -m uvicorn backend.main:app --host "$HOST" --port "$PORT"
