# Roadmap

Status: v1.0 · Last updated 2026-10-06 · Implements [PRD.md](./PRD.md) section 14. Detailed steps are in [phases/](./phases/).

## 1. Plan at a glance

This is built as a personal project, so time is expressed as effort shares and nominal hours for one developer working part-time; calendar dates are flexible. A compressed 96-hour slice is in section 3.

| # | Phase | Goal | Effort share | Nominal hours |
|---|---|---|---|---|
| 1 | Scaffolding | Repo, tooling, CI, Compose, `GraphClient` smoke test | 5% | 5 |
| 2 | Data layer | Schema, indexes, tenants, queries, seed | 8% | 8 |
| 3 | Authority engine | `check_authority`, lineage trust, precedence, delegation, parser; S1 passes against real FalkorDB | 18% | 18 |
| 4 | Gateway and API | MCP agent/admin profiles, sandbox, guard, REST core | 14% | 14 |
| 5 | Agents and evaluation | Scripted LLM, three agent kinds, scenarios S1–S3 and S5, metrics, concurrency S6 | 15% | 15 |
| 6 | Lineage tools | Blast radius, quarantine, replay; S4 | 10% | 10 |
| 7 | UI and demo | Graph view, split-screen, decision, blast radius, replay, eval pages | 14% | 14 |
| 8 | Planner (stretch, gated) | Verified revocation planner; S7 | 6% | 6 |
| 8b | External validation (optional, gated) | AgentDojo subset with Wilson intervals ([phase-8b](./phases/phase-8b-external-validation.md)) | taken from Phase 9 slack | about 8 |
| 9 | Hardening and release | Edge cases, live runs, results, README, demo video | 10% | 10 |

Total about 100 hours. Cut order if time runs short: Phase 8 first, then replay (Phase 6 second half), then UI polish. Never cut: the check, the lineage-trust rule, the baseline comparison, the false-block metric.

## 2. MVP milestone ("done enough to demo")

All of the following are true:
- `docker compose up` brings up FalkorDB, the API and the UI.
- Scenarios S1, S2 and S3 run for `naive`, `flat` and `mandate`, with `mandate` executing 0 unauthorised actions and at most 5 percent false blocks.
- Every decision has an explanation path viewable in the UI.
- S5 (tenant isolation) shows zero leaks.
- The evaluation report is generated from the harness.

Should tier (adds): as-of queries, blast radius, replay (S4), concurrency (S6).

## 3. Hackathon-mode slice (only if entering Graph Hacks is confirmed allowed)

The hackathon runs Oct 15 to Oct 18 (96 hours, GMT+5:30). **Do not use this slice unless the organisers confirm in writing that work done before the start is acceptable**; otherwise the main coding must start on Oct 15 (PRD section 14).

| Hours | Work |
|---|---|
| 0–24 | Phases 1–3 (schema, check, S1) |
| 24–48 | Phases 4–5 (gateway, agents, S2, S3, metrics) |
| 48–72 | Phases 6–7 (blast radius, replay, UI) |
| 72–96 | Phase 9 only (hardening, results, video, README, submit); Phase 8 only if the go/no-go gate passed at hour 48 |

## 4. Stretch goals ranked by effort versus payoff

| Goal | Effort | Payoff |
|---|---|---|
| As-of explorer in the UI (slider over time) | Low | High (shows time travel) |
| Live-model runs of S1–S3 with a published comparison | Low | High (credibility) |
| Concurrency chart in the UI | Low | Medium |
| Revocation planner (Phase 8) | Medium to high | High if scenario S7 is convincing, else low |
| Real adapter (IMAP read-only) | High | Medium; adds privacy work |
| Signed instruction records | High | Medium; existing projects do this |

## 5. Demo script (3 minutes)

1. **(0:00)** One sentence: "Agents keep your rules in memory. Memory gets summarised. Here is what happens."
2. **(0:15)** Run S1 split-screen. Naive deletes five emails; Agent Mandate stops and asks. Footer shows `5 vs 0`.
3. **(1:00)** Run S2. Show the untrusted email, the greyed forged rule, and the denied refund with the ignored-instruction chip.
4. **(1:30)** Click a decision: show the explanation path on the graph. "Who authorised this? Here is the chain back to the owner's words."
5. **(1:50)** Run S3: revoke a delegation; the next call is denied.
6. **(2:10)** S4: open a mistaken rule, show the blast radius, press Replay; two decisions flip.
7. **(2:40)** Show the evaluation table: unauthorised actions and false blocks for the three agents.
8. **(2:55)** Close: "Authority with provenance, enforced at the tool boundary, measured against baselines."

Order rationale: the gap is shown first (concrete pain), then provenance (the idea), then explanation, then control, then repair, then numbers.

## 6. After the first release (about three months)

- Real adapters (IMAP, Gmail API read-only, a file-store connector) with a privacy review.
- Signed instruction records and external append-only audit log.
- Per-tenant OAuth and a hosted multi-tenant version.
- Policy-as-graph editor in the UI.
- Comparison study with existing delegation gateways on a shared scenario set.
- Optional planner and redundancy analysis on large authority graphs.

## 7. Risks to schedule

| Risk | Phase | Mitigation |
|---|---|---|
| FalkorDB dialect differs from the sketched Cypher | 2 | Validate each query on the live instance first; adapt `q*.cypher` |
| MCP SDK cannot serve two profiles in one process | 4 | Two ports or two processes |
| UI graph work expands | 7 | Use Cytoscape defaults; cap features to the flows in ux-flows.md |
| Planner has no convincing scenario | 8 | Go/no-go gate; skip |
| Evaluation shows Mandate has false blocks | 5 | Fix rules or report honestly |


## Added after the teammate-document review (2026-10-07)

Done: static-policy baseline, laundered and lookalike scenarios, S5 and S6, mutation testing, read-only graph calls, metrics and readiness, reliance ranking. Since done: scoped keys and roles, token expiry and rotation, the injection corpus, the explanation verifier, seed and reset, the production stack, an audit trail for rule state changes, and measured revocation lag. What remains is in [friend-docs-review.md](./friend-docs-review.md): live-model runs with a record/replay cache and a hosted instance. Since done as well: the web console, approving held actions from it, live updates, single-use approval links and per-token revocation.
