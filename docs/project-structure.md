# Project Structure

Status: v1.0 · Last updated 2026-10-06 · Implements [architecture.md](./architecture.md) section 3.

## 1. Repo layout

A single monorepo (`agent-mandate`): backend, UI, evaluation and docs change together, one person can own all of it, and CI is one workflow.

```
agent-mandate/
├── README.md
├── CONTRIBUTING.md  SECURITY.md
├── .editorconfig  .gitattributes  .pre-commit-config.yaml
├── pyproject.toml              # package "mandate", deps, ruff, pytest config
├── docker-compose.yml          # falkordb, api, ui
├── Dockerfile                  # api image
├── .env.example                # all env vars, no secrets
├── .gitignore
├── .github/
│   ├── workflows/ci.yml  pull_request_template.md  CODEOWNERS
│   └── ISSUE_TEMPLATE/  bug_report.md  feature_request.md
├── docs/
│   ├── README.md (index)  PRD.md  architecture.md  project-structure.md  data-model.md
│   ├── api-spec.md  ai-pipeline.md  prompts.md  evaluation.md  scenarios.md
│   ├── security-privacy.md  deployment.md  dev-setup.md  integration-guide.md
│   ├── edge-cases.md  ux-flows.md  roadmap.md  testing.md  decisions.md
│   ├── prior-art.md  claims-ledger.md  risk-register.md  demo-and-qa.md
│   ├── engineering-review.md  design-patterns.md
│   ├── spec/authority-semantics.md   # normative rules AUTH-001..AUTH-027
│   ├── results/                # committed evaluation reports (Phase 9)
│   └── phases/                 # phase-1-*.md ... phase-9-*.md
├── src/mandate/
│   ├── __init__.py
│   ├── config.py               # Settings (pydantic-settings), env loading
│   ├── logging.py              # structlog setup with secret redaction
│   ├── ids.py                  # new_id(prefix), is_valid_id
│   ├── clock.py                # Clock protocol, SystemClock, FixedClock
│   ├── errors.py               # MandateError hierarchy (codes match api-spec.md)
│   ├── graph/
│   │   ├── client.py           # GraphClient: select_graph, run, copy, delete
│   │   ├── tenants.py          # create_tenant, tenant_graph_name, list_tenants
│   │   ├── schema.py           # ensure_indexes(graph)
│   │   ├── store.py            # FalkorAuthorityStore: implements authority.ports (the adapter)
│   │   └── queries/            # *.cypher, one query per file (see data-model.md section 7)
│   ├── models/
│   │   ├── domain.py           # pydantic: Utterance, Instruction, Scope, Agent, Action, Decision...
│   │   └── api.py              # request/response models
│   ├── authority/
│   │   ├── parser.py           # deterministic instruction parser
│   │   ├── lineage.py          # lineage_trust(instruction)
│   │   ├── precedence.py       # pick winner among candidates
│   │   ├── delegation.py       # chains and scope intersection
│   │   ├── ports.py            # Protocols the core needs (AuthorityStore, ...); no I/O imports
│   │   ├── scope.py            # scope matching (glob, constraints)
│   │   ├── lineage.py  delegation.py  candidates.py   # lineage trust, chains, snapshot
│   │   ├── pdp.py              # PolicyDecisionPoint protocol + DeterministicPDP (pure decision)
│   │   ├── check.py            # check_authority(): loads snapshot, calls the PDP, persists
│   │   ├── explain.py          # template-based explanations (never from a model)
│   │   └── service.py          # AuthorityService: ingest, confirm, revoke, delegate, check, explain
│   ├── lineage/
│   │   ├── blast_radius.py
│   │   ├── replay.py
│   │   └── planner.py          # stretch
│   ├── gateway/
│   │   ├── agent_server.py     # MCP agent profile
│   │   ├── admin_server.py     # MCP admin profile
│   │   ├── tools.py            # TOOLS: argument models, action type and resource per tool
│   │   ├── guard.py            # guarded_call(), resolve_pending(): validate, check, execute
│   │   └── sandbox/
│   │       ├── state.py        # seeded mail, orders, files
│   │       └── actions.py      # validated sandbox operations
│   ├── agents/
│   │   ├── prompts/            # versioned prompt files, see docs/prompts.md
│   │   ├── llm.py              # LLMClient protocol
│   │   ├── anthropic_llm.py    # live provider
│   │   ├── scripted_llm.py     # deterministic
│   │   ├── mandate_agent.py
│   │   ├── naive_agent.py      # rules in prompt + compaction
│   │   └── extraction.py       # LLM instruction extraction (optional live)
│   ├── api/
│   │   ├── app.py              # create_app()
│   │   ├── deps.py             # auth, graph client
│   │   └── routes/             # tenants.py utterances.py instructions.py delegations.py
│   │                           # check.py decisions.py actions.py graph_view.py
│   │                           # runs.py eval.py plan.py
│   └── eval/
│       ├── scenario.py  baselines.py  surfaces.py  runner.py  metrics.py  report.py  __main__.py
│       ├── agentdojo/          # optional Phase 8b: defence element, scope synthesis, runner
│       ├── scenarios/          # S1..S7 YAML + variants
│       ├── loader.py  runner.py  metrics.py  report.py  concurrency.py
├── ui/
│   ├── package.json  vite.config.ts  index.html
│   └── src/
│       ├── main.tsx  App.tsx  api.ts  types.ts
│       ├── components/ GraphView.tsx DecisionPanel.tsx SplitRun.tsx
│       │               BlastRadius.tsx ReplayDiff.tsx RulesList.tsx
│       └── pages/ Demo.tsx Tenant.tsx Eval.tsx
├── tests/
│   ├── unit/  integration/  e2e/  conftest.py
└── scripts/
    ├── seed.py  demo.ps1  demo.sh  wait_for_falkordb.py
```

## 2. Naming conventions

| Thing | Convention | Example |
|---|---|---|
| Python modules and functions | `snake_case` | `check_authority` |
| Classes and pydantic models | `PascalCase` | `Decision` |
| Graph labels | `PascalCase` | `Instruction` |
| Relationship types | `UPPER_SNAKE` | `DELEGATES_TO` |
| Node properties | `snake_case` | `valid_from` |
| IDs | prefix plus ULID-like | `ins_01J...`, `utt_`, `agt_`, `act_`, `dec_`, `apr_`, `dlg_`, `scp_` |
| Time | epoch milliseconds, integer | `1760500000000` |
| REST paths | `/v1/...`, plural nouns, kebab-case | `/v1/tenants/{tid}/blast-radius` |
| MCP tools | `snake_case`, domain prefix | `email_delete` |
| Scenarios | `S<number>_<slug>_v<variant>.yaml` | `S1_rule_lost_v2.yaml` |
| Branches | `type/short-slug` | `docs/architecture`, `feat/check-authority` |
| Commits | Conventional Commits | `feat(authority): add precedence rules` |

## 3. Where do I start

Read [PRD.md](./PRD.md), then [data-model.md](./data-model.md) (the schema everything shares), then [architecture.md](./architecture.md) section 5 (the guarded call). Open [phases/phase-1-scaffolding.md](./phases/phase-1-scaffolding.md) and work through the phases in order. The first runnable milestone is Phase 3, a passing `check_authority` for scenario S1 against a real FalkorDB. Run `docker compose up -d falkordb` and `pytest tests/unit` before changing anything.
