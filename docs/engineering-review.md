# Engineering Review: What the Best Reference Projects Do, and What We Change

Status: v1.0 · Last updated 2026-10-06. A design review of the closest open-source projects and papers, written the way a staff engineer would before committing to a build: what exists, what practices make the strong projects credible, where the honest gap is, and the concrete changes to our plan. **Findings come from repository pages and search summaries read on 2026-10-06, not from reading source code; verify details before quoting them publicly.**

## 1. Method

1. Search GitHub and the literature for projects that sit in the same place: agent action gateways, policy engines for agents, information-flow control, guardrail frameworks, agent security benchmarks.
2. Read the README or paper summary of the closest ones for architecture, policy model, evaluation design, testing practice, documentation habits and maturity.
3. Extract practices to adopt, gaps we can honestly fill, and things we should not build.
4. Change the plan only where the evidence supports it, and record each change as an ADR and a risk.

## 2. What exists

| Project | What it is | Practices worth copying | Gap relative to us |
|---|---|---|---|
| **mcp-policy-gateway** (mzquadri) | MCP proxy with nine deterministic controls at discovery, request and response stages; strongest action wins (allow, sanitize, hold, block) | A **deterministic benchmark with no API keys**: 47 cases (26 attacks, 21 benign near-misses), reproducible with one command; **Wilson confidence intervals**; comparison with a keyword filter; **external validation corpus** (MCPTox, 660 real tool declarations) with honest limits stated; decision latency reported (median about 249 microseconds); explicit limitations section | Stateless: "a pure function of observable protocol events", no memory of earlier instructions, no notion of who authorised what, no delegation |
| **Microsoft Agent Governance Toolkit** | Policy engine (YAML, OPA, Cedar), zero-trust identity, delegation chains, sandbox rings, Merkle audit trail | **Formal specs in RFC 2119 language with 992 conformance tests**; 29 ADRs; formal threat model; fuzz targets; secret scanning in CI; mapping to the OWASP Agentic Top 10; adapters for several agent frameworks; "fail closed" stated as a principle | Policies are developer-authored and static; no user-utterance provenance; no per-decision replay on a cloned state |
| **Progent** (paper) | A DSL of privilege policies per tool and argument; attack success on AgentDojo reduced from 41 to 2 percent (as reported) | Evaluated on an **external benchmark** with utility and attack metrics; policies can be generated from the user's task | Per-call constraints only; no policies across actions or across agents (per the paper's own limitation) |
| **FIDES** (paper) | Information-flow control with integrity and confidentiality labels through agent execution; deterministic blocking on AgentDojo | The right theory for "untrusted data must not steer actions" | A research system; labels attach to data flow in one agent, not to standing instructions over time or to multiple agents |
| **LlamaFirewall** (Meta) | PromptGuard 2 (injection classifier), AlignmentCheck (chain-of-thought audit), CodeShield; reported over 90 percent attack-success reduction on AgentDojo | Layered defences with a **utility-under-attack** view; evaluation on a public benchmark | Probabilistic detectors; no authority model, so no "who allowed this" answer |
| **Invariant Guardrails and mcp-scan** | Rule-based guardrails over agent traces, deployed as a proxy | Rules as readable matching code over **traces** (history-aware) | Rules are written by developers, not derived from user statements |
| **agentgateway** | Proxy for agent-to-tool traffic with RBAC and a CEL policy engine, rate limits, observability | Production gateway shape; policy language reuse; observability | Policy is configuration, not conversation |
| **McpVanguard, mcp-firewall, cMCP and Cedar-based enforcers** | Inspect tool calls before execution; cMCP evaluates a Cedar policy bundle inside a TEE | Standard policy languages (Cedar) with analysable policies | Same: static, developer-authored policy |
| **AgentDojo** (ETH Zurich) | Benchmark of agents under indirect prompt injection: four suites (banking, slack, travel, workspace) with 16, 21, 20 and 40 user tasks; metrics **benign utility, utility under attack, attack success rate**; pip-installable, MIT, active community | The **standard external benchmark** that Progent, FIDES and LlamaFirewall all report on | Single-turn tasks; no standing instructions or revocation over time |

