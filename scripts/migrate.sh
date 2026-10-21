#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
.venv/bin/alembic upgrade head
.venv/bin/python -m app.core.seed
