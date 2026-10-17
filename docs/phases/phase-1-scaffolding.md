# Phase 1: Scaffolding and Environment

## Plan at a glance

| # | Phase | Goal | Effort share |
|---|---|---|---|
| **1** | **Scaffolding (this file)** | Repo, tooling, CI, Compose, `GraphClient` smoke test | 5% |
| 2 | Data layer | Schema, indexes, tenants, queries, seed | 8% |
| 3 | Authority engine | `check_authority`; S1 passes against real FalkorDB | 18% |
| 4 | Gateway and API | MCP agent/admin profiles, sandbox, guard, REST core | 14% |
| 5 | Agents and evaluation | Scripted LLM, agent kinds, S1–S3, S5, S6, metrics | 15% |
| 6 | Lineage tools | Blast radius, quarantine, replay; S4 | 10% |
| 7 | UI and demo | Graph view, split-screen, decision, blast radius, replay | 14% |
| 8 | Planner (stretch, gated) | Verified revocation planner; S7 | 6% |
| 9 | Hardening and release | Edge cases, live runs, results, README, video | 10% |

Nominal total about 100 hours (see [../roadmap.md](../roadmap.md)). Phases run in order; each ends with a git tag `phase-<n>-complete`.

---

## Header

- **Goal (done means):** `docker compose up -d falkordb` works; `pip install -e ".[dev]"` works; `pytest` passes including a real round trip to FalkorDB; CI is green on a pull request.
- **Preconditions:** Docker Desktop, Python 3.12, Node 20 (for Phase 7), Git. The repo `agent-mandate` exists with `main` containing `.gitignore`.
- **Implements:** [../project-structure.md](../project-structure.md) section 1; [../deployment.md](../deployment.md) sections 2 to 4; [../architecture.md](../architecture.md) section 3 (`mandate.graph`).

## Already done by the repository setup commit

The setup commit on `main` already contains: the package tree with empty `__init__.py` files (task 3), `pyproject.toml` (task 2), `docker-compose.yml` with the `falkordb` service and `.env.example` (task 7), a CI workflow with lint, typecheck and unit jobs (task 11, partial), `tests/unit/test_package.py` and `tests/unit/test_parser_cases_file.py`, `tests/data/parser_cases.csv`, `scripts/dev.ps1` and `scripts/dev.sh`, `.pre-commit-config.yaml`, `.editorconfig`, `.gitattributes`, contribution and security files. Verify them rather than recreating: install Python 3.12 (see [../dev-setup.md](../dev-setup.md)), run `pip install -e ".[dev]"`, `.\scripts\dev.ps1 check`, and confirm CI is green. Still to do in this phase: tasks 4, 5, 6, 8, 9, 10 (config, ids, logging, `GraphClient`, wait script, the named tests) and the integration CI job.

## Task breakdown

