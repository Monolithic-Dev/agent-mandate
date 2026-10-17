# Claims Ledger

Status: v1.0 · Last updated 2026-10-06. What the README, blog posts and any demo may say, and what evidence each statement needs. The rule: **if there is no row here with evidence attached, do not say it.**

## 1. Claims we may make once the evidence exists

| ID | Claim (exact wording to use) | Evidence required | Where the evidence lives | Status |
|---|---|---|---|---|
| C1 | "Under scripted scenarios S1 to S3, Agent Mandate executed N unauthorised actions; the naive baseline executed M." | Stub evaluation report | `docs/results/<date>/report.md` | Measured (stub, 2026-10-07, 26 scenarios): mandate 0 of 47, naive 44, flat 19, static policy 6 (a policy we chose); `docs/results/2026-10-07-eval-v2/report.md`. Earlier run (20 scenarios): `docs/results/2026-10-06-stub/report.md` |
| C2 | "Agent Mandate held legitimate actions with a false-block rate of X percent (n probes)." | Same report, false-block list | same | Measured (stub, 2026-10-07): 0 of 36 legitimate probes blocked for mandate, naive and flat; 7 of 36 for the static policy; includes 3 lookalike scenarios; `docs/results/2026-10-07-eval-v2/report.md` |
| C3 | "Every decision includes an explanation path (X of Y)." | Explanation completeness metric | same | Measured (stub, 2026-10-07): 103 of 103 decisions explained; `docs/results/2026-10-07-eval-v2/report.md` |
| C4 | "For scenario S4, blast radius found K of K affected decisions and replay matched the oracle." | S4 metrics | same | Measured (stub, 2026-10-06): 20 of 20 affected decisions found, replay matched in 5 of 5; `docs/results/2026-10-06-stub/report.md` |
| C5 | "Across S5 variants we observed 0 cross-tenant leaks (n probes)." | S5 results | same | Measured (2026-10-07, real FalkorDB, through the REST API): 0 leaks in 60 probes (95% CI 0.0% to 6.0%) over 3 variants; `docs/results/2026-10-07-s5-s6/isolation.md` |
| C6 | "Under S6 (N parallel checks), decisions matched the oracle; p50 was A ms and p95 B ms on <hardware>." | Concurrency report with hardware stated | same | Measured (2026-10-07, real FalkorDB in Docker on a 20-thread Windows machine, one Python process, 50 closed-loop clients after a warm-up): 1,400 checks and 600 writes, 0 wrong answers, 0 errors, 0 cross-tenant effects, 0 audit-log gaps. Read-heavy p50 about 50-80 ms, p95 about 150-285 ms; write-heavy p50 about 65-115 ms but **p95 about 1.4-2.7 s** (writes to one tenant graph queue behind each other). Latency here is queueing under 50 simultaneous clients, not single-call latency (sequential p95 is 27.5 ms in the stub report). The 100 ms p95 target is not met under this load; `docs/results/2026-10-07-s5-s6/concurrency.md`.  |
| C7 | "In a live sample (one model, 16 scenarios, one run each), results were ..." | Live report, labelled live | `docs/results/2026-10-11-live-openai-gpt-oss-120b/report.md` | Measured (2026-10-11, `openai/gpt-oss-120b` on Groq): without the gateway, 28 of 39 attempts that should not execute did (71.8%, 95% CI 56.2% to 83.5%); with it, 0 of 39 (0.0%, 95% CI 0.0% to 9.0%); legitimate actions completed 24 of 27 and 27 of 27. One model, one run per scenario and arm, 16 of 27 scenarios (the others cannot be one task); the prompt-only arm is our own prompt, not an optimised one. Say "one model on scripted tasks", never "models" |
| C8 | "The deterministic parser matched P of 40 labelled sentences." | Parser accuracy | same | Measured: 40 of 40 labelled sentences (30 parse exactly, 10 stay unparsed), `tests/unit/test_authority_parser.py` |
| C9 | "The planner found a cut of size S on S7, minimal by brute force, with legitimate actions preserved." | S7 results | same | Only if Phase 8 is done |

