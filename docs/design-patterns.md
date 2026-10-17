# Design Patterns and Code Standards

Status: v1.0 · Last updated 2026-10-06. How the code is organised and why. Complements [architecture.md](./architecture.md) (what the components are) and [decisions.md](./decisions.md) ADR-015 (the decision). The rules here are enforced by tools where possible, not by good intentions.

## 1. Layers and the dependency rule

Ports and adapters (hexagonal architecture), expressed inside the existing packages so docs and code share names.

```
            interfaces (adapters, outside)                 core (inside)                   infrastructure (adapters, outside)
   +--------------------------------------+     +-------------------------------+     +-----------------------------------+
   | mandate.api      REST (FastAPI)      |     | mandate.models   entities     |     | mandate.graph    FalkorDB store   |
   | mandate.gateway  MCP servers, guard  | --> | mandate.authority rules, PDP, | <-- |   implements authority.ports      |
   | mandate.eval     runner, reports     |     |   use cases, ports (Protocols)|     | mandate.agents   LLM clients      |
   +--------------------------------------+     +-------------------------------+     +-----------------------------------+
```

**Dependency rule:** source-code dependencies point inward. The core (`mandate.models`, `mandate.authority`) never imports an adapter or an I/O framework (`falkordb`, `fastapi`, `anthropic`, `mcp`, `httpx`). The core declares what it needs as `Protocol` classes (ports) in `mandate/authority/ports.py`; `mandate.graph` implements them. Agents reach the system only through the gateway, never the graph or the engine.

Enforced in CI by `lint-imports` (import-linter contracts in `pyproject.toml`). A violation fails the build.

## 2. Patterns in use, and where

| Pattern | Where | Why |
|---|---|---|
| **Ports and adapters** | `authority/ports.py` (ports), `graph/store.py` (adapter), `gateway`, `api` | Core logic is testable with in-memory fakes and independent of FalkorDB and FastAPI |
| **Repository / store** | `AuthorityStore` port, `FalkorAuthorityStore` adapter | One place for persistence details; queries live in `.cypher` files, not in logic |
| **Strategy** | `PolicyDecisionPoint` (deterministic now, Cedar-backed later), `LLMClient` (Anthropic, scripted), agent kinds (`naive`, `flat`, `mandate`) | Swap behaviour behind a stable interface; evaluation compares strategies |
| **Factory** | `create_app()`, `make_llm(settings)`, `make_agent(kind, ...)` | Construct wired objects at the edge; no wiring inside core code |
| **Dependency injection (constructor injection)** | Use cases receive a store, a clock and an id factory; FastAPI uses `Depends` only in `api/deps.py` | No hidden globals; tests inject fakes |
| **Command / use case** | One function or class per use case with a typed request and result (`CheckAuthority`, `IngestUtterance`, `ConfirmInstruction`, `Revoke`, `BlastRadius`, `ReplayWithout`) | Interfaces stay thin; behaviour is reusable by REST, MCP and the evaluator |
| **Pipeline of filters** | Candidate selection in `check_authority` (validity, revocation, supersession, quarantine, scope, lineage) | Each rule is small, named after a spec rule ID, and testable alone |
| **Value objects (immutable)** | Frozen pydantic models for `Decision`, `Scope`, `CheckRequest` | Safe to pass around and to record |
| **Null object** | `NullTracer` when OpenTelemetry is not installed | No `if tracer:` branches |
| **Retry with backoff and timeout** | LLM client, `GRAPH.COPY`, graph connect | Bounded, observable failure handling |
| **Fail closed** | `check_authority`, gateway guard | Errors never widen authority (ADR-011) |
| **Event stream** | Run events for the UI (SSE) | Decouples runner from presentation |

Patterns not used on purpose: inheritance hierarchies for domain entities, a generic "service locator", active-record models, global mutable state, and an ORM (the graph is queried with fixed Cypher).

## 3. Code standards

- **Typing:** every function is typed (`disallow_untyped_defs`); mypy is strict for the core. Public data crosses boundaries as pydantic models, not dicts.
- **Purity:** decision logic is pure functions of an input snapshot; I/O happens before and after. This is what makes microsecond latency measurable and tests fast.
- **Time and ids** come from `Clock` and `new_id`, injected, never `time.time()` inline in logic.
- **Errors:** raise subclasses of `MandateError` (`mandate/errors.py`); interfaces translate them to HTTP or MCP responses. No bare `except`; the only broad catch is the fail-closed wrapper in the check path, and it logs.
- **Configuration:** `Settings` is created at the edge and passed down. Core code never reads the environment.
- **Queries:** only files in `graph/queries/` can run; names are validated; all values are parameters (ADR on injection safety in [security-privacy.md](./security-privacy.md)).
- **Logging:** structured, with `tenant_id`, `agent_id`, `decision_id`; secrets redacted by key name; never log request bodies or utterance text in full.
- **Naming:** see [project-structure.md](./project-structure.md) section 2. Functions are verbs, entities are nouns, spec rules are cited as `AUTH-nnn` in docstrings and test names.
- **Tests:** unit tests use in-memory fakes of the ports; integration tests use a real FalkorDB; scenario tests run the harness. See [testing.md](./testing.md).
- **Commits and PRs:** Conventional Commits; one feature per branch; docs change with code ([../CONTRIBUTING.md](../CONTRIBUTING.md)).

## 4. How the rules are enforced

| Rule | Tool |
|---|---|
| Layering and forbidden imports | import-linter (`lint-imports`), CI job `architecture` |
| Style, imports, simple bugs | ruff (`check` and `format --check`), CI job `lint` |
| Types | mypy, CI job `typecheck` |
| Behaviour and spec rules | pytest, hypothesis; conformance map in [spec/authority-semantics.md](./spec/authority-semantics.md) |
| Secrets | pre-commit gitleaks locally; CI scan in Phase 9 |
| Docs match code | PR template checklist; reviewed in every PR |

## 5. Adding a feature (checklist)

1. Name the spec rule or requirement it implements.
2. Put pure logic in `authority` or `models`; if it needs data, add a method to a port, not an import of an adapter.
3. Implement the adapter in `graph` (or the interface in `api` or `gateway`).
4. Write the unit test against a fake, then the integration test.
5. Update docs in the same PR; run `scripts/dev.ps1 check`.
