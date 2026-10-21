#!/usr/bin/env bash
# One-time setup (Linux / macOS). Run from the project root: ./scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[1/4] Checking .env"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "      Created .env — edit it now and set POSTGRES_PASSWORD, DATABASE_URL,"
  echo "      SECRET_KEY and SEED_ADMIN_PASSWORD, then run this again."
  exit 0
fi

echo "[2/4] Creating Python virtual environment"
[ -d backend/.venv ] || python3 -m venv backend/.venv

echo "[3/4] Installing Python packages"
backend/.venv/bin/pip install --upgrade pip --quiet
backend/.venv/bin/pip install -r backend/requirements.txt

echo "[4/4] Installing frontend packages"
(cd frontend && npm install)

echo
echo "Setup complete. Next:  ./scripts/migrate.sh  then  ./scripts/dev.sh"
