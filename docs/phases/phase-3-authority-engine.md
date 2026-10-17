# Phase 3: Authority Engine

## Header

- **Goal (done means):** `check_authority` returns the correct `allow`/`deny`/`confirm` with a complete path for scenario S1 against a real FalkorDB, and all precedence, lineage and delegation rules from the spec are implemented and tested.
- **Preconditions:** Phase 2 complete.
- **Also implements:** [../spec/authority-semantics.md](../spec/authority-semantics.md) (all rules AUTH-001 to AUTH-027, each with its conformance test; property tests with `hypothesis` for AUTH-017, 022, 023, 024, 026) and ADR-012: add `authority/pdp.py` with a `PolicyDecisionPoint` protocol and a pure `DeterministicPDP.decide(request, snapshot)` that `check.py` calls after loading candidates; measure its latency on the fake graph in microseconds. Add `tests/unit/spec/` and `tests/integration/spec/` and a CI check (`scripts/check_spec_tests.py`) that every rule ID in the spec has a test name.
- **Implements:** [../data-model.md](../data-model.md) sections 6 and 8; [../PRD.md](../PRD.md) FR-1 to FR-12, FR-16, FR-17; [../ai-pipeline.md](../ai-pipeline.md) section 4 (deterministic parser).

## Implementation status

Also implemented: `explain.py` (template narratives) and `service.py` (`AuthorityService`: ingest an utterance with server-computed trust, confirm, revoke, delegate with an authority probe, check, explain; owner-only operations). Implemented in several pull requests: (1) `scope.py`, `precedence.py`, `parser.py`; (2) the engine: `ports.py` (ports), `lineage.py`, `delegation.py`, `candidates.py`, `pdp.py` (`DeterministicPDP`), `check.py`, with `tests/fakes/memory_store.py` (an in-memory implementation of the ports) and the conformance tests in `tests/unit/spec/`; (3) the FalkorDB adapter that implements the same ports (phase 2 follow-up). Differences from the plan below, all reflected in the spec: the engine depends on `AuthorityReader` and `DecisionRecorder` ports instead of calling the graph client (ADR-015); `check_authority` never raises, it returns a fail-closed `deny`/`check_error` with an `error_kind` (`graph_unavailable`, `internal`, `persist_failed`); a failure to write the audit record denies the action; the store returns every status created by `as_of` and the engine applies the rules. `scripts/check_spec_tests.py` enforces that each spec rule has a test.

## Task breakdown

1. **Branch** `feat/authority-engine`.
2. **`authority/scope.py`.**
   - `matches(scope, action_type, resource, args) -> bool`: action type equals, is `*`, or prefix wildcard (`email.*` matches `email.delete`); resource matched with `fnmatch.fnmatchcase` after `posixpath.normpath`; reject resources containing `..`; constraints: `max_amount` requires `args["amount"]` to be an integer or float and `<= max_amount`, otherwise not matched (and reported as `constraint_not_met` upstream).
   - `intersect(a, b) -> Scope | None` for delegation: action types intersect (equal, or one is a wildcard covering the other); resource patterns kept as a list (both must match); `max_amount` is the minimum; `None` when empty.
3. **`authority/lineage.py`.** `lineage_trust(client, graph, instruction_id) -> LineageTrust` implementing data-model.md section 8: BFS with `q04_lineage_sources`, visited set, depth limit 6, collecting reached `Utterance` nodes; returns `trusted`, `mixed` or `untrusted`. Also `recompute_and_store(...)` writing the property.
4. **`authority/delegation.py`.** `chains_to(client, graph, agent_id, as_of) -> list[Chain]` using `q02_delegation_chains`; `Chain` holds `root_id` and hops; `effective_candidates(...)` returns candidate instructions of each root with their scope intersected through the chain; depth limit 4; cycle-safe by the visited set.
5. **`authority/precedence.py`.** `decide(candidates) -> Winner | None`: sort by `(activated_at desc, effect_rank)` where `effect_rank` is `deny=0, confirm=1, allow=2`; return the first. Pure function; property test with hypothesis that shuffling inputs never changes the winner.
6. **`authority/parser.py`.** `parse(text) -> list[ParsedInstruction]` using the pattern table in ai-pipeline.md section 4; `ParsedInstruction(effect, action_type, resource_pattern, constraints, text_span)`; returns `[]` for anything unmatched. Includes `HIGH_IMPACT` marking so the API can require confirmation.
7. **`authority/check.py`.** `check_authority(client, tenant_id, req: CheckRequest) -> CheckResult`:
   1. Validate request (pydantic); resolve `as_of` (default `now_ms()`).
   2. `q01` direct candidates; `delegation.effective_candidates`; `q03` supersessions to drop superseded ones; compute each candidate's lineage trust (recompute, do not trust the stored value); drop `untrusted` into `ignored`; mark `mixed`.
   3. Filter by scope match and constraints (collect a `constraint_failed` flag).
   4. `precedence.decide`; map to result and reason per data-model.md section 6; if none and revoked candidates existed at `as_of`, reason `authority_revoked`.
   5. Build `path_json` (ordered hops from trusted utterance to agent and scope; for denials, what was found and why it did not count).
   6. Persist `Action`, `Decision`, `CHECKED`, `USED` via `repo.py` and measure `latency_ms`.
   7. **Fail closed:** wrap steps 2 to 6 in `try/except Exception` returning `deny`/`check_error` (and still try to persist a minimal `Decision`; if persisting fails, log and return the deny anyway). `GraphUnavailable` is re-raised for the API to map to 503 but the gateway treats it as deny.
