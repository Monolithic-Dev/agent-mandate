# Phase 6: Lineage Tools (Blast Radius, Quarantine, Replay)

## Header

- **Goal (done means):** for a mistaken or forged instruction, the system lists every affected summary, derived instruction, delegation and decision; the owner can quarantine it (reversibly); replay on a `GRAPH.COPY` clone shows exactly which decisions would differ; scenario S4 passes with oracle-matching results.
- **Preconditions:** Phase 5 complete.
- **Implements:** [../PRD.md](../PRD.md) FR-18, FR-19, UC4; [../api-spec.md](../api-spec.md) "Lineage" section; [../data-model.md](../data-model.md) `q05`, `q06`, `q07`; [../evaluation.md](../evaluation.md) S4.

## Implementation status

Done: `lineage/blast_radius.py` (`blast_radius`, `quarantine`, `derived_closure`: a bounded, cycle-safe fixpoint over summaries and the rules expressed from them), `lineage/replay.py` (`replay_without`: clone, quarantine on the clone, re-evaluate each affected decision at its original `as_of`, always remove the clone), the `LineageReader` port (derivation step, decisions using, delegations via, `clone_for_replay`) implemented by the FalkorDB store (`GRAPH.COPY`) and the in-memory fake (deep copy), and the REST routes `GET .../blast-radius`, `POST .../quarantine`, `DELETE .../quarantine?by=`, `POST .../replay`. Activating a rule now supersedes older active rules with the same effect, scope and agents (AUTH-009), which is what makes the S4 "typo supersedes the right limit" story work. Differences from the plan: the lineage package works through ports rather than the graph client; `replay` takes no body; release of a quarantine is `DELETE` with the owner as a query parameter; blast radius also lists the `reason` and `agent_id` of each affected decision. Scenario S4's YAML and its metrics arrive with the evaluation harness.

## Task breakdown

1. **Branch** `feat/lineage-tools`.
2. **`lineage/blast_radius.py`.** `blast_radius(client, tenant_id, instruction_id) -> BlastRadius`:
   - Fixpoint loop: start with `ids = {instruction_id}`; repeat `q05_blast_radius_step` to add summaries and the derived instructions they express, until no new ids (cap 10 iterations, visited set).
   - `q06_decisions_using` for all ids; `q07_delegations_via` for all ids.
   - Returns `{instruction_id, summaries, derived_instructions, delegations, decisions:[{id, result, action}]}` sorted by time.
   - **Validation:** unknown instruction → `NotFound`.
3. **`lineage/quarantine.py`.** `quarantine(client, tenant_id, instruction_id, value=True)` sets `quarantined` on the instruction and all derived instructions (from the blast radius); returns the affected ids; idempotent; `DELETE` variant sets false. Quarantine does not alter history or `status`.
4. **`lineage/replay.py`.** `replay_without(client, tenant_id, instruction_id) -> ReplayResult`:
   1. `run_id = new_id("act")[4:]`; clone name `t_<tenant>__replay_<run_id>` via `client.copy_graph` with 3 retries and backoff on transient "could not fork" errors; `GraphUnavailable` after retries.
   2. In a `try/finally`: on the clone, mark the instruction and derived instructions quarantined (`set_quarantined`).
   3. For each decision from `blast_radius`, re-run `check_authority` against the clone using the original action and `as_of = decision.as_of`, **in dry-run mode** (parameter `persist=False`, so no nodes are written even on the clone).
   4. Compare `was` and `now` results; return `changes` (where different) and `unchanged` count.
   5. `finally`: `client.delete_graph(clone)`; if deletion fails, log an error and rely on `sweep_replay_graphs()` at startup.
5. **Add `persist: bool = True` to `check_authority`** (Phase 3 code) without changing default behaviour; add a test.
6. **Routes** in `api/routes/lineage.py`: `GET /instructions/{iid}/blast-radius`, `POST /instructions/{iid}/quarantine`, `DELETE /instructions/{iid}/quarantine`, `POST /instructions/{iid}/replay`; error mapping for `GraphUnavailable` (503). Admin MCP tools `blast_radius`, `quarantine`, `replay_without` call the same service functions.
7. **Scenario S4 files** `S4_bad_authority_v1..v5.yaml` and runner support for the events `owner_say` (mistaken rule), `agent_attempt` (four actions that use it), and a final `probe_lineage` event asserting expected affected decision ids and expected replay changes (oracle values written by hand). Extend `eval/metrics.py` with `tainted_found` and `replay_accuracy`; extend `report.py`.
8. **Tests:**
    - Integration: `test_blast_radius_lists_derived_and_decisions`, `test_blast_radius_fixpoint_with_two_levels`, `test_blast_radius_unknown_instruction_404`, `test_quarantine_excludes_instruction_in_check`, `test_quarantine_is_reversible`, `test_replay_changes_match_oracle`, `test_replay_does_not_modify_live_graph` (node counts equal before and after), `test_replay_cleans_up_clone`, `test_replay_cleans_up_on_exception`, `test_replay_retries_on_fork_failure` (client double), `test_check_persist_false_writes_nothing`.
    - Scenario: `test_s4_all_variants_tainted_found_100_percent`, `test_s4_replay_accuracy_100_percent`.

## Real-world engineering concerns

- **Clone lifecycle:** guaranteed deletion in `finally`; unique names; startup sweep; never reuse a clone.
- **Cost:** `GRAPH.COPY` time grows with graph size; log `copy_ms` and add a warning above 2 s.
- **Consistency:** replay uses the live graph's state at copy time; mutations after the copy are not reflected, which is acceptable and documented in the response (`copied_at`).
- **Concurrency:** replay runs against a clone and does not block live checks (GRAPH.COPY keeps the source accessible per the FalkorDB docs).
- **Safety:** quarantine only changes a flag; nothing is deleted, so decisions stay auditable.

## Definition of done

- [ ] For the S4 seed, `blast-radius` returns exactly the oracle's set of affected decisions.
- [ ] `replay` returns exactly the oracle's changed decisions and leaves the live graph's node counts unchanged.
- [ ] After the call there are no `__replay_` graphs in `list_graphs()` (also after a forced failure).
- [ ] Quarantining makes subsequent checks ignore the instruction; unquarantining restores them.
- [ ] Evaluation report includes `tainted_found = 100%` and `replay_accuracy = 100%` for `mandate`; baselines show 0 (no equivalent).

## Risks and blockers

| Risk | Mitigation |
|---|---|
| `GRAPH.COPY` argument or behaviour differs on the pinned version | Test early with a minimal script; pin the image tag; fall back to rebuilding a clone from a query dump if copy is unavailable |
| Blast radius fixpoint explodes on cycles | Visited set and iteration cap |
| Replay semantics confuse reviewers | Document `as_of = original decision time` and that only rules (not later facts) change |

## Time budget

10 percent, about 10 hours. **Cut first if long:** `DELETE quarantine`, delegation listing in blast radius (keep decisions and derived instructions).

## Handoff

Phase 7 can assume: stable lineage endpoints returning the documented shapes and S4 passing. Tag: `phase-6-complete`.