1. **Branch.** `git switch -c feat/scaffolding`.
2. **`pyproject.toml`.** Package `mandate`, `requires-python = ">=3.12"`, src layout (`[tool.setuptools.packages.find] where = ["src"]`). Dependencies: `falkordb`, `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `pydantic-settings`, `structlog`, `mcp`, `anthropic`, `httpx`, `pyyaml`. Dev extras: `pytest`, `pytest-asyncio`, `hypothesis`, `ruff`, `mypy`, `coverage`. Configure `[tool.ruff]` (line length 100), `[tool.pytest.ini_options]` (`asyncio_mode = "auto"`, markers `integration`, `scenario`), `[tool.mypy]` (strict on `mandate.authority` and `mandate.graph`).
3. **Create the tree** from project-structure.md section 1 with empty `__init__.py` files (`src/mandate/{graph,models,authority,lineage,gateway,gateway/sandbox,agents,api,api/routes,eval}`), `tests/{unit,integration,e2e}`, `scripts/`.
4. **`src/mandate/config.py`.** `class Settings(BaseSettings)` with fields from deployment.md section 3 (`falkordb_host`, `falkordb_port`, `falkordb_password`, `mandate_api_key`, `mandate_model`, `anthropic_api_key`, `mandate_log_level`, `mandate_rate_limit_per_min`); `model_config = SettingsConfigDict(env_file=".env", env_prefix="")`; `get_settings()` cached with `lru_cache`. **Validation:** `mandate_api_key` must be at least 16 characters when the API starts (raise a clear error); never log values.
5. **`src/mandate/ids.py`.** `now_ms() -> int` and `new_id(prefix: str) -> str` returning `<prefix>_<26 chars>` (48-bit time plus 80 bits from `secrets`, Crockford base32, uppercase). `PREFIXES = {"prn","utt","ins","scp","agt","sum","act","dec","apr","dlg"}`; raise `ValueError` for any other prefix. `ID_RE` from data-model.md section 10.
6. **`src/mandate/logging.py`.** `configure_logging(level)` using `structlog` JSON renderer; a processor that redacts keys containing `key`, `token`, `secret`, `password`.
7. **`docker-compose.yml`** with the `falkordb` service only for now: image `falkordb/falkordb:latest`, ports `127.0.0.1:6379:6379` and `127.0.0.1:3000:3000`, volume `falkordb_data:/var/lib/falkordb/data`, healthcheck `redis-cli ping` every 5 s (5 retries). **`.env.example`** with every variable from deployment.md section 3 and empty secrets.
8. **`src/mandate/graph/client.py`.** `class GraphClient` with:
   - `__init__(settings)`: builds `FalkorDB(host, port, password)`; connection errors raise `GraphUnavailable` (custom exception in `mandate/errors.py`).
   - `ping() -> bool` (lists graphs; returns False on exception).
   - `graph(name) -> Graph` validating `name` against `^[a-z0-9_]{1,60}$` (also allows the `__replay_` infix).
   - `run(graph_name, query_name, params) -> list[dict]`: loads the Cypher from `src/mandate/graph/queries/<query_name>.cypher` (cached), executes with parameters, converts the result set to dicts. **Rejects** any `query_name` not matching `^q\d{2}_[a-z_]+$` or whose file is missing; there is no method that accepts raw query text except `run_admin_text()`, used only by `schema.py` and tests.
   - `copy_graph(src, dest, retries=3)`, `delete_graph(name)`, `list_graphs()`.
   - **Error handling:** wrap driver exceptions into `GraphUnavailable` (connection) or `GraphQueryError` (bad query); retry connection errors twice with 100 ms backoff.
9. **`scripts/wait_for_falkordb.py`.** Polls `GraphClient.ping()` up to 30 s, exits non-zero on timeout.
10. **Tests (write first, make them pass):**
    - `tests/unit/test_ids.py`: `test_new_id_matches_regex`, `test_new_id_rejects_unknown_prefix`, `test_ids_are_time_ordered`, `test_ids_unique_over_10000`.
    - `tests/unit/test_config.py`: `test_settings_read_env`, `test_short_api_key_rejected_on_startup_validation`.
    - `tests/unit/test_logging_redaction.py`: `test_secret_keys_redacted`.
    - `tests/unit/test_client_validation.py`: `test_graph_name_validation`, `test_run_rejects_unknown_query_name`, `test_run_rejects_path_traversal_query_name`.
    - `tests/integration/test_graph_smoke.py` (`@pytest.mark.integration`): `test_roundtrip_create_and_match`, `test_copy_graph_creates_independent_copy`, `test_delete_graph`.
11. **CI** `.github/workflows/ci.yml` with jobs lint, typecheck, unit, integration (FalkorDB `services:` container with a health check), per deployment.md section 4. The eval, ui and secrets stages are added as no-op placeholders with `if: false` and enabled in later phases.
12. **Commit** each logical unit with Conventional Commit messages; open a pull request to `main`.

## Real-world engineering concerns

- **Connection robustness:** FalkorDB may still be starting when tests begin; `wait_for_falkordb.py` runs before integration tests locally and in CI.
- **Query safety from day one:** the `run()` restriction is what makes later injection tests meaningful; do not add a raw-text escape hatch.
- **Secrets:** `.env` is git-ignored; run `git status` before every commit to confirm no key file is staged.
- **Windows:** use forward slashes in code; scripts have `.sh` and `.ps1` variants where needed.

## Definition of done

- [ ] `docker compose up -d falkordb && python scripts/wait_for_falkordb.py` exits 0.
- [ ] `pip install -e ".[dev]"` succeeds on a clean virtual environment.
- [ ] `pytest tests/unit -q` passes with the named tests above.
- [ ] `pytest tests/integration -q` passes against the running container.
- [ ] `ruff check .` and `mypy src/mandate` pass.
- [ ] CI is green on the pull request.
- [ ] `GraphClient.run("x; MATCH (n) DELETE n", {})` raises `ValueError` (not executed).

## Risks and blockers

| Risk | Mitigation |
|---|---|
| Docker Desktop not running or port 6379 already in use | Check `docker ps`; change the host port in `.env` and Compose |
| `falkordb` client API differs from assumed method names | Verify `select_graph`, `query`, `copy`, `delete`, `list_graphs` in the installed version before writing wrappers; adjust only `client.py` |
| `mcp` package version differences | Pin versions after the first successful install in `pyproject.toml` |

## Time budget

5 percent of the project, about 5 hours. **Cut first if long:** the mypy strictness and the CI placeholders (keep lint and unit).

## Handoff

Phase 2 can assume: a working `GraphClient` with the restricted `run()`, `Settings`, `new_id`, structured logging, a healthy local FalkorDB, and green CI. Tag: `git tag phase-1-complete`.
