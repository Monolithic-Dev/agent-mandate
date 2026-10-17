# Deployment and Operations

Status: v1.0 · Last updated 2026-10-06 · Implements [architecture.md](./architecture.md) sections 6 and 9.

## 1. Target

**Local-first with Docker Compose.** The deliverable is a repository anyone can run with one command, plus an optional hosted demo. Reasons: no cost, no secrets exposure, identical to what a reviewer will run, and the project's data is synthetic.

Optional hosted demo: a single small VM (or a container host such as Fly.io or Railway) running the same Compose stack behind TLS (Caddy). Do this only after Phase 8 and only with the demo API key rotated.

## 2. Containers

`docker-compose.yml` (development) runs only `falkordb`; the API and the console run on the host (`scripts/dev.ps1 api` and `scripts/dev.ps1 ui`, or `dev.sh`). `docker-compose.prod.yml` runs the whole stack:

| Service | Image | Ports | Notes |
|---|---|---|---|
| `falkordb` | `falkordb/falkordb:6.0.1` (pinned in Compose and CI) | none in production (development: `127.0.0.1:6379`, Browser `127.0.0.1:3000`) | Password required; named volume `falkordb_data`; healthcheck `redis-cli ping` |
| `api` | built from `Dockerfile` (multi-stage, non-root) | `127.0.0.1:${API_PORT:-8000}` | `uvicorn --factory mandate.api.app:create_app`; read-only root filesystem; mounts `docs/results` read-only for `GET /v1/eval/latest` |
| `ui` | built from `ui/Dockerfile` (Node build, unprivileged nginx) | `127.0.0.1:${UI_PORT:-8080}` | Serves the console and proxies `/v1` to `api`. By default it adds no key and people sign in; with `MANDATE_UI_KEY` set it adds that key server-side instead, so it never reaches the browser; read-only root filesystem; healthcheck |

The MCP servers are separate processes (`python -m mandate.mcp_servers agent|admin`), not part of the stack.

Commands:
```
export MANDATE_API_KEY=$(openssl rand -hex 24) FALKORDB_PASSWORD=$(openssl rand -hex 24)
docker compose -p mandate-prod -f docker-compose.prod.yml up -d --build --wait
docker compose -p mandate-prod -f docker-compose.prod.yml exec api python -m mandate.seed
MANDATE_NEW_PASSWORD='a long passphrase' docker compose -p mandate-prod -f docker-compose.prod.yml \
  exec -e MANDATE_NEW_PASSWORD api python -m mandate.users add you@example.com --name You --role admin
# the console: http://127.0.0.1:8080, sign in with that email and passphrase
```

The first admin invites everyone else from **Users** in the console. `python -m mandate.users` also lists users and resets a password or disables a user from the server's shell, for recovery. Serve the console over HTTPS anywhere but localhost: the session cookie is `Secure`. Setting `MANDATE_UI_KEY` turns sign-in off and gives everyone who can reach the console that key's role; do that only on localhost.

## 2a. Render, free: one container

`render.yaml` at the repository root deploys one **free** web service from `deploy/free/Dockerfile`: FalkorDB (in memory, bound to localhost, with a password generated at start), the API and the built console, started by `deploy/free/start.sh`. The API serves the console's files itself (`MANDATE_STATIC_DIR`, `src/mandate/api/console.py`), so the console and the API share an origin and there is no nginx.

