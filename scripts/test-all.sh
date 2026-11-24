#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"

(
  cd "$project_root/backend"
  uv sync --group dev
  uv run pytest -v
  uvx ruff check app tests
  uvx pip-audit --path .venv
)

(
  cd "$project_root/frontend"
  [[ -d node_modules ]] || npm ci
  npm test -- --run
  npm run build
  npm audit
  npm run test:e2e
)

echo "All LearnFlow checks passed."
