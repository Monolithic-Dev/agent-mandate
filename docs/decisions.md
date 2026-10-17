# Architecture Decision Records

Status: v1.0 · Last updated 2026-10-06. Short records of decisions that other documents depend on. New decisions get the next number; superseded ones are marked, never deleted.

## ADR-001: The decision is made by deterministic code, not the LLM
**Status:** accepted. **Context:** an LLM judge can be steered by text, is not reproducible and cannot be tested exhaustively. **Decision:** `authority.check` decides; the LLM only proposes actions and (optionally) proposes candidate rules. **Consequences:** reproducible evaluation; a smaller attack surface; the model cannot grant authority.

## ADR-002: Use FalkorDB, and say honestly why
**Status:** accepted. **Context:** relational stores with recursive queries can model authority chains (the PRD admits this). **Decision:** use FalkorDB because the project also needs lineage closure for blast radius, graph cloning with `GRAPH.COPY` for replay, one isolated graph per tenant, and (stretch) max-flow. **Consequences:** the "RBAC with extra steps" critique must be answered with these capabilities and with measurements, not assertions.

## ADR-003: Anthropic API behind a provider-neutral `LLMClient`; deterministic `ScriptedLLM` for scored runs
**Status:** accepted. **Context:** reproducible numbers and low cost matter. **Decision:** live provider is Anthropic (`anthropic` SDK, model id from `MANDATE_MODEL`); evaluation uses scripted steps; live runs are a separate, labelled sample. **Consequences:** swapping providers is a one-file change; live results never mix with scored results.

## ADR-004: React + Vite + TypeScript + Cytoscape.js for the UI
**Status:** accepted. **Context:** the core demo is a highlighted path on a graph. **Decision:** Cytoscape.js for rendering, React for state. **Consequences:** a small set of components; a "show as table" alternative for accessibility.

## ADR-005: Two MCP profiles, agent and admin
**Status:** accepted. **Context:** if an agent could call authority-changing tools, a forged rule could authorise itself. **Decision:** the agent profile exposes only guarded sandbox tools and `explain_decision`; admin tools are on a separate mount and token. **Consequences:** agent identity comes from its token; two mounts to configure.

## ADR-006: Three-valued lineage trust (`trusted`, `mixed`, `untrusted`)
**Status:** accepted. **Context:** summaries can blend owner and untrusted text. **Decision:** `untrusted` is ignored; `mixed` can yield only `confirm`; `trusted` can yield any effect. **Consequences:** laundering through summaries is blocked at the cost of extra confirmations, measured by the false-block metric.

## ADR-007: Precedence is "most recently activated wins; deny, then confirm, then allow on ties"
**Status:** accepted. **Context:** owners change their minds, and rules need a simple, explainable order. **Decision:** as stated, with default deny. **Consequences:** a later broad deny overrides an earlier narrow allow; documented and tested in both orders.

## ADR-008: Cut erasure-with-receipt and PageRank trust from v1
**Status:** accepted. **Context:** overlap with existing projects (Vismaran, Graphiti) and weak justification for PageRank. **Decision:** out of scope. **Consequences:** the project stays focused on authority, lineage and replay.

## ADR-009: The revocation planner is a gated stretch
**Status:** accepted. **Context:** `algo.maxFlow` returns flow values and flow-carrying edges, not the minimum cut; a simple chain needs no planner. **Decision:** build only if (a) the core and should-tier items pass, (b) a redundancy scenario (S7) exists, and (c) `algo.maxFlow` is verified on the pinned FalkorDB version. The cut is derived in application code and the "legitimate actions survive" guarantee comes from re-checking on a `GRAPH.COPY` clone. **Consequences:** no schedule dependency on the planner.

## ADR-010: Git workflow
**Status:** accepted. **Decision:** `main` is protected by convention; every change is a feature branch (`type/slug`) merged by pull request; Conventional Commit messages; commits are authored by the developer's own git identity with no co-author trailers. **Consequences:** a reviewable history; each document and phase arrives as its own PR.

## ADR-012: Put the decision engine behind a `PolicyDecisionPoint` interface
**Status:** accepted. **Context:** Cedar and OPA are the standard policy languages and are analysable; Cedar-based MCP enforcers exist. Our instructions are produced from sentences and need provenance, lifecycle and as-of semantics that those languages do not model directly. **Decision:** define `authority/pdp.py` with a `PolicyDecisionPoint` protocol (`decide(request, snapshot) -> Decision`) and implement our own deterministic engine for v1. A Cedar-backed implementation (compiling active, trusted instructions into a policy set) is future work. **Consequences:** the engine is replaceable and testable against the same conformance suite; no dependency on Cedar in v1.

## ADR-013: Optional external validation on AgentDojo
**Status:** accepted as optional and gated. **Context:** credible agent-defence work reports on public benchmarks; our scenarios are self-written. **Decision:** Phase 8b wraps an AgentDojo pipeline with the engine on a small, seeded subset, reports benign utility, utility under attack and attack success rate with Wilson intervals, and states that it tests the engine plus a scope-synthesis step. **Consequences:** extra cost and time; skipped without penalty if the gate fails; claims limited to what was run.

## ADR-014: Spec-first semantics with conformance tests
**Status:** accepted. **Context:** the strongest comparable projects publish numbered, testable rules (RFC 2119 style) and conformance suites. **Decision:** [spec/authority-semantics.md](./spec/authority-semantics.md) is normative; every rule has a test; behaviour changes name the rule IDs they touch. **Consequences:** more up-front writing; far less ambiguity during implementation and review.

## ADR-011: Fail closed
**Status:** accepted. **Decision:** any error in the check path returns `deny` with reason `check_error`. **Consequences:** an outage blocks actions instead of allowing them.

## ADR-015: Ports and adapters inside the existing packages, enforced by import-linter
**Status:** accepted. **Context:** the project is meant to be built and reviewed like production software; a flat set of modules lets I/O leak into decision logic, which makes the core hard to test and the claims hard to defend. **Decision:** keep the package names used across the docs, but treat them as layers: `mandate.models` and `mandate.authority` are the core and may not import `mandate.graph`, `mandate.api`, `mandate.gateway`, `mandate.agents`, `mandate.eval` or I/O frameworks; the core declares `Protocol` ports in `mandate/authority/ports.py`; `mandate.graph` implements them; agents may not import the graph or the engine. Contracts are in `pyproject.toml` and checked by `lint-imports` in CI. See [design-patterns.md](./design-patterns.md). **Consequences:** a few extra files (ports, store adapter), fakes for unit tests, and phase runbooks 2 and 3 describe the store and ports instead of calling the graph client from the engine.
