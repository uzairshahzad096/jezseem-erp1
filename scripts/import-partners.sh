#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
.venv/bin/python -m app.partners.import_legacy