8. **`authority/explain.py`.** `explain(client, tenant_id, decision_id)` using `q10_decision_path`; builds the template `narrative` strings: one template per reason code (for example `"Denied: no rule from {owner} covers {action_type} on {resource}."`).
9. **`authority/instructions.py`.** Service functions used by the API later: `ingest_utterance(...)` (stores utterance with server-computed trust, parses, creates pending instructions), `confirm(instruction_id, by)` (owner only; rejects untrusted lineage with `UntrustedLineage`), `revoke(...)`, `supersede_if_duplicate(...)`.
10. **Tests:**
    - Unit (fake graph): all cases listed under "Authority check", "Lineage trust", "Delegation" and "Parser" in [../testing.md](../testing.md) section 2, with the parser table in `tests/data/parser_cases.csv` (40 labelled sentences).
    - `tests/unit/test_precedence_property.py`: `test_winner_independent_of_order`.
    - Integration: `tests/integration/test_check_db.py`: `test_s1_delete_returns_confirm_with_path`, `test_s1_read_and_archive_allow`, `test_s2_forged_refund_denied_and_ignored_listed`, `test_as_of_before_revoke_allows`, `test_decision_and_action_nodes_written`, `test_check_error_fails_closed` (stop graph connection mid-test via a client double), `test_p95_latency_under_50ms_on_seed` (soft assertion with a clear message).

## Real-world engineering concerns

- **Determinism:** no randomness or wall-clock reads inside the pure functions; `as_of` is passed in.
- **Consistency:** a check reads the graph in a few queries; a revocation landing between them is acceptable because each query is individually consistent and the next call sees it. Document this in `check.py`.
- **Performance:** at most 4 queries per check plus one BFS step per lineage level; keep each query indexed (data-model.md section 9). Do not cache in v1.
- **Logging:** `structlog` event `check_decided` with `tenant_id`, `agent_id`, `result`, `reason`, `latency_ms` (never the action arguments in full).
- **Security:** lineage trust is recomputed on every check so a tampered stored property cannot grant authority.

## Definition of done

- [ ] S1 integration tests pass: delete → `confirm`/`confirm_rule`, read and archive → `allow`/`authorized`.
- [ ] S2 forged refund → `deny`/`no_authority_path` with the forged instruction listed under `ignored`.
- [ ] A mixed-lineage summary can only produce `confirm`.
- [ ] Parser meets the 40-sentence table (30 parse exactly, 10 stay unparsed).
- [ ] Hypothesis test for order independence passes.
- [ ] Every decision has a non-empty `path_json`.
- [ ] `mypy` strict passes for `mandate.authority`.

## Risks and blockers

| Risk | Mitigation |
|---|---|
| Delegation intersection semantics get subtle | Write the unit tests first from the table in data-model.md; keep chain depth at 4 |
| Lineage BFS performance on deep chains | Depth limit 6; visited set; tenant graphs are small |
| Precedence surprises (later narrow allow after broad deny) | Both orders tested; ADR-007 documents it |
| Parser too narrow or too broad | The 40-sentence table; unparsed stays unparsed |

## Time budget

18 percent, about 18 hours. **Cut first if long:** `explain.py` narratives beyond the main reason codes, supersession-on-duplicate.

## Handoff

Phase 4 can assume: a tested `check_authority`, `explain`, `instructions` service functions, deterministic parser. Tag: `phase-3-complete` (first runnable milestone).