| | |
|---|---|
| You provide | `MANDATE_ADMIN_EMAIL` and `MANDATE_ADMIN_PASSWORD` (Render asks when you apply the Blueprint). `MANDATE_API_KEY` is generated. Optionally `MANDATE_DEMO_EMAIL` and `MANDATE_DEMO_PASSWORD`: a second, operator account for visitors. Our deployment: <https://agent-mandate-0ocw.onrender.com>. |
| On every start | The database starts empty; the script seeds the demo tenant (`MANDATE_SEED=0` skips it) and creates the admin. Render supplies `RENDER_EXTERNAL_URL`, which becomes `MANDATE_PUBLIC_URL` for approval links. |
| What you give up | The free plan sleeps after about 15 minutes idle (about a minute to wake) and keeps no data between starts. Anything created in the console is gone after a restart. Memory use is about 80 MB of the 512 MB. |
| Live agents | Add `GROQ_API_KEY` (or another provider's key) to the service's environment, and run `python -m mandate.agents "..." --provider groq` with `MANDATE_API_URL=http://127.0.0.1:$PORT` in its Shell (the Shell is not on the free plan; run it from your own machine against the public address instead, using the generated `MANDATE_API_KEY` from the dashboard). |

Run the same image anywhere that takes a container: `docker build -f deploy/free/Dockerfile -t agent-mandate-free .`, then `docker run -p 10000:10000 -e MANDATE_ADMIN_EMAIL=... -e MANDATE_ADMIN_PASSWORD=... agent-mandate-free`. CI builds it and checks sign-in on every change.

## 2b. Render, paid: three services and a disk

`deploy/render/paid.render.yaml` keeps data between restarts: the console (public), the API (private) and FalkorDB (private, with a 1 GB disk). Private services and disks are not on the free plan. Use it by choosing that file as the Blueprint path.

| Service | Built from | Notes |
|---|---|---|
| `mandate-console` | `ui/Dockerfile` | The only public service. `MANDATE_API_UPSTREAM` is the API's private `host:port`, filled in by Render. |
| `mandate-api` | `Dockerfile` | `MANDATE_API_KEY` generated; set `MANDATE_PUBLIC_URL` to the console's address; seed and create the admin in its Shell. |
| `mandate-db` | `deploy/render/falkordb/Dockerfile` | The pinned image behind a start script that takes the password from `FALKORDB_PASSWORD` and refuses to start without one. |

## 3. Configuration (`.env.example`)

| Variable | Purpose | Default |
|---|---|---|
| `FALKORDB_HOST` / `FALKORDB_PORT` | Graph connection | `localhost` / `6379` |
| `FALKORDB_PASSWORD` | If set on the server | empty |
| `MANDATE_API_KEY` | REST admin key | required |
| `MANDATE_MODEL` | Live LLM id | `claude-sonnet-5-5` |
| `ANTHROPIC_API_KEY` | Live runs only | empty |
| `MANDATE_LOG_LEVEL` | Log level | `INFO` |
| `MANDATE_RATE_LIMIT_PER_MIN` | API limit | `600` |
| `MANDATE_UI_KEY` | Key the console proxy adds (empty: people sign in) | empty in Docker; `MANDATE_API_KEY` in `npm run dev` unless `MANDATE_UI_AUTH=login` |
| `MANDATE_SESSION_TTL_SECONDS` | Longest a console session lasts | `43200` |
| `MANDATE_SESSION_IDLE_SECONDS` | Session ends after this long without a request | `7200` |
| `MANDATE_PUBLIC_URL` | The console's public address, for approval links in webhook messages | empty (messages carry no links) |
| `MANDATE_NOTIFY_INTERVAL_SECONDS` | How often the notifier looks for held actions (0: off) | `3` |
| `MANDATE_NOTIFY_LINK_TTL_SECONDS` | How long a messaged approval link lasts | `3600` |
| `MANDATE_WEBHOOK_ALLOW_PRIVATE` | Let webhooks reach private addresses (local testing only) | `false` |
| `MANDATE_COOKIE_SECURE` | Session cookie only over HTTPS (browsers also accept it on localhost) | `true` |

## 4. CI (`.github/workflows/ci.yml`)

Stages on every push and pull request:

1. **lint**: `ruff check` and `ruff format --check`.
2. **typecheck**: `mypy src/mandate`.
3. **unit**: `pytest tests/unit -q` (no database).
4. **integration**: a FalkorDB service container; `pytest tests/integration -q`.
5. **eval (stub)**: `python -m mandate.eval.runner --suite full --mode stub` and assert the thresholds in evaluation.md (unauthorised actions executed by `mandate` equals 0; false blocks at most 5 percent).
6. **ui**: in `ui/`, `npm ci`, `npm run lint` (strict TypeScript), `npm test` (vitest) and `npm run build`. The **docker** job also builds the console image, checks it serves the app and reaches the API without exposing the key, and runs the Playwright smoke tests against the production stack.
7. **secrets**: `gitleaks` scan.

Live LLM runs never execute in CI.

## 5. Environments

| Environment | Purpose |
|---|---|
| Local | Development and the demo |
| CI | Automated checks with a throwaway FalkorDB container |
| Optional hosted demo | Public showcase with rotated key |

No staging environment; the data is synthetic.

## 6. Monitoring and logging

- JSON logs (`structlog`) on stdout; `docker compose logs -f api`.
- `/healthz` shows graph reachability.
- Per-check `latency_ms` stored on `Decision`; `GET /v1/eval/...` summarises it.
- "Is it broken during a demo?" checklist in testing.md section 6: healthz, one check call, one UI graph load.

## 7. Rollback and recovery

- Images are tagged by git SHA; roll back with `docker compose up -d` after checking out the previous tag.
- FalkorDB data is synthetic and reproducible: `docker compose down -v && docker compose up -d && python -m mandate.seed` restores a known state in under a minute.
- Keep a recorded demo video as the fallback if live infrastructure fails.

## 8. Cost

Local: zero. Live LLM runs: bounded by the cap in ai-pipeline.md section 7 (target under US$2 for the live set). Optional hosted demo: roughly US$5 to 10 per month for one small VM, to be confirmed against the chosen provider.

## 9. Assumptions
- Docker Desktop is available on the developer machine (Windows 11 here).
- The FalkorDB image tag will be pinned after Phase 2 so behaviour does not drift.