| C10 | "On an AgentDojo subset (suite, n tasks, seed, model, version), attack success rate was A with no defence, B with the tool-filter baseline and C with Mandate; benign utility was X, Y and Z (Wilson intervals shown). This tests the engine plus a scope-synthesis step." | Phase 8b report, with oracle and synthesised modes separate | `docs/results/<date>/agentdojo.md` | Only if Phase 8b is done |
| C11 | "The authority semantics are specified as N numbered rules, each with a conformance test; property-based tests passed on M generated cases." | Spec file and CI output | [spec/authority-semantics.md](./spec/authority-semantics.md), CI logs | Measured: 27 rules, each with at least one conformance test (enforced by `scripts/check_spec_tests.py`); property-based tests run in CI |
| C12 | "Mutation testing of the authority engine killed N of M mutants (score P%); survivors are listed and judged." | Mutation report | `docs/results/<date>-mutation/report.md` | Measured (2026-10-07): 107 of 112 (95.5%); survivors judged equivalent or untestable, `docs/results/2026-10-07-mutation/report.md` |
| C13 | "Every stored explanation can be re-checked against the graph; N of N verified." | Evaluation report plus `tests/unit/test_verify.py` | `docs/results/<date>/report.md` | Measured (2026-10-08, real FalkorDB): 103 of 103 Mandate explanations verified; 11 kinds of tampering caught in unit tests. This checks the explanation is consistent with the graph, not that the decision was right |
| C14 | "Under S6 (50 clients across 5 tenants), a revoke took effect within its own write: no check that started after the write finished was allowed; the write window was A ms at p50 and B ms at worst." | S6 report with the revocation-lag table and the timing-window oracle | `docs/results/<date>/concurrency.md` | Measured (2026-10-08, git `0a31c7f`, FalkorDB 6.0.1 in Docker on a 16-thread Windows machine, one Python process): read-heavy window p50 237.8 ms, max 1,210.5 ms; write-heavy p50 629.9 ms, max 1,430.2 ms; 0 wrong answers. The window is write latency under queueing, not a propagation delay: within it either answer is correct. `docs/results/2026-10-08-eval-v4/concurrency.md` |

**Positioning sentence (the one we may use):** "Agent Mandate derives authority from what the owner actually said, requires every allow to trace back to a trusted utterance, and can answer 'as of when?' and 'what if that rule hadn't existed?' from the same graph." It does not claim to be the first authorisation gateway.

## 2. Claims we must not make

| Claim | Why not |
|---|---|
| "First", "unique", "novel mechanism", "nobody has done this" | Related work exists ([prior-art.md](./prior-art.md)) |
| "Prevents prompt injection" | It controls authority, not what the model reads or says |
| "Provably forgotten" or any erasure guarantee | Out of scope (ADR-008) |
| "Secure" or "production-ready" | Single admin key, synthetic data, no external audit |
| "Works with real mailboxes" | Sandbox only |
| "Scales to ..." beyond S6 sizes | Only what S6 measures |
| "Better than <named product>" | No head-to-head comparison has been run |
| Any figure from the motivating incident stated as fact | Secondary reporting; say "reported" |

## 3. Wording rules

- Always give the number of probes or runs next to a rate.
- Say "scripted", "synthetic" and "stub" where they apply. Never present stub-mode results as live-model results.
- Report failures: list the variants where Agent Mandate failed or blocked a legitimate action.
- State the date, git SHA and model id of every result.
- Credit related work by name wherever the idea overlaps.

## 4. Process

1. A statement enters the README only if it matches a row in section 1 and the evidence exists.
2. `scripts/render_results.py` (Phase 9) generates the README table from the committed reports so numbers cannot drift.
3. When a result changes, update the row's status and date in the same pull request.
4. Before any public post, re-read section 2.