## 3. What the strongest projects have in common

1. **A reproducible benchmark that includes benign near-misses**, so false blocks are measured, not hoped away. Ours already does (legitimate probes); we adopt the corpus framing and confidence intervals.
2. **An external benchmark.** Credible work reports on AgentDojo-style public suites, not only on self-written scenarios.
3. **Specs with numbered, testable rules** (RFC 2119 style) and conformance tests. Ours was prose; we add a normative spec.
4. **Fail closed, deterministic enforcement outside the model.** Already our ADR-001 and ADR-011.
5. **Limitations written down**, including what the system misses. Ours has a claims ledger and non-goals.
6. **Decision latency reported** in the right unit (microseconds for the pure engine, milliseconds end to end).
7. **Framework adapters and examples** so someone can try it in minutes.
8. **ADRs, threat model, fuzzing or property tests, secret scanning** in the repository from the start.

## 4. The honest gap

Almost everything above is **static, developer-authored policy**. None of the projects read treats the **human's own conversational statements as the source of policy**, with:

- provenance from the utterance to every allow or deny,
- the rule that text from untrusted content cannot become authority,
- revocation, supersession and "as of 3 PM" questions answered from the same record,
- **replay**: "what would the decisions have been without this rule?".

That is a narrower claim than "an agent authorisation gateway" (which is crowded), and it is the one we should make. It is also easier to defend: it names a missing capability instead of a missing product.

What Progent says about itself (policies are per call, not across actions or agents) supports the delegation and multi-agent part of the gap. FIDES supports the theory of the lineage rule; our contribution is applying integrity labels to **standing instructions over time**, not data flows within one run.

**Risks to this positioning:** a project we did not find may already do it; the extractor that turns sentences into rules is the weak link and is what Progent-style systems also depend on. Both are recorded in [risk-register.md](./risk-register.md).

## 5. Changes to the plan

| # | Change | Why (evidence) | Where |
|---|---|---|---|
| 1 | **Add a normative authority spec** with numbered rules (RFC 2119 language) and a conformance test per rule, including property-based tests for non-interference, as-of consistency, attenuation and revocation monotonicity | Microsoft's toolkit does spec plus conformance tests; our semantics were prose | [spec/authority-semantics.md](./spec/authority-semantics.md); ADR-014 |
| 2 | **Add external validation on AgentDojo** (a subset of one suite) as an optional, gated phase, reporting benign utility, utility under attack and attack success rate against no defence and a simple baseline | Every credible defence reports on it | [phases/phase-8b-external-validation.md](./phases/phase-8b-external-validation.md); ADR-013 |
| 3 | **Report Wilson confidence intervals** for every rate, and state n | mcp-policy-gateway does; small n makes bare percentages misleading | [evaluation.md](./evaluation.md) |
| 4 | **Add a benign near-miss set** (legitimate actions phrased to resemble attacks) to the deterministic corpus | Same project; it is what makes false blocks meaningful | [evaluation.md](./evaluation.md), [scenarios.md](./scenarios.md) |
| 5 | **Put the decision engine behind a `PolicyDecisionPoint` interface** so a Cedar-backed implementation could be swapped in later; keep our own deterministic engine for v1 | Cedar and OPA are the standard languages; analysability matters; but v1 needs provenance and lifecycle that Cedar does not model | ADR-012 |
| 6 | **Report engine latency in microseconds** (pure function) and end-to-end in milliseconds | Same project | [evaluation.md](./evaluation.md) |
| 7 | **Add OpenTelemetry tracing** on the check path (optional extra) | Gateways in production expose traces; it helps explain latency | [architecture.md](./architecture.md) section 9 |
| 8 | **Provide adapters and runnable examples** (a minimal MCP client script; later an agent-framework example) | The toolkit ships framework adapters | [integration-guide.md](./integration-guide.md) |
| 9 | **Map threats to the OWASP Agentic Top 10** once the current list is verified from the source | The toolkit does; do not copy the list from memory | task in [phases/phase-9-hardening-and-release.md](./phases/phase-9-hardening-and-release.md) |
| 10 | **Reposition the claim** from "an authority gateway" to "user-statement-derived authority with provenance, as-of and replay" | Section 4 | [PRD.md](./PRD.md), [prior-art.md](./prior-art.md), [claims-ledger.md](./claims-ledger.md) |

