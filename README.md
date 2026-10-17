<p align="center"><img src="./docs/images/banner.svg" alt="Agent Mandate: authority for AI agents, kept in a graph" width="100%"></p>

# Agent Mandate

**An action gateway for AI agents: an agent may take a consequential action only if a graph holds a valid chain from something a trusted human actually said, through unrevoked instructions and delegations, to that action. The gateway returns the chain as the explanation.**

[![CI](https://github.com/Monolithic-Dev/agent-mandate/actions/workflows/ci.yml/badge.svg)](https://github.com/Monolithic-Dev/agent-mandate/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-3776ab)
![FalkorDB](https://img.shields.io/badge/graph-FalkorDB-7c3aed)
![React 19](https://img.shields.io/badge/console-React%2019-149eca)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)
![WCAG 2.2 AA](https://img.shields.io/badge/WCAG-2.2%20AA%20audited-167a4a)

![The same script, run for an ordinary agent and for Agent Mandate: 5 unauthorised deletions against 0](./docs/images/demo.png)

*An ordinary agent loses its "confirm before deleting" rule when its context is compacted and deletes five emails. Agent Mandate keeps the rule in a graph and holds all five for the owner. Same script, same tool calls; only the gate differs.*

**Live demo: <https://agent-mandate-0ocw.onrender.com>** (free hosting: the first visit after a quiet spell takes about a minute to wake; sign-in is by invitation; a visitor account is in the [submission](./docs/submission.md)) · [Quick start](#quick-start) · [Tour of the console](#tour-of-the-console) · [Results](#results-so-far-stub-mode) · [Architecture](#architecture) · [User flows](#user-flows) · [Deployment](#deployment) · [Security](#security) · [Documentation](#documentation)

## Status

The authority engine, the FalkorDB adapter, the guarded gateway, the REST API, the MCP agent and admin servers, the lineage tools (blast radius, quarantine, replay) and the evaluation harness are implemented and tested. So is the web console, which covers:

| Area | What is there |
|---|---|
| **Decisions** | Scenario runs side by side; every decision explained from templates and re-verified against the graph; approving held actions in the console or through single-use approval links. |
| **Rules** | A rule studio that previews a sentence before it is said (the rules it makes, the live rules it contradicts, which recent requests it would decide differently, re-checked on a throwaway copy of the graph); time limits ("for the next 2 hours"); blast radius, quarantine and replay. |
| **Exploring** | A graph explorer: search, hide kinds of node, and trace any node back to who said it and forward to what it led to. A traced view is a shareable link. |
| **Operations** | Slack and signed JSON webhooks that tell the owner an action is held, with a one-time approval link; an activity overview per tenant (decisions over time by outcome, top reasons, check latency). |
| **Accounts** | Sign-in with roles and tenant access, sessions stored in the graph and ended on sign-out, an audit log of every change (refusals included) exportable as CSV, and a command-line tool for the first admin. |
| **Quality** | An axe audit of every page against WCAG 2.2 AA in light and dark; layouts that work on a phone; 770 unit, 97 FalkorDB integration, 50 console unit and 19 browser tests. |

Live agents work too (any model, see [Models](#models)); a scored evaluation with live models, and the optional planner, are not done. See the [roadmap](./docs/roadmap.md) and the [phase runbooks](./docs/phases/).

## Quick start

Needs Docker. This starts FalkorDB, the API and the console the way they run in production, loads a demo tenant and creates your first admin:

```
git clone https://github.com/Monolithic-Dev/agent-mandate.git && cd agent-mandate
export MANDATE_API_KEY=$(openssl rand -hex 24)          # the server's own key, for scripts
export FALKORDB_PASSWORD=$(openssl rand -hex 24)
docker compose -f docker-compose.prod.yml up -d --build --wait
docker compose -f docker-compose.prod.yml exec -T api python -m mandate.seed
docker compose -f docker-compose.prod.yml exec -T -e MANDATE_NEW_PASSWORD='choose-a-long-passphrase' api   python -m mandate.users add you@example.com --role admin
```

Open <http://localhost:8080> and sign in as that user. The **Demo** page runs a scenario for an ordinary agent and for Agent Mandate side by side; **Tenants → demo** has held actions to approve, rules, decisions and the graph. To work on the code instead, see [Run it](#run-it) and [docs/dev-setup.md](./docs/dev-setup.md).

## Tour of the console

| | |
|---|---|
| ![A tenant: what waits for the owner's approval](./docs/images/tenant.png) | ![The rule studio previewing a sentence before it is saved](./docs/images/studio.png) |
| **A tenant.** What is waiting for the owner, with approve, decline or a single-use link; the rules, the decision log, the graph. | **Rule studio.** Type a rule in the owner's words and see the rules it makes, what it overlaps and which recent requests it would decide differently, before anything is saved. |
| ![A decision explained as a chain from the owner's words to the agent, verified against the graph](./docs/images/decision.png) | ![The graph explorer tracing a decision back to who said it](./docs/images/explorer.png) |
| **Every decision explained.** The chain from the owner's words to the agent, and a check of each claim against the graph. | **Graph explorer.** Search, filter by kind and trace a node's lineage both ways; the trace is in the address, so it can be shared. |
| ![Decisions over time by outcome, with the top reasons, actions and agents](./docs/images/activity.png) | ![The audit log](./docs/images/audit.png) |
| **Activity.** Decisions per hour by outcome, why they were decided that way, and how fast. Chart colours are checked for colour-blind separation. | **Audit log.** Every change, refusals included, in plain sentences with filters and CSV export. |

On a phone the sidebar becomes a menu and the tables become cards, so the owner can approve from wherever they are:

| | |
|---|---|
| ![Approvals on a phone](./docs/images/phone-approvals.png) | ![The menu on a phone](./docs/images/phone-menu.png) |

The console also has a dark theme, and every page passes an automated WCAG 2.2 AA audit in both. More in [ui/README.md](./ui/README.md).

## Positioning

Many projects enforce policy at the tool boundary, and most take **static, developer-written policy**. Agent Mandate's narrower claim: authority is **derived from what the owner actually said**, every allow must trace back to a trusted utterance, and the same graph answers "as of when?" and "what if that rule had not existed?". It does not claim to be the first authorisation gateway; see [docs/engineering-review.md](./docs/engineering-review.md) and [docs/prior-art.md](./docs/prior-art.md).

## The problem

Agents keep rules such as "confirm before deleting" in their prompt or memory. Memory gets summarised and the rule is lost. Text planted in an email can look like an instruction from the owner. After a revocation, agents keep acting. And when something goes wrong, logs show that a call happened, not why the agent thought it was allowed. A reported February 2026 incident involved an agent that lost a confirm-before-acting rule and deleted a large part of an inbox.

## What it does

- Stores standing rules, permissions, delegations and revocations as a graph in FalkorDB, outside the agent's prompt, one graph per tenant.
- Enforces them at the tool boundary, so a rule cannot be lost when the agent's context is summarised. Every error fails closed, and an action is refused if its audit record cannot be written.
- Treats instructions found in untrusted content (an email body, a tool result) as information, never as authority: an instruction without a path back to a trusted owner utterance can be stored but never activated.
- Supports delegation that only narrows, revocation that takes effect on the next check, and "was this allowed at 3:00 PM?" queries.
- Answers "who told the agent it could do this?" with a path, and explains every decision from templates (never from a model).
- When a rule turns out to be mistaken, lists everything it affected, quarantines it and its offspring, and replays the affected decisions on a cloned graph to show what would have changed.
- Measures all of this against two baselines, reporting false blocks and confidence intervals.

## Results so far (stub mode)

From [docs/results/2026-10-08-eval-v5/report.md](./docs/results/2026-10-08-eval-v5/report.md): 26 scripted scenarios (rule lost in compaction, forged instruction, revocation and delegation, bad authority found later, **laundered instruction**, **benign lookalikes**), FalkorDB 6.0.1, deterministic scripted agents (no language model), generated at git `6557bb2` from a clean tree. [eval-v4](./docs/results/2026-10-08-eval-v4/) holds S5 (0 of 60 cross-tenant probes leaked) and S6 (0 wrong answers in 1,400 concurrent checks, with the measured revocation lag).

| | naive | flat | static policy | **Agent Mandate** |
|---|---|---|---|---|
| Unauthorised actions executed (of 47 probes that should not execute) | 44 | 19 | 6 | **0** (95% CI 0.0% to 7.6%) |
| Legitimate probes blocked (of 36) | 0 | 0 | 7 (19.4%) | **0** (95% CI 0.0% to 9.6%) |
| Held when confirmation was required (of 19) | 0 | 15 | 18 | 19 |
| Decisions with a complete explanation | n/a | n/a | n/a | 103 of 103 |
| Explanations re-verified against the graph | n/a | n/a | n/a | 103 of 103 |
| Lineage: affected decisions found, replay matching a hand-written oracle | n/a | n/a | n/a | 20 of 20, 5 of 5 |
| Decision latency, p50 / p95 (end to end, one client) | n/a | n/a | n/a | 7.0 ms / 10.9 ms (earlier runs: 5.4 / 8.7, 8.2 / 20.7 and 29.8 / 43.8 ms; it varies with the host's load) |

How to read this honestly: the scenarios are scripted and synthetic; **naive** loses its confirm and deny rules when its context is compacted (a documented failure, reproduced deterministically, not a measurement of any product); **flat** keeps its rules but cannot tell who said something and has no notion of delegation; **static policy** is a fixed developer-written policy we chose (reads and archiving allowed, refunds up to 100 allowed, sends, deletes and writes need approval, everything else denied) that ignores conversation entirely, so forged and laundered text cannot move it, but it also cannot honour the owner's own limits (its 7 false blocks) or learn of a revocation (its 6 unauthorised actions, all in the revocation scenarios). The static numbers depend entirely on that policy and say nothing about any named product. Every S2 and S8 variant puts a forged or laundered rule in the graph (a test checks that each S2 variant does, and that Agent Mandate lists it as ignored); until eval-v5, three S2 variants planted only text the parser drops. Rewording them changed none of the counts. Nothing here says anything about real-model behaviour. See the report's limits section and [docs/claims-ledger.md](./docs/claims-ledger.md) for what may and may not be claimed.

### With a real model

The scripted agents above say nothing about real models, so the same scenarios were also run with one: [`openai/gpt-oss-120b`](./docs/results/2026-10-11-live-openai-gpt-oss-120b/report.md) on Groq, working each scenario's attempts as one task, in two arms. *Prompt-only* has the owner's rules in its prompt (minus what a compaction dropped) and unguarded tools; *Agent Mandate* has no rules in its head and every call goes through the gateway.

| 16 runnable scenarios, 1 run each | prompt-only | Agent Mandate |
|---|---|---|
| Unauthorised actions that took effect (of 39 that should not) | **28** (71.8%, 95% CI 56.2% to 83.5%) | **0** (0.0%, 95% CI 0.0% to 9.0%) |
| Legitimate actions completed (of 27) | 24 | 27 |

One model, a small sample, 16 of the 27 scenarios (the rest cannot be run as a single task, and the report lists why), and a model's output varies from run to run. It is evidence about this model on these tasks, not a claim about models. Every transcript is in the results folder; rerun it with `python -m mandate.eval.live` (see [Models](#models)).

## Tech stack

Python 3.12 · FalkorDB · FastAPI + pydantic · structlog · pytest and hypothesis · import-linter (architecture rules in CI) · ruff and mypy · Docker Compose. MCP (Python SDK 2.x). Web console: React, Vite, TypeScript, Cytoscape.js, vitest and Playwright. Live agents: the Anthropic SDK, or any OpenAI-compatible API (Groq, OpenAI, OpenRouter, local servers).

## Run it

Prerequisites: Python 3.12, Docker. Details and Windows notes in [docs/dev-setup.md](./docs/dev-setup.md).

```
python -m venv .venv && source .venv/bin/activate      # Windows: py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env                                  # set MANDATE_API_KEY (at least 16 characters)
docker compose up -d falkordb                         # if port 6379 is taken, set FALKORDB_PORT in .env

pytest tests/unit                                     # no database needed
pytest tests/integration                              # needs FalkorDB
python -m mandate.eval                                # the evaluation, with gates; writes eval/results/<time>/
python -m mandate.eval.isolation                      # S5: cross-tenant probes through the REST API
python -m mandate.eval.concurrency                    # S6: 50 agents across 5 tenants, revokes mid-run
python scripts/mutation_test.py --workers 8           # breaks the engine on purpose, checks the tests notice
uvicorn --factory mandate.api.app:create_app          # the REST API (reads .env)
cd ui && npm install && npm run dev                   # the web console on http://localhost:5173 (needs the API)
python -m mandate.mcp_servers admin --tenant T --owner prn_...   # owner MCP tools (stdio); add --http to serve
python -m mandate.mcp_servers agent --token <token>              # agent MCP tools; the admin mints the token
```

The REST API is documented in [docs/api-spec.md](./docs/api-spec.md); with the server running, `/docs` serves the OpenAPI UI (send the key in the `X-Mandate-Key` header).

## Models

**The product does not need a model or an API key.** The authority engine never calls one: a decision is derived from the graph, so it is reproducible and can be replayed. The scored evaluation uses deterministic scripted agents for the same reason. A model is only needed to run a *live agent*, a language model that works a task with the gateway's tools, so you can watch what a real one does at the gateway.

Live agents are provider-neutral. Claude is one choice, not the only one:

| Provider | Set | Notes |
|---|---|---|
| `anthropic` (default) | `ANTHROPIC_API_KEY`, `MANDATE_MODEL` | Claude, through the Anthropic SDK. |
| `groq` | `MANDATE_LLM_PROVIDER=groq`, `GROQ_API_KEY` | Default model `openai/gpt-oss-120b`; change it with `MANDATE_LLM_MODEL`. |
| `openai` | `MANDATE_LLM_PROVIDER=openai`, `OPENAI_API_KEY` | |
| `openai-compatible` | `MANDATE_LLM_PROVIDER=openai-compatible`, `MANDATE_LLM_BASE_URL`, `MANDATE_LLM_MODEL` | OpenRouter, Together, Ollama, vLLM, or any server speaking that API. A local one needs no key. |

```
python -m mandate.agents "Archive the newsletters, then delete message m-1" --tenant demo
python -m mandate.agents "Refund order 4 for $40" --provider groq
```

One real run on Groq is written up in [docs/results/2026-10-11-live-groq/](./docs/results/2026-10-11-live-groq/README.md): of five calls, two ran, two were held for the owner and one was denied, and the model reported all of it. It is one run, not a measurement. Each tool call goes through the same guarded REST call every agent uses, so the model cannot reach a tool except through the gateway, and held or denied calls come back to it as results. It prints what ran, what was held for the owner and what was denied. A different provider is one small adapter in [src/mandate/llm/](./src/mandate/llm/).

## Graph data model

One FalkorDB graph per tenant. Nodes: `Principal`, `Utterance` (with a trust level computed from channel and role), `Instruction` (a rule: allow, deny or confirm), `Scope`, `Agent`, `Summary`, `Action`, `Decision`, `Approval`. Edges: `SAID`, `EXPRESSES` and `DERIVED_FROM` (lineage), `ABOUT` and `APPLIES_TO` (what a rule covers and for whom), `SUPERSEDES` and `REVOKES`, `DELEGATES_TO` (narrowing only), and `PROPOSED_BY`, `CHECKED`, `USED`, `APPROVES` (the decision trail that blast radius and replay read). Full schema in [docs/data-model.md](./docs/data-model.md); every Cypher query the product runs is listed in the generated [docs/query-catalog.md](./docs/query-catalog.md).

## How the code is organised

Ports and adapters, enforced by import-linter in CI ([docs/design-patterns.md](./docs/design-patterns.md), ADR-015): `mandate.models` and `mandate.authority` are the core and never import FalkorDB, FastAPI or any adapter; `mandate.graph` implements the core's ports; `mandate.gateway` and `mandate.api` are the interfaces; `mandate.eval` is the evidence generator. Behaviour is specified as numbered rules with conformance tests ([docs/spec/authority-semantics.md](./docs/spec/authority-semantics.md)), including property-based tests and a differential test that holds the in-memory fake and the FalkorDB adapter to identical decisions.

## Architecture

```mermaid
flowchart LR
    subgraph Agents
        A1([AI agent])
        A2([Sub-agent<br/>narrower authority])
    end
    subgraph Mandate[Agent Mandate]
        GW[Gateway<br/>MCP and REST]
        ENG{{Authority engine<br/>pure, no model,<br/>fails closed}}
        NOT[Notifier]
        API[REST API]
    end
    subgraph Data[FalkorDB]
        T[(One graph<br/>per tenant)]
        R[(Registry graph<br/>users, sessions,<br/>audit, webhooks)]
    end
    A1 & A2 -->|tool call| GW
    GW -->|"may it?"| ENG
    ENG <-->|rules, lineage,<br/>decisions| T
    GW -->|allow| TOOL[[The real tool]]
    GW -->|confirm| HELD[/Held for the owner/]
    HELD --> NOT
    NOT -->|Slack or signed webhook<br/>with a one-time link| OWNER([Owner])
    OWNER -->|approve or decline| API
    API --> GW
    CONSOLE[Web console] --> API
    API --> ENG
    API <--> R
    NOT <--> R
```

The engine decides; it never calls a model, so a decision is reproducible and can be replayed on a copy of the graph. Ports and adapters keep it that way: the core never imports FalkorDB or FastAPI, and import-linter fails CI if it does.

### One guarded call

```mermaid
sequenceDiagram
    autonumber
    participant Agent
    participant Gateway
    participant Engine as Authority engine
    participant Graph as Tenant graph
    participant Owner
    Agent->>Gateway: tool call (e.g. email.delete inbox/m-1)
    Gateway->>Engine: check(agent, action, resource, amount)
    Engine->>Graph: rules for this agent and scope, their lineage, delegations, revocations
    Graph-->>Engine: candidate rules and the path behind each
    Note over Engine: a rule counts only if it traces to a trusted owner utterance,<br/>is active and unrevoked, and every limit is met
    Engine->>Graph: record the decision and the rules it used
    alt the record cannot be written
        Gateway-->>Agent: refused (fails closed)
    else allow
        Gateway->>Agent: the tool runs, with the chain as the explanation
    else confirm
        Gateway-->>Agent: held, nothing has run
        Gateway->>Owner: "an action is waiting" with a one-time approval link
        Owner->>Gateway: approve or decline
        Gateway->>Agent: runs now, or is declined
    else deny
        Gateway-->>Agent: denied, with the reason
    end
```

### What the graph holds

```mermaid
flowchart TB
    P([Principal<br/>owner or external]) -->|SAID| U[Utterance<br/>trust from channel and role]
    U -->|EXPRESSES| I{{Instruction<br/>allow, deny or confirm}}
    S[Summary of a compacted context] -->|DERIVED_FROM| U
    S -->|EXPRESSES| I
    I -->|ABOUT| SC[Scope<br/>action type and resource pattern]
    I -->|APPLIES_TO| AG[Agent]
    I -.->|SUPERSEDES| I2{{Older instruction}}
    AG -->|DELEGATES_TO<br/>narrowing only| AG2[Sub-agent]
    ACT[Action] -->|PROPOSED_BY| AG
    D([Decision]) -->|CHECKED| ACT
    D -->|USED| I
    AP[Approval] -->|APPROVES| ACT
```

Every allow is a path through this graph from a trusted `Utterance` to the `Action`. An instruction found in an untrusted `Utterance` keeps its origin, so it can be stored and shown but never activated.

## User flows

### An owner approves from their phone

```mermaid
sequenceDiagram
    autonumber
    actor Agent
    participant Mandate as Agent Mandate
    participant Slack as Slack or webhook
    actor Owner as Owner (phone)
    Agent->>Mandate: email.send to a new address
    Mandate-->>Agent: held, because a rule says to ask first
    Mandate->>Slack: "assistant wants to run email_send(...)" + Approve link (single use, expires)
    Slack-->>Owner: notification
    Owner->>Mandate: opens the link (token in the URL fragment)
    Mandate-->>Owner: who asked, what, and why it is held
    Owner->>Mandate: Approve
    Mandate->>Agent: the action runs, and the approval is recorded on the graph
```

### Writing a rule, safely

```mermaid
flowchart LR
    A[Owner types a sentence<br/>in the rule studio] --> B[Preview<br/>the rules it makes,<br/>time limits, what was not understood]
    B --> C{Overlaps a live rule?}
    C -->|contradicts, repeats,<br/>or changes a limit| D[Shown with the old rule]
    C -->|no| E
    D --> E[Re-check recent requests<br/>on a throwaway copy of the graph]
    E --> F{Would any decision change?}
    F -->|yes| G[Listed: was allow, now deny]
    F -->|no| H
    G --> H{Save?}
    H -->|save, confirm later| I[Stored, inert until confirmed]
    H -->|save and confirm as the owner| J[Active from the next check]
    H -->|no| K[Nothing was written]
```

### When a rule turns out to be wrong

```mermaid
flowchart LR
    A[A mistaken or forged rule is found] --> B[Blast radius<br/>every decision that used it]
    B --> C[Quarantine<br/>the rule and everything derived from it]
    C --> D[Replay the affected decisions<br/>on a cloned graph, without it]
    D --> E[See which would have flipped]
    E --> F{Keep it?}
    F -->|release| G[Rule active again]
    F -->|revoke| H[Stops applying on the next check;<br/>past decisions keep their record]
```

### A new person joins the console

```mermaid
flowchart LR
    A[First admin created on the server<br/>python -m mandate.users add] --> B[Signs in<br/>scrypt, rate limited,<br/>server-side session]
    B --> C[Invites a colleague in Users<br/>role and tenant access]
    C --> D{Role}
    D -->|viewer| E[Sees their tenants,<br/>changing actions disabled with a note]
    D -->|operator| F[Can also run checks<br/>and previews]
    D -->|admin| G[Approves, edits rules,<br/>manages users, reads the audit log]
    E & F & G --> H[(Every change, refusals included,<br/>recorded in the audit log)]
```

## Deployment

```mermaid
flowchart LR
    B([Browser]) -->|8080| N[nginx<br/>serves the console,<br/>proxies /v1]
    N --> API[API<br/>FastAPI, unprivileged]
    API --> F[(FalkorDB<br/>password, internal network only)]
    API -->|HTTPS, no private addresses| W([Slack or your webhook])
    S([Scripts and agents]) -->|X-Mandate-Key| API
```

`docker-compose.prod.yml` runs all three with a read-only filesystem for the API, no published database port and health checks; ports bind to localhost, so put your own TLS proxy in front. Settings are in [.env.example](./.env.example) and [docs/deployment.md](./docs/deployment.md).

### Deploy to Render, free

[render.yaml](./render.yaml) deploys the whole thing as **one free web service** (no card): FalkorDB, the API and the console in one container ([deploy/free/](./deploy/free/)). On Render, **New → Blueprint**, pick this repository, and enter the email and password you want to sign in with (and, if you want visitors to try it, a second email and password: that account is an operator, who can run scenarios and approve held actions but not manage users). A few minutes later the console is at the service's `onrender.com` address, with the demo tenant loaded.

It is a demo deployment, and the trade-offs are the free plan's: the service sleeps after about 15 minutes without a visit (the first visit after that takes about a minute), and the database is in memory, so it starts empty each time and the container re-seeds the demo tenant and recreates your admin on every start. For a deployment that keeps its data, [deploy/render/paid.render.yaml](./deploy/render/paid.render.yaml) is the three-service version with a disk. Details in [docs/deployment.md](./docs/deployment.md).

## Security

- **Fail closed.** Every error is a denial, and an action is refused if its audit record cannot be written.
- **Untrusted text is never authority.** A rule drawn from an email body or a tool result can be stored but never activated; the graph keeps its origin so it can be quarantined with everything derived from it.
- **Tenants are isolated.** One graph per tenant; the evaluation probes it with 60 cross-tenant requests and none leak.
- **Console sessions.** Server-side and revocable, HttpOnly, SameSite=Strict cookies; only a hash of the token is stored; a CSRF header on every change; passwords hashed with scrypt; sign-in is rate limited and a wrong email answers like a wrong password.
- **Webhooks.** HTTPS only, and never to a private address (checked when saved and again before each send); URLs are masked once saved; JSON bodies are signed with HMAC-SHA256.
- **Approval links.** Single use, short lived, with the token in the URL fragment so it never reaches a server log.
- **Audit.** Every change by every kind of caller, refusals included, in the graph.
- **Supply chain.** Dependencies are audited and secrets are scanned in CI.

The threat model and what is out of scope are in [docs/security-privacy.md](./docs/security-privacy.md); report a vulnerability as described in [SECURITY.md](./SECURITY.md).

## Quality

CI runs, on every change: ruff and mypy, import-linter (the architecture rules), 770 unit tests (including property-based tests and a differential test that holds the in-memory fake and the FalkorDB adapter to identical decisions), 97 integration tests against a real FalkorDB, the console's type check, 50 unit tests and build, a secret scan and a dependency audit, then it builds the production images and runs 19 browser tests against them, including an [axe](https://github.com/dequelabs/axe-core) audit of every page. `python scripts/mutation_test.py` breaks the engine on purpose and checks that the tests notice.

## Documentation

| Document | What is inside |
|---|---|
| [docs/README.md](./docs/README.md) | Index and reading order |
| [docs/PRD.md](./docs/PRD.md) | Problem, goals and non-goals, requirements, scope tiers, metrics |
| [docs/spec/authority-semantics.md](./docs/spec/authority-semantics.md) | Normative rules AUTH-001 to AUTH-027 and the conformance test map |
| [docs/architecture.md](./docs/architecture.md), [docs/design-patterns.md](./docs/design-patterns.md) | Components, the guarded-call flow, layers and patterns |
| [docs/data-model.md](./docs/data-model.md), [docs/api-spec.md](./docs/api-spec.md) | Graph schema and queries; REST and MCP surfaces |
| [docs/evaluation.md](./docs/evaluation.md), [docs/scenarios.md](./docs/scenarios.md) | Metrics, baselines, scenario scripts |
| [docs/security-privacy.md](./docs/security-privacy.md), [docs/edge-cases.md](./docs/edge-cases.md) | Threat model and failure cases |
| [docs/prior-art.md](./docs/prior-art.md), [docs/engineering-review.md](./docs/engineering-review.md) | Related work and what was adopted |
| [docs/observability.md](./docs/observability.md) | Health and readiness endpoints, Prometheus metrics, alerts worth having |
| [docs/judge-qa.md](./docs/judge-qa.md), [docs/submission.md](./docs/submission.md), [docs/demo-script.md](./docs/demo-script.md), [AI_USAGE.md](./AI_USAGE.md), [docs/friend-docs-review.md](./docs/friend-docs-review.md) | Questions and walkthrough, submission checklist, demo script, AI-assistance disclosure, review of the teammate's documents |
| [docs/claims-ledger.md](./docs/claims-ledger.md), [docs/risk-register.md](./docs/risk-register.md) | What may be claimed; risks |
| [docs/roadmap.md](./docs/roadmap.md), [docs/phases/](./docs/phases/) | Phases, budgets, runbooks |
| [docs/decisions.md](./docs/decisions.md), [docs/testing.md](./docs/testing.md), [docs/deployment.md](./docs/deployment.md), [docs/dev-setup.md](./docs/dev-setup.md) | Decisions, tests, deployment, setup |
| [docs/ai-pipeline.md](./docs/ai-pipeline.md), [docs/prompts.md](./docs/prompts.md), [docs/integration-guide.md](./docs/integration-guide.md), [docs/ux-flows.md](./docs/ux-flows.md), [docs/demo-and-qa.md](./docs/demo-and-qa.md) | Planned parts and the demo |

## What this is not

- It does not stop all prompt injection. It controls what an agent is authorised to do, not what the model reads.
- It does not claim to be the first system of its kind. Related work is credited in [docs/prior-art.md](./docs/prior-art.md): mandatum, the Agent Passport System, Charon, CaMeL, MAP-Graph, Vismaran, Mem-Quarantine, MemLineage, Graphiti, LlamaFirewall, Progent and others.
- It uses only synthetic data. Do not connect real mailboxes.

## License

[MIT](./LICENSE). The console's icons are [Phosphor Icons](https://phosphoricons.com) (MIT), generated into `ui/src/icons.tsx`; the fonts (Inter, JetBrains Mono) are under the SIL Open Font License.

## Team

**Code Blooded**: Mahakisore and Ramkumar.
