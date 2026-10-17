# Documentation Index

Status: v1.0 · Last updated 2026-10-06. Start here. The documents are a specification: the code is built to them, and they are updated in the same pull request as any code that changes a name, rule or endpoint ([../CONTRIBUTING.md](../CONTRIBUTING.md)).

## Reading order

1. [PRD.md](./PRD.md): what and why.
2. [prior-art.md](./prior-art.md) and [engineering-review.md](./engineering-review.md): what already exists, what we adopt, and what is claimed.
3. [data-model.md](./data-model.md) and [spec/authority-semantics.md](./spec/authority-semantics.md): the graph, and the numbered rules for `check_authority`; every other document uses these names.
4. [architecture.md](./architecture.md): components and the guarded-call flow.
5. [api-spec.md](./api-spec.md): REST endpoints and MCP tools.
6. [ai-pipeline.md](./ai-pipeline.md) and [prompts.md](./prompts.md): agents, parser, extractor, prompts.
7. [scenarios.md](./scenarios.md) and [evaluation.md](./evaluation.md): the acceptance tests and metrics.
8. [security-privacy.md](./security-privacy.md) and [edge-cases.md](./edge-cases.md): threats and failure cases.
9. [project-structure.md](./project-structure.md), [dev-setup.md](./dev-setup.md), [deployment.md](./deployment.md): building and running.
10. [roadmap.md](./roadmap.md), [phases/](./phases/): the build plan.
11. [testing.md](./testing.md): test strategy and checklists.

## All documents

| Document | Purpose | Audience |
|---|---|---|
| [PRD.md](./PRD.md) | Problem, goals, scope tiers, requirements, metrics | everyone |
| [architecture.md](./architecture.md) | Components, flows, trade-offs | engineers |
| [project-structure.md](./project-structure.md) | Repo layout, naming, where to start | engineers |
| [data-model.md](./data-model.md) | Graph schema, authority rules, Cypher queries | engineers |
| [api-spec.md](./api-spec.md) | REST and MCP surfaces | engineers, integrators |
| [ai-pipeline.md](./ai-pipeline.md) | Agents, parser, extractor, guardrails | AI engineers |
| [prompts.md](./prompts.md) | Prompt catalog and change process | AI engineers |
| [evaluation.md](./evaluation.md) | Metrics, baselines, reporting rules | engineers, reviewers |
| [scenarios.md](./scenarios.md) | Concrete scenario scripts and oracles | engineers, reviewers |
| [security-privacy.md](./security-privacy.md) | Threat model, auth, secrets | engineers, reviewers |
| [edge-cases.md](./edge-cases.md) | Failure cases and fixes | engineers |
| [deployment.md](./deployment.md) | Docker, CI, configuration, rollback | engineers |
| [dev-setup.md](./dev-setup.md) | Environment setup, tasks, troubleshooting | contributors |
| [integration-guide.md](./integration-guide.md) | Putting the gateway in front of your agent (planned interface) | integrators |
| [ux-flows.md](./ux-flows.md) | UI flows, accessibility, demo polish | frontend, reviewers |
| [roadmap.md](./roadmap.md) | Phases, budgets, MVP, demo script | everyone |
| [testing.md](./testing.md) | Test layers, named cases, QA checklist | engineers |
| [decisions.md](./decisions.md) | Architecture decision records | engineers |
| [risk-register.md](./risk-register.md) | Risks, mitigations, review log | owner |
| [claims-ledger.md](./claims-ledger.md) | What may be claimed and the evidence needed | everyone who writes about the project |
| [demo-and-qa.md](./demo-and-qa.md) | Demo checklist and tough questions with answers | presenter |
| [engineering-review.md](./engineering-review.md) | Review of reference projects; adopted practices and plan changes | everyone |
| [design-patterns.md](./design-patterns.md) | Layers, patterns, code standards and how they are enforced | engineers |
| [spec/authority-semantics.md](./spec/authority-semantics.md) | Normative rules AUTH-001 to AUTH-027 and the conformance test map | engineers, reviewers |
| [phases/](./phases/) | Nine phase runbooks plus the optional phase 8b | the person building |
| [results/](./results/) | Committed evaluation reports (after Phase 9) | reviewers |

## Conventions used across documents

- Time is epoch milliseconds; ids are `<prefix>_<26 characters>`; property names are `snake_case`; labels `PascalCase`; relationships `UPPER_SNAKE`.
- Reason codes: `authorized`, `confirm_rule`, `mixed_lineage`, `explicit_deny`, `authority_revoked`, `constraint_not_met`, `no_authority_path`, `check_error`.
- Scenario ids: `S<n>_<slug>_v<variant>`.
- "Stub" means the deterministic scripted LLM; "live" means a real model. Results are always labelled.

## Status of the documents

| State | Documents |
|---|---|
| Written and merged | all of the above |
| Verified against code | none yet (no implementation); each phase file lists what to verify |
| Contains unverified assumptions | `data-model.md` queries (Phase 2), `api-spec.md` MCP profiles (Phase 4), `phase-8` max-flow call (Phase 8), `integration-guide.md` client config |

## Known open items

1. Product name check ("Agent Mandate") before any public announcement.
2. Licence choice (none added yet; it is the owner's decision).
3. Organisers' written answer on pre-existing work, if the project will be submitted to Graph Hacks.
4. LLM provider budget for live runs.
