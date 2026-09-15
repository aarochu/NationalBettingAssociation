#!/usr/bin/env bash
# Start the local web app at http://127.0.0.1:8420 (override with PORT=...)
# Creates .venv and installs dependencies on first run.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "No .env found. Copy .env.example to .env and fill it in first." >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r ingest/requirements.txt -r app/requirements.txt

exec .venv/bin/uvicorn app.server:app \
  --host 127.0.0.1 --port "${PORT:-8420}" \
  --reload --reload-dir app
