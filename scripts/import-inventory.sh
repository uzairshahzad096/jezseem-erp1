#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
.venv/bin/python -m app.inventory.import_legacy
