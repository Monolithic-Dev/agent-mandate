# Prior Art and Positioning

Status: v1.0 · Last updated 2026-10-06. What already exists, what this project overlaps with, and what it adds. **Descriptions come from search results and short summaries, not from reading the code or papers in depth; verify before quoting them anywhere public.** This document supports the claims policy in [claims-ledger.md](./claims-ledger.md).

## 1. Summary

A detailed review of the closest repositories and papers, with the practices adopted from them and the resulting plan changes, is in [engineering-review.md](./engineering-review.md).

The space is crowded. Delegation chains with revocation, MCP authorisation gateways, provenance for agent memory and deletion receipts all exist in some form. This project does **not** claim to be first. It combines, in one small open and measured system: authority that requires provenance back to a trusted human utterance, enforcement at the tool boundary, as-of queries, blast radius with replay on a cloned graph, per-tenant graphs, and a comparison against baselines with false blocks reported.

## 2. Related work

| Work | What it is (as described in sources) | Overlap | What this project does differently or adds |
|---|---|---|---|
| mandatum | Verifiable delegation for AI agents: a signed chain rooted in a named human, narrowing at each hop, revocable at any link; its own page says what is new is narrow | Delegation chain, narrowing, revocation | No signing here; adds lineage trust from utterances, as-of, blast radius, replay, evaluation against baselines |
| Agent Passport System (IETF draft, 2026) | Delegation chains with monotonically narrowing authority, cascade revocation, a policy chain and an MCP enforcement gateway | Narrowing, cascade, MCP gateway | Same caveat; this project is a measured implementation of a small subset plus provenance and replay |
| Charon | MCP authorisation gateway with delegation provenance traced to the originating human | Gateway, provenance of delegation | Adds untrusted-content lineage rule and the graph-based replay |
| Permit MCP Gateway, Gravitee (commercial) | Track delegation chains and enforce per-tool policy | Policy gateway | Open, small, evaluated; not a product |
| CaMeL (Google DeepMind) | Tracks data provenance so untrusted content cannot influence control flow | The principle behind the forged-instruction rule | CaMeL changes how the agent program is executed; this project enforces at the tool boundary without changing the agent |
| MAP-Graph | Provenance-aware shared memory with permissions and revocation; affected descendants stay marked, not deleted | Provenance graph, quarantine-by-marking | Adds action gating, trust from utterances, replay, baseline evaluation |
| MemLineage | Cryptographic provenance and derivation lineage for memory entries | Lineage | No cryptography here |
| Mem-Quarantine | Memory firewall for shared swarms that blocks poisoned memories and removes tainted cascades | Poison containment | Different layer: controls authority to act, not memory admission |
| Graphiti (Zep) | Temporal knowledge graph memory with provenance; removes a fact only when no remaining episode supports it | Temporal facts, provenance | Not a policy engine; could be combined, not required |
| Vismaran | Right-to-be-forgotten across graph, vector and inference layers with a signed receipt | Deletion receipts | Cut from scope here (ADR-008) |
| MemAudit | Post-hoc auditing of poisoned memory via causal attribution and structural anomaly detection (research) | Tracing which memories caused a decision | Post-hoc and benchmark-oriented; this project records decisions as they happen and can replay |
| GitOfThoughts, agent-merge | Version control ideas for agent reasoning and sessions | Branch, diff, replay | Replay here is a cloned authority graph, not git |
| Attack-path tools (BloodHound-style, Wiz) | Graph-based security paths and remediation, with clone-and-verify in some tools | Max-flow min-cut remediation and verification (the optional planner) | The planner is applied to authority routes, and gated as a stretch |
| mcp-policy-gateway, McpVanguard, mcp-firewall, agentgateway, cMCP | MCP proxies enforcing deterministic controls, RBAC with CEL, or Cedar policy bundles inside a TEE | Gateway at the tool boundary, fail-closed enforcement | Policy there is static and developer-authored; ours is derived from the owner's own statements, with provenance, as-of and replay. mcp-policy-gateway is also the model for our benchmark design (benign near-misses, confidence intervals, no API keys) |
| Microsoft Agent Governance Toolkit | Policy engine (YAML, OPA, Cedar), identity and delegation chains, audit trail, conformance specs | Delegation, audit, fail-closed, spec-driven testing | Static policy; no utterance provenance or replay; we copy its spec-plus-conformance-test discipline |
| Progent, FIDES (papers) | Privilege-control DSL (per call, not across actions or agents, per the paper); information-flow control with integrity labels | Lineage rule is a small instance of integrity labelling (FIDES); per-task policy generation overlaps our extractor (Progent) | Standing instructions over time, revocation, multi-agent delegation, replay |
| LlamaFirewall, Invariant Guardrails | Injection classifiers and chain-of-thought audit; trace-based rules | Layered defence; history-aware rules | Probabilistic or developer-written; no authority model; composable with ours rather than competing |
| AgentDojo | Public benchmark for agents under indirect prompt injection (utility, utility under attack, attack success rate) | Our external validation target (optional Phase 8b) | Single-turn tasks; no standing instructions |
| ReBAC systems (Zanzibar-style) | Relationship-based access control as a service | Chains and relationships can be modelled there | See section 4 on the "this is just access control" critique |

