#!/usr/bin/env bash
# Starts backend and frontend together; Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."

cleanup() { kill 0; }
trap cleanup EXIT INT TERM

(cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000) &
(cd frontend && npm run dev) &

echo
echo "  Frontend  http://localhost:3000"
echo "  API docs  http://localhost:8000/api/docs"
echo
wait
