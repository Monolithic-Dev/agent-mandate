# Developer tasks for Windows. Usage: .\scripts\dev.ps1 <task>
# Tasks: up, down, reset, logs, seed, demo, api, ui, test, itest, lint, fmt, check
param(
    [Parameter(Position = 0)]
    [ValidateSet("up", "down", "reset", "logs", "seed", "demo", "api", "ui", "test", "itest", "lint", "fmt", "check")]
    [string]$Task = "check"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

switch ($Task) {
    "up"    { docker compose up -d falkordb; Write-Host "FalkorDB Browser: http://localhost:3000" }
    "down"  { docker compose down }
    "reset" { docker compose down -v; docker compose up -d falkordb }
    "logs"  { docker compose logs -f falkordb }
    "seed"  { python -m mandate.seed }
    "demo"  { python -m mandate.seed --reset }  # rebuild the demo tenant from scratch
    "api"   { uvicorn --factory mandate.api.app:create_app --port 8000 }  # reads .env
    "ui"    { Push-Location ui; try { npm install; npm run dev } finally { Pop-Location } }  # http://localhost:5173
    "test"  { pytest tests/unit -q }
    "itest" { pytest tests/integration -q }
    "lint"  { ruff check .; ruff format --check . }
    "fmt"   { ruff check --fix .; ruff format . }
    "check" { ruff check .; ruff format --check .; mypy; pytest tests/unit -q }
}
