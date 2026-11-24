#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
api_port="${LEARNFLOW_API_PORT:-8000}"
web_port="${LEARNFLOW_WEB_PORT:-5173}"
backend_pid=""
frontend_pid=""

cleanup() {
  if [[ -n "$backend_pid" ]]; then kill "$backend_pid" 2>/dev/null || true; fi
  if [[ -n "$frontend_pid" ]]; then kill "$frontend_pid" 2>/dev/null || true; fi
}
trap cleanup INT TERM EXIT

command -v uv >/dev/null || {
  echo "uv is required: https://docs.astral.sh/uv/" >&2
  exit 1
}
command -v npm >/dev/null || {
  echo "npm is required" >&2
  exit 1
}

(
  cd "$project_root/backend"
  uv sync --group dev
  exec uv run uvicorn app.main:app --host 127.0.0.1 --port "$api_port"
) &
backend_pid=$!

if [[ ! -d "$project_root/frontend/node_modules" ]]; then
  (cd "$project_root/frontend" && npm ci)
fi

(
  cd "$project_root/frontend"
  exec npm run dev -- --port "$web_port"
) &
frontend_pid=$!

echo "LearnFlow API: http://127.0.0.1:${api_port}"
echo "LearnFlow Web: http://127.0.0.1:${web_port}"

while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 1
done

echo "One LearnFlow process exited; stopping the other." >&2
exit 1
