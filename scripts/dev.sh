#!/usr/bin/env bash
# Developer tasks for macOS and Linux. Usage: ./scripts/dev.sh <task>
# Tasks: up, down, reset, logs, seed, demo, api, ui, test, itest, lint, fmt, check
set -euo pipefail
cd "$(dirname "$0")/.."

case "${1:-check}" in
  up)    docker compose up -d falkordb; echo "FalkorDB Browser: http://localhost:3000" ;;
  down)  docker compose down ;;
  reset) docker compose down -v; docker compose up -d falkordb ;;
  logs)  docker compose logs -f falkordb ;;
  seed)  python -m mandate.seed ;;
  demo)  python -m mandate.seed --reset ;;  # rebuild the demo tenant from scratch
  api)   uvicorn --factory mandate.api.app:create_app --port 8000 ;;  # reads .env
  ui)    cd ui && npm install && npm run dev ;;  # http://localhost:5173
  test)  pytest tests/unit -q ;;
  itest) pytest tests/integration -q ;;
  lint)  ruff check .; ruff format --check . ;;
  fmt)   ruff check --fix .; ruff format . ;;
  check) ruff check .; ruff format --check .; mypy; pytest tests/unit -q ;;
  *)     echo "unknown task: $1" >&2; exit 2 ;;
esac
