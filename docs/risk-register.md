# Risk Register

Status: v1.0 · Last updated 2026-10-06. Likelihood (L) and impact (I) are judgements on a 1 to 5 scale, not measurements. Review at the end of every phase; add the date and outcome to the Status column.

| ID | Risk | L | I | Mitigation | Early signal | Phase | Status |
|---|---|---|---|---|---|---|---|
| R1 | Result reads as "access control with extra steps" and the extras do not matter in practice | 4 | 4 | Lead with provenance, as-of and replay; measure them; answer honestly in [prior-art.md](./prior-art.md) section 4 | Reviewers ask "why not Postgres?" and the answer is weak | 5, 9 | Open |
| R2 | FalkorDB dialect differs from the sketched Cypher (variable-length filters, map collection, parameterised bounds) | 3 | 3 | Validate every query on the live instance in Phase 2; keep fixed-depth fallbacks | A `q*.cypher` errors on first run | 2 | Closed 2026-10-08: every `q*.cypher` and `w*.cypher` runs against a real FalkorDB in the integration CI job |
| R3 | `GRAPH.COPY` fails or is slow ("could not fork") | 2 | 3 | Retries with backoff; clone cleanup; log `copy_ms`; fallback to rebuilding a subgraph | Copy time above 2 s on small graphs | 6 | Open |
| R4 | MCP SDK cannot serve two profiles with separate tokens in one process | 3 | 3 | Two ports or two processes; thin adapter | Auth hook missing in the SDK | 4 | Closed 2026-10-08: agent and admin are separate server processes (`python -m mandate.mcp_servers agent` and `... admin`) |
| R5 | Local Python is 3.9 while the project needs 3.12 | 5 | 2 | Install 3.12 (see [dev-setup.md](./dev-setup.md)); use a virtual environment | `pip install -e .` refuses on 3.9 | 1 | Open |
| R6 | Baseline looks like a strawman | 3 | 4 | Include the `flat` baseline; document the compaction function; live runs as a cross-check | Reviewers say "of course naive fails" | 5, 9 | Open |
| R7 | Mandate has false blocks on legitimate probes | 3 | 3 | Inspect and fix rules; report what remains | False-block rate above 5 percent | 5 | Closed 2026-10-08: 0 of 36 legitimate probes blocked in `docs/results/2026-10-07-eval-v2`; reopen if a new scenario shows one |
| R8 | Scope creep (UI, planner, adapters) | 4 | 3 | Tier and cut order in the PRD; planner gate; phase budgets | A phase exceeds 150 percent of budget | all | Open |
| R9 | Live LLM runs cost more or behave inconsistently | 3 | 2 | Caps (12 calls, 1024 tokens); small sample; report spread; scored runs use the scripted LLM | Spend log above target | 9 | Open |
| R10 | Instruction parser too narrow or too broad | 3 | 3 | 40-sentence labelled set; unparsed stays unparsed; high-impact rules need owner confirmation | Accuracy below target on the labelled set | 3 | Open |
| R11 | Planner has no convincing scenario or `algo.maxFlow` differs from the docs | 4 | 2 | Go/no-go gate (Phase 8); skip if the gate fails | Gate item unchecked at Phase 8 start | 8 | Open |
| R12 | Prior-art overlap grows during the build | 3 | 3 | Re-run the search before releases; adjust claims | A new project does the same thing | 9 | Open |
| R13 | Docs drift from code | 4 | 3 | Update docs in the same PR; PR template checks; final read-through | A reviewer finds a name mismatch | all | Open |
| R14 | Secrets committed by mistake | 2 | 5 | `.gitignore`, pre-commit gitleaks, CI scan in Phase 9, rotate on any leak | Scanner alert | all | Open |
| R15 | Single maintainer: schedule depends on one person | 4 | 3 | Small phases; each phase leaves a working tree and a tag | A phase stalls more than a week | all | Open |
| R16 | Name "Agent Mandate" conflicts with an existing project | 3 | 2 | Check before any public announcement; rename is cheap early | Search finds a product with the same name | 9 | Open |
| R17 | Hackathon eligibility is unclear (work started before the event) | 3 | 4 | Treat as a personal project; ask the organisers in writing; never alter history | No answer from organisers | 9 | Open |
| R18 | UI graph work expands | 3 | 2 | Cytoscape defaults; six flows only; table fallback | Phase 7 above 150 percent of budget | 7 | Open |

| R19 | The space is more crowded than first thought (gateways, policy engines, IFC, guardrails); the claim reads as a re-implementation | 4 | 4 | Reposition to the specific gap (user-statement-derived authority with provenance, as-of, replay); credit prior work; compose rather than compete ([engineering-review.md](./engineering-review.md)) | A reviewer names an existing project doing the same | all | Open |
| R20 | AgentDojo integration costs more than planned or tests the scope-synthesis step more than the engine | 4 | 2 | Gate in Phase 8b; report oracle and synthesised modes separately; skip if the gate fails | Smoke run fails or budget estimate exceeded | 8b | Open |
| R21 | Spec rules and code diverge (rule IDs without tests) | 3 | 3 | Conformance test map in the spec; PRs cite rule IDs; CI check that every rule ID has a test name | A rule ID with no matching test | 3, 9 | Open |
| R22 | The sentence-to-rule extractor is the weak link and dominates results in the external benchmark | 4 | 3 | Deterministic parser plus owner confirmation for high-impact rules; report extractor accuracy separately | Low extractor precision on the labelled set | 3, 8b | Open |

## Review log

| Date | Phase reviewed | Changes |
|---|---|---|
| 2026-10-06 | Initial | Register created |
| 2026-10-06 | Reference-repo review | Added R19 to R22 after analysing comparable projects |
