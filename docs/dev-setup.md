# Developer Setup

Status: v1.0 · Last updated 2026-10-06. Gets a working environment for Phase 1 onwards. Commands are for Windows PowerShell first, with the macOS/Linux equivalent where it differs.

## 1. Prerequisites

| Tool | Needed | Notes |
|---|---|---|
| Git | any recent | |
| Python | **3.12** | This machine currently reports Python 3.9.11, which is too old for `requires-python >= 3.12`. Install 3.12 alongside it. |
| Docker Desktop (with Compose v2) | yes | Verified present: Docker 29.5.3, Compose v5.1.4 |
| Node.js | 20 or newer | For Phase 7; Node 22 is present |
| GitHub CLI (`gh`) | optional | Logged in on this machine |

### Installing Python 3.12 on Windows
```powershell
winget install --id Python.Python.3.12 -e
py -3.12 --version        # should print Python 3.12.x
```
On macOS/Linux use your package manager or `pyenv install 3.12`.

## 2. First-time setup

```powershell
git clone https://github.com/Monolithic-Dev/agent-mandate.git
cd agent-mandate

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"

copy .env.example .env               # macOS/Linux: cp .env.example .env
# edit .env: set MANDATE_API_KEY to a random string of at least 16 characters

.\scripts\dev.ps1 up                 # macOS/Linux: ./scripts/dev.sh up
# FalkorDB Browser: http://localhost:3000
```

If PowerShell blocks the activation script: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## 3. Everyday tasks

| Task | Windows | macOS/Linux |
|---|---|---|
| Start FalkorDB | `.\scripts\dev.ps1 up` | `./scripts/dev.sh up` |
| Stop | `.\scripts\dev.ps1 down` | `./scripts/dev.sh down` |
| Wipe data and restart | `.\scripts\dev.ps1 reset` | `./scripts/dev.sh reset` |
| Logs | `.\scripts\dev.ps1 logs` | `./scripts/dev.sh logs` |
| Unit tests | `.\scripts\dev.ps1 test` | `./scripts/dev.sh test` |
| Lint | `.\scripts\dev.ps1 lint` | `./scripts/dev.sh lint` |
| Auto-format | `.\scripts\dev.ps1 fmt` | `./scripts/dev.sh fmt` |
| Everything CI runs | `.\scripts\dev.ps1 check` | `./scripts/dev.sh check` |

## 4. Pre-commit hooks (recommended)

```powershell
pip install pre-commit
pre-commit install
pre-commit run --all-files
```
Hooks run whitespace fixes, YAML and TOML checks, `ruff`, and a `gitleaks` secrets scan.

## 5. Git workflow

See [../CONTRIBUTING.md](../CONTRIBUTING.md): branches `type/slug`, Conventional Commits, pull requests to `main`. Commits use your own git identity; no co-author trailers.

## 6. Line endings (Windows)

`.gitattributes` normalises text files to LF (and `.ps1` to CRLF). If Git warns "LF will be replaced by CRLF", that is expected and harmless. When editing files with PowerShell, avoid `Get-Content | Set-Content` on UTF-8 files: Windows PowerShell 5.1 re-encodes them and can corrupt non-ASCII characters. Use an editor, or `[System.IO.File]::ReadAllText/WriteAllText` with `UTF8Encoding($false)`.

## 7. Verifying the environment

```powershell
python --version                       # 3.12.x inside the venv
docker compose ps                      # falkordb is "healthy"
pytest tests/unit -q                   # passes
python -c "import mandate; print(mandate.__version__)"
```
From Phase 1 onward, `pytest tests/integration -q` also needs FalkorDB running.

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `pip install -e .` says "requires a different Python" | Using Python 3.9 | Create the venv with `py -3.12` |
| Port 6379 or 3000 already in use | Another Redis or service (common on a developer machine) | Set `FALKORDB_PORT` and `FALKORDB_BROWSER_PORT` in `.env` (for example 6390 and 3010); Compose and the app both read them |
| `docker compose up` hangs on pull | Network or Docker not running | Start Docker Desktop; retry |
| FalkorDB container "unhealthy" | Still starting | Wait 10 seconds; `docker compose logs falkordb` |
| Tests cannot connect to FalkorDB | Container down or wrong host | `.\scripts\dev.ps1 up`; check `FALKORDB_HOST` and `FALKORDB_PORT` in `.env` |
| `mypy` cannot find imports | Package not installed in the venv | `pip install -e ".[dev]"` |
| CI fails on `ruff format --check` | Unformatted code | `.\scripts\dev.ps1 fmt` and commit |
| Garbled characters in a doc after editing | Re-encoding by PowerShell 5.1 | Restore from git (`git checkout -- <file>`) and edit with an editor |

## 9. Where to go next

Read [README.md](./README.md) for the reading order, then [phases/phase-1-scaffolding.md](./phases/phase-1-scaffolding.md).