## 6. What we deliberately do not build

- A prompt-injection classifier (LlamaFirewall, PromptGuard) or a chain-of-thought auditor. Our lineage rule is structural, not statistical, and we do not compete with detectors.
- A general MCP firewall (tool poisoning detection, secret scanning, egress control). mcp-policy-gateway and others do this; the gateway could be composed with them.
- A TEE or Merkle-audit system. Listed as post-release work.
- A policy language. Instructions are produced from sentences, not written in a DSL.

## 7. Evaluation plan, version 2

| Layer | What | Why |
|---|---|---|
| Deterministic corpus (own) | Scenarios S1 to S7 with attacks and benign near-misses, three agent kinds, Wilson intervals, no API keys | Reproducibility ([evaluation.md](./evaluation.md)) |
| Property-based tests | Non-interference, as-of consistency, attenuation, revocation monotonicity, replay faithfulness | Spec conformance ([spec/authority-semantics.md](./spec/authority-semantics.md)) |
| External benchmark (optional) | AgentDojo subset: benign utility, utility under attack, attack success rate | External validity |
| Live sample | Small, labelled, with spread | Real-model behaviour |

**Caveat for the AgentDojo run.** AgentDojo tasks are single-turn, so the "standing instruction" is the user's task text. To use our engine we must derive scopes from that text, which exercises the extractor as much as the gateway, and overlaps with how Progent generates policies. The run therefore tests a narrower claim ("an authority graph seeded from the user's request, with untrusted tool output carrying no authority, blocks injected actions at acceptable utility cost"), and results must be described that way.

## 8. Engineering habits to adopt from day one

- Every rule has an ID and a test; every PR says which rule IDs it touches.
- Every number in the README comes from a committed report with git SHA, model id and date.
- Limitations and non-goals are written before results.
- Security-relevant changes require a test that fails without the change.
- Spec, code and docs change together.

## 9. Sources

- mcp-policy-gateway: https://github.com/mzquadri/mcp-policy-gateway
- Microsoft Agent Governance Toolkit: https://github.com/microsoft/agent-governance-toolkit
- McpVanguard: https://github.com/provnai/McpVanguard · mcp-firewall: https://github.com/ressl/mcp-firewall · cMCP: https://github.com/agentrust-io/cmcp · agentgateway: https://github.com/agentgateway/agentgateway
- Awesome list of MCP security tools: https://github.com/tamish560/awesome-mcp-security
- AgentDojo: https://github.com/ethz-spylab/agentdojo · docs: https://agentdojo.spylab.ai
- Progent: https://arxiv.org/abs/2504.11703
- LlamaFirewall: https://github.com/meta-llama/PurpleLlama/blob/main/LlamaFirewall/README.md · paper: https://arxiv.org/html/2505.03574v1
- Invariant Guardrails and mcp-scan: https://invariantlabs-ai.github.io/docs/mcp-scan/
- Cedar and OPA for MCP access control: https://natoma.ai/blog/mcp-access-control-opa-vs-cedar-the-definitive-guide · https://github.com/permitio/cedar-agent
- Policy language benchmarking: https://goteleport.com/blog/benchmarking-policy-languages/
- FIDES and related IFC work were seen only as search summaries; locate the primary papers before citing.
