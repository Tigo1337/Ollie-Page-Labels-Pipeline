#!/usr/bin/env bash
# One command to run the app (Replit "Run" button and deployments use this).
set -euo pipefail
cd "$(dirname "$0")/.."

# Python dependencies are installed by Replit's package manager, not at startup:
# the Nix-managed system Python environment is immutable.

# Build the frontend when it is missing or older than its sources.
if [ ! -f frontend/dist/index.html ] || \
   [ -n "$(find frontend/src frontend/index.html frontend/package.json -newer frontend/dist/index.html 2>/dev/null | head -1)" ]; then
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi

exec python -m uvicorn app.main:_app_factory --factory --host 0.0.0.0 --port "${PORT:-5000}"
