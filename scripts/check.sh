#!/usr/bin/env bash
# Single verification entry point (Linux/macOS). Mirrors scripts/check.ps1.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
unset VIRTUAL_ENV

step() { echo "==> $1"; }

cd "$root/backend"
step "backend: sync";        uv sync --locked --quiet
step "backend: ruff check";  uv run ruff check .
step "backend: ruff format"; uv run ruff format --check .
step "backend: pytest";      uv run pytest -q

cd "$root/frontend"
if [ ! -d node_modules ]; then step "frontend: npm ci"; npm ci; fi
step "frontend: prettier";     npm run lint
step "frontend: api types";    npm run api:types
step "frontend: svelte-check"; npm run check
step "frontend: build";        npm run build

echo "OK: all checks passed"
