# Testing

Status: v1.0 · Last updated 2026-10-06. Test strategy for [PRD.md](./PRD.md); named cases are implemented phase by phase in [phases/](./phases/). Scenario-level proof lives in [evaluation.md](./evaluation.md).

## 1. Strategy by layer

| Layer | Scope | Tools | Needs DB |
|---|---|---|---|
| Unit | Pure logic: parser, scope matching, precedence, lineage trust (with an in-memory fake graph), delegation intersection, metrics | pytest | No |
| Integration | `GraphClient`, queries `q01`–`q11`, `check_authority` against a real FalkorDB, API routes via `httpx.AsyncClient`, MCP profiles | pytest, pytest-asyncio, FalkorDB container | Yes |
| Scenario / e2e | Scenarios S1–S7 through the runner for all agent kinds; thresholds asserted | `python -m mandate.eval.runner` | Yes |
| UI | Component tests for `GraphView` and `DecisionPanel`; one Playwright smoke test of the demo page | vitest, Playwright | API |
| Property | Rules AUTH-017, AUTH-022 (untrusted non-interference), AUTH-023 (revocation monotonicity), AUTH-024 (attenuation), AUTH-026 (as-of consistency) with generated graphs and events | hypothesis | No (fake graph) |
| Conformance | One or more named tests per rule in [spec/authority-semantics.md](./spec/authority-semantics.md) section 3; CI fails if a rule ID has no test | pytest | Mixed |
| External (optional) | AgentDojo subset, Phase 8b | agentdojo | Yes |

Calibration: most effort goes to `authority` and the scenario suite, because a wrong decision is the product's worst failure.

## 2. Critical test cases (by feature)

### Authority check (`tests/unit/test_check_*.py`, `tests/integration/test_check_db.py`)
- `test_default_deny_when_no_candidates`
- `test_allow_when_trusted_allow_matches_scope`
- `test_confirm_rule_returns_confirm`
- `test_explicit_deny_beats_allow_same_ms`
- `test_most_recent_rule_wins`
- `test_revoked_rule_not_applied_after_revocation_time`
- `test_as_of_before_revocation_still_allows`
- `test_validity_window_respected`
- `test_max_amount_boundary_inclusive`
- `test_constraint_not_met_reason`
- `test_quarantined_instruction_excluded`
- `test_superseded_instruction_excluded`
- `test_check_error_fails_closed` (simulated graph failure → deny, `check_error`)
- `test_decision_path_reaches_trusted_utterance`

### Lineage trust (`tests/unit/test_lineage.py`)
- `test_owner_direct_utterance_is_trusted`
- `test_untrusted_content_is_untrusted`
- `test_mixed_summary_is_mixed`
- `test_mixed_can_only_confirm`
- `test_cycle_in_derived_from_terminates`
- `test_depth_limit_enforced`

### Delegation (`tests/unit/test_delegation.py`)
- `test_delegate_scope_is_intersection`
- `test_delegate_cannot_exceed_delegator`
- `test_delegation_revoked_blocks_next_call`
- `test_delegator_rule_revoked_blocks_delegate`
- `test_chain_depth_limit`
- `test_delegation_cycle_terminates`
- `test_deny_passes_down_to_delegate`

### Parser (`tests/unit/test_parser.py`)
- 40 labelled sentences (30 parse, 10 do not) as a parametrised table; `test_unparsed_stays_unparsed`.

### Gateway and API (`tests/integration/test_gateway.py`, `test_api.py`)
- `test_agent_profile_has_no_admin_tools`
- `test_agent_identity_from_token_not_argument`
- `test_confirm_flow_requires_owner_approval`
- `test_non_owner_cannot_approve`
- `test_untrusted_instruction_cannot_be_confirmed` (409)
- `test_email_body_recorded_as_untrusted_utterance`
- `test_no_delete_decision_route`
- `test_api_key_required`, `test_rate_limit_returns_429`
- `test_injection_strings_are_inert`

### Lineage tools (`tests/integration/test_lineage.py`)
- `test_blast_radius_lists_derived_and_decisions`
- `test_blast_radius_fixpoint_with_two_levels`
- `test_quarantine_is_reversible`
- `test_replay_changes_match_oracle`
- `test_replay_cleans_up_clone` (even on failure)

### Tenancy and concurrency
- `test_cross_tenant_isolation` (S5)
- `test_concurrent_checks_match_oracle` (S6, smaller size in CI)
- `test_two_approvals_one_wins`

### Planner (stretch, `tests/integration/test_planner.py`)
- `test_flow_value_matches_brute_force_on_small_graph`
- `test_cut_removes_all_forged_paths`
- `test_cut_preserves_must_keep_actions`
- `test_planner_refuses_when_must_keep_would_break`

## 3. Test data and fixtures

- `tests/conftest.py`: `falkordb_client` (session), `tenant` (function-scoped, dropped after), `owner`, `agent`, `now_ms` fixed clock.
- Scenario seeds from `src/mandate/eval/scenarios/*.yaml` double as fixtures.
- A `FakeGraph` implementing the `GraphClient` protocol for unit tests.
- `tests/data/parser_cases.csv` with the 40 labelled sentences.

## 4. Coverage targets

- `mandate.authority`: 95 percent line coverage; `mandate.lineage`: 90 percent; overall: 85 percent. Coverage is a floor, not the goal; the scenario suite is the real acceptance test.

## 5. Acceptance gates (CI and release)

1. All unit and integration tests pass.
2. Stub evaluation: `mandate` executes 0 unauthorised actions; false blocks at most 5 percent; explanation completeness 100 percent; cross-tenant leaks 0.
3. `naive` shows more than 0 unauthorised actions on S1–S3 (otherwise the baseline is not demonstrating the problem and the scenario is rewritten).

## 6. Manual QA checklist (before any demo)

- [ ] `docker compose up -d` and `/healthz` returns `ok`
- [ ] `python -m mandate.seed` completes
- [ ] Demo page loads in under 3 seconds; reset button works
- [ ] S1 split-screen ends with `5 vs 0`
- [ ] S2: forged rule is greyed; refund denied
- [ ] A decision's graph highlights a path ending at the owner utterance
- [ ] Revoke blocks the next call
- [ ] Blast radius and replay show the expected diff
- [ ] Eval page shows the latest table
- [ ] Recorded fallback video is on disk and plays
- [ ] No API key visible in the UI, logs or screenshots

## 7. Explicitly not tested (and why)

- Real email or file systems: sandbox only in v1.
- Real-world prompt-injection robustness of live models: out of scope; the system controls authority, not model behaviour. Live runs are reported as a sample, not as proof.
- Browser compatibility beyond current Chrome and Firefox.
- Load beyond the S6 size: the project claims only what S6 measures.
- Cryptographic properties: there are none in v1.
- Accessibility beyond keyboard navigation and contrast checks (no screen-reader test pass).
