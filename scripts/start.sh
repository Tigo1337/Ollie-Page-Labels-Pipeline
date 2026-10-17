#!/usr/bin/env bash
# One command to run the app (Replit "Run" button and deployments use this).
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pip install -q -r requirements.txt
if [ -n "${REPL_ID:-}" ]; then
  python -m pip install -q replit-object-storage || echo "replit-object-storage not installed; using local storage"
fi

# Build the frontend when it is missing or older than its sources.
if [ ! -f frontend/dist/index.html ] || \
   [ -n "$(find frontend/src frontend/index.html frontend/package.json -newer frontend/dist/index.html 2>/dev/null | head -1)" ]; then
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi

exec python -m uvicorn app.main:_app_factory --factory --host 0.0.0.0 --port "${PORT:-8000}"