## 3. The motivating incident

A February 2026 report described an agent that lost a confirm-before-acting instruction during context compaction and deleted a large part of an owner's inbox (reports say over 200 emails). Source: https://simonwillison.net/2026/Feb/23/summer-yue (secondary account; treat the count as reported, not verified).

## 4. The honest critique and the answer

**"This is access control with extra steps."** Part of it is, and the project says so. What goes beyond a recursive lookup, and is measured rather than asserted:

1. **Authority requires provenance.** A rule counts only if its lineage reaches a trusted owner utterance, with a three-valued trust (`trusted`, `mixed`, `untrusted`) that defeats laundering through summaries.
2. **As-of semantics** from timestamps on the same graph that answers present checks.
3. **Blast radius and replay on a cloned graph** (`GRAPH.COPY`): "what would have happened without this rule" is a query, not a log search.
4. **One graph per tenant**, with a measured isolation probe.
5. **Evaluation against baselines with false blocks reported**, so "it blocks bad actions" cannot hide "it blocks good ones".

If measurement shows these do not matter in practice, the honest conclusion is that a simpler store would do, and the project should say so.

## 5. What to borrow from related work

- Narrowing-only delegation (mandatum, Agent Passport System): already in the design.
- The principle that untrusted data must not steer control flow (CaMeL): the basis of the lineage rule.
- Descendants marked, not deleted (MAP-Graph): the basis of quarantine.
- Signed records (mandatum, MemLineage): listed as post-release work in [roadmap.md](./roadmap.md).

## 6. Sources

- mandatum: https://pkg.go.dev/github.com/kanywst/mandatum
- Agent Passport System: https://datatracker.ietf.org/doc/html/draft-pidlisnyi-aps-00
- Charon: https://glama.ai/mcp/servers/NinadRao0707/charon/tree
- Permit MCP gateway layers: https://www.permit.io/blog/six-layers-mcp-gateway
- CaMeL: https://arxiv.org/abs/2503.18813 · https://simonwillison.net/2025/Apr/11/camel/
- MAP-Graph: https://arxiv.org/pdf/2608.10509
- MemLineage: https://arxiv.org/pdf/2605.14421
- Mem-Quarantine: https://github.com/AAH20/mem-quarantine
- Graphiti provenance: https://blog.getzep.com/how-zep-tracks-provenance-in-agent-memory/
- Vismaran: https://github.com/sambhal-labs/vismaran
- MemAudit: https://arxiv.org/pdf/2605.23723
- GitOfThoughts: https://arxiv.org/abs/2606.14470 · agent-merge: https://github.com/GuanZhengPM/agent-merge
- FalkorDB `GRAPH.COPY`: https://docs.falkordb.com/commands/graph.copy.html · max flow: https://docs.falkordb.com/algorithms/maxflow

## 7. Maintenance

Re-run the prior-art search before any public announcement and before each release. Add anything new here, and adjust the claims in [claims-ledger.md](./claims-ledger.md).
