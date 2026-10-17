# Phase 8: Verified Revocation Planner (Stretch, Gated)

## Header

- **Goal (done means):** given a forged or mistaken authority source, the planner proposes a small set of revocations that removes every authority path to chosen high-impact actions, and **verifies on a `GRAPH.COPY` clone** that all designated legitimate actions still pass; scenario S7 shows a case where a minimal cut is not just "revoke the root".
- **Preconditions:** Phases 1 to 7 complete **and the go/no-go gate below passes**.
- **Implements:** [../PRD.md](../PRD.md) section 9 and FR-22; [../decisions.md](../decisions.md) ADR-009; [../evaluation.md](../evaluation.md) S7.

## Go/no-go gate (decide before writing any planner code)

All four must be true; otherwise skip this phase and go to Phase 9 (this is expected and fine):

- [ ] Phases 1 to 7 definitions of done are met.
- [ ] A redundancy scenario exists on paper: one forged source reaches a high-impact action through at least three routes (for example a summary, a delegation and a second derived rule), so the smallest cut has more than one element or is not obviously the root.
- [ ] `algo.maxFlow` runs on the pinned FalkorDB image (see task 2).
- [ ] At least 6 hours remain in the effort budget.

## Task breakdown

1. **Branch** `feat/planner`.
2. **Verify `algo.maxFlow`.** In the Browser or `scripts/probe_maxflow.py`: create a 6-node test graph with a `capacity` property, call `CALL algo.maxFlow({sourceNodes:[...], targetNodes:[...], capacityProperty:'capacity', nodeLabels:[...], relationshipTypes:[...]}) YIELD maxFlow, edges, edgeFlows` (confirm argument names against https://docs.falkordb.com/algorithms/maxflow and the installed version). Record the exact working call and result shape in a comment in `planner.py` and in [../data-model.md](../data-model.md) section 7 addendum. Expected from the docs: it returns the flow value and flow-carrying edges with per-edge flow, **not** the minimum cut.
3. **`lineage/planner.py`:**
   - `build_flow_network(client, tenant_id, source_ids, sink_action_types)`: model **authority routes** as a directed graph. Vertices: the forged source nodes (super-source), `Summary`, `Instruction`, `Agent`, and one sink vertex per high-impact action type. Edges follow authority propagation (`EXPRESSES`, `DERIVED_FROM` reversed to propagation direction, `APPLIES_TO`, `DELEGATES_TO`, `ABOUT` to the sink). Capacity: **1** on revocable elements (an instruction's `EXPRESSES` edge, a delegation), **large** (for example 1000) on non-revocable ones. Materialise it in a scratch graph on a `GRAPH.COPY` clone (never mutate the live graph) with a `capacity` property.
   - `min_cut(flow_result, network)`: derive the cut **in application code** from `edgeFlows` and capacities: build the residual graph, BFS from the super-source over edges with remaining capacity, and the cut is the set of saturated edges from the reachable set to the unreachable set; map each cut edge back to a revocable element (`Instruction` or `Delegation`). Assert `sum(capacity of cut) == maxFlow` (a self-check; raise `PlannerInconsistent` otherwise).
   - `plan_revocations(client, tenant_id, source_ids, sink_action_types, must_keep, dry_run=True)`: clone, apply the cut on the clone (revoke those elements with `repo.py`), then **verify** by running `check_authority(persist=False)` on the clone for: (a) forged routes: each forged-derived action probe must be `deny` or `confirm`; (b) `must_keep`: each designated legitimate action must remain `allow`. Return `{cut, verified, preserved, broken, flow}`; if any `must_keep` breaks, return `verified: false` with the broken list and **do not apply**. On success and `dry_run=False` (requires owner approval token), apply the same revocations to the live graph.
4. **Route and tool:** `POST /v1/tenants/{tid}/plan-revocations` (replace the 501 stub if present) and admin MCP tool `plan_revocations`; `dry_run` defaults to true; applying requires `by` to be an owner.
5. **Scenario S7:** `S7_redundant_paths_v1..v2.yaml` with the redundant routes and `must_keep` probes; runner support for the `plan` event; metrics `planner_cut_size_vs_optimum` (brute-force on the small graph: enumerate subsets of revocable elements in increasing size) and `planner_legit_preserved`.
6. **Tests:**
    - `test_flow_value_matches_brute_force_on_small_graph`
    - `test_min_cut_capacity_equals_max_flow`
    - `test_cut_removes_all_forged_paths_on_clone`
    - `test_cut_preserves_must_keep_actions`
    - `test_planner_refuses_to_apply_when_must_keep_would_break`
    - `test_dry_run_does_not_modify_live_graph`
    - `test_clone_is_deleted_after_plan`
    - `test_simple_chain_needs_single_revocation` (sanity: planner agrees with "revoke the root" on a simple chain)

## Real-world engineering concerns

- **Honest framing:** the cut guarantees separation of the modelled routes, not that no other path exists; the clone verification is the real safety check, and the README says so.
- **Safety:** nothing is applied to the live graph without `dry_run=False` and an owner.
- **Cleanup:** the clone is deleted in `finally`.
- **Failure handling:** if `algo.maxFlow` errors, return 503 `planner_unavailable` and fall back to the report "revoke these roots" (non-optimal) clearly labelled as such.

## Definition of done

- [ ] On S7 the planner returns a cut with more than one element (or one that is not the root) and `verified: true`, with all `must_keep` probes still `allow`.
- [ ] Brute-force comparison confirms the cut size is minimal on the test graphs.
- [ ] Dry run leaves the live graph unchanged; applying changes only the cut elements.
- [ ] S7 appears in the evaluation report with `planner_legit_preserved = 100%`.
- [ ] If the gate failed: this phase file is annotated "skipped: <reason>" and the PRD scope table is updated accordingly.

## Risks and blockers

| Risk | Mitigation |
|---|---|
| `algo.maxFlow` arguments or output differ from the docs | Task 2 verification first; adapt `planner.py` only |
| The cut is trivial (revoke the root) | That is the gate's second condition; skip the phase if the scenario cannot show redundancy |
| Planner proposes revoking something legitimate | The clone verification catches it; report `verified: false` instead of applying |

## Time budget

6 percent, about 6 hours, and only if the gate passes. **Cut first if long:** the brute-force comparison and the live-apply step (keep dry-run).

## Handoff

Phase 9 can assume the planner either exists (S7 passing) or is documented as skipped. Tag: `phase-8-complete` (or `phase-8-skipped`).
