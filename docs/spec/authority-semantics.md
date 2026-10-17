# Authority Semantics Specification

Status: v1.0 (normative) · Last updated 2026-10-06. This is the contract for `check_authority` and its helpers. The key words MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119. Every rule has an ID that tests cite. Data structures are defined in [../data-model.md](../data-model.md); this document defines behaviour. If the two disagree, fix both in one pull request.

## 1. Definitions

- **Tenant graph:** the single FalkorDB graph of one tenant. A decision depends only on it (AUTH-025).
- **As-of time `t`:** the instant for which a decision is evaluated (epoch ms).
- **Instruction:** a rule with `effect` in {`allow`, `confirm`, `deny`}, a scope, a validity window, and a lineage.
- **Lineage trust:** `trusted`, `mixed` or `untrusted`, computed from the utterances an instruction derives from.
- **Candidate:** an instruction that survives the filters in AUTH-007 to AUTH-014 for a given check.
- **Authority path:** the ordered chain from a trusted utterance to the agent and scope that justifies a decision.

## 2. Rules

### Trust and lineage

| ID | Rule |
|---|---|
| AUTH-001 | If no candidate exists, the result MUST be `deny` with reason `no_authority_path`. |
| AUTH-002 | An utterance MUST have `trust = trusted` if and only if its channel is `owner_direct` and its speaker has role `owner`. The server MUST compute this; a client-supplied value MUST be ignored. |
| AUTH-003 | Lineage trust MUST be computed by breadth-first traversal upward from the instruction through `EXPRESSES` and `DERIVED_FROM`, depth at most 6, with a visited set. The result is `untrusted` if no utterance is reached or none is trusted; `trusted` if all reached utterances are trusted; `mixed` otherwise. |
| AUTH-004 | A candidate with lineage `untrusted` MUST NOT contribute to a decision. It MUST be listed in `ignored_json` with reason `untrusted_lineage`. |
| AUTH-005 | A candidate with lineage `mixed` MUST NOT produce `allow`. Mixed candidates are considered only when no trusted candidate is live; then a mixed `allow` or `confirm` yields `confirm` with reason `mixed_lineage`, and a mixed `deny` is honoured as `deny` (`explicit_deny`), because restricting is the safe direction. |
| AUTH-006 | An instruction MUST NOT become `active` unless an owner confirms it and its lineage is `trusted`, or `mixed` with an explicit owner confirmation recorded. An instruction with lineage `untrusted` MUST NOT be activatable. |
| AUTH-022 | **Untrusted non-interference.** Adding any utterance with `trust = untrusted`, and any instruction whose lineage is `untrusted`, MUST NOT change the result, reason, or path of any check. (It MAY add entries to `ignored_json`.) |

### Time and lifecycle

| ID | Rule |
|---|---|
| AUTH-007 | A candidate MUST satisfy `activated_at <= t`, `valid_from <= t`, and (`valid_to` is null or `t < valid_to`). |
| AUTH-008 | A candidate with `revoked_at <= t` MUST be excluded. One with `revoked_at > t` or null MUST be included. Evaluation MUST use timestamps, never the current `status`. |
| AUTH-009 | An instruction MUST be excluded if a **non-quarantined** instruction that supersedes it has `activated_at <= t`. |
| AUTH-010 | A quarantined instruction MUST be excluded from every check and MUST NOT supersede any instruction. |
| AUTH-026 | **As-of consistency.** For any `t`, `check(as_of=t)` MUST be unaffected by any event (activation, revocation, delegation, supersession, utterance) whose timestamp is greater than `t`. |

Two notes on time. An instruction's `created_at` and `activated_at` are the time the system recorded it, never a client-supplied time: an utterance may carry an earlier `at` (when it was said), but rules parsed from it take effect from when they were recorded, so a later ingest cannot change an answer already given for an earlier `t` (`test_backdated_utterance_cannot_rewrite_a_past_answer`). Quarantine is deliberately **not** timestamped (AUTH-010): it removes a rule from every check, including checks about the past, which is what lets replay ask "what if this rule had never existed?". The recorded decisions are the audit trail of what was actually decided; an as-of check after a quarantine answers with the quarantine applied.

### Scope and constraints

| ID | Rule |
|---|---|
| AUTH-011 | A scope matches an action when its `action_type` equals the action's, is `*`, or is a prefix wildcard `x.*` covering it, **and** the normalised resource matches `resource_pattern` as a case-sensitive glob. A resource containing `..` or empty MUST NOT match. |
| AUTH-012 | If a scope has `max_amount`, the action MUST provide a numeric `args.amount` with `amount <= max_amount` (inclusive); otherwise the candidate is not applicable and the check records `constraint_not_met` if no other candidate applies. |

### Delegation

| ID | Rule |
|---|---|
| AUTH-013 | Authority received by delegation MUST be narrowed to the intersection of the delegator's scope and every delegation scope on the chain; `max_amount` is the minimum on the chain. An empty intersection yields no authority. |
| AUTH-014 | A delegation MUST count only if its `created_at <= t`, it is not revoked at or before `t`, and `valid_from <= t < valid_to` (or `valid_to` null). |
| AUTH-015 | A `deny` held by a delegator MUST apply to its delegates. |
| AUTH-016 | Chains MUST be limited to depth 4 and MUST terminate on cycles. |
| AUTH-024 | **Attenuation.** For a delegate with no direct instructions, if the result is `allow` then the same check evaluated for the delegator MUST also be `allow`. |

### Decision

| ID | Rule |
|---|---|
| AUTH-017 | Among candidates, the one with the greatest `activated_at` MUST win; on a tie `deny` beats `confirm` beats `allow`. |
| AUTH-018 | Result and reason MUST follow this table: winner `allow` → `allow`/`authorized`; winner `confirm` → `confirm`/`confirm_rule`; only `mixed` candidates → `confirm`/`mixed_lineage`; winner `deny` → `deny`/`explicit_deny`; candidates existed but all revoked at or before `t` → `deny`/`authority_revoked`; candidates existed but constraints failed → `deny`/`constraint_not_met`; none → `deny`/`no_authority_path`; any error → `deny`/`check_error`. |
| AUTH-019 | Any exception in the check path MUST yield `deny` with reason `check_error`, and the result MUST say why (`error_kind`: `graph_unavailable`, `internal` or `persist_failed`). A graph outage MUST NOT yield `allow` or `confirm`. If the audit record cannot be written, the action MUST be denied (no record, no action). |
| AUTH-020 | Every decision MUST be persisted with a non-empty `path_json` (for denials, what was found and why it did not count), `as_of`, `reason`, and `USED` edges to the instructions considered, unless the check is run with `persist = false`. |
| AUTH-021 | **Determinism.** For the same tenant graph and the same request (including `as_of`), `result`, `reason` and `path_json` MUST be identical across calls. Ids and latency MAY differ. |
| AUTH-023 | **Revocation monotonicity.** Revoking an instruction with effect `allow` MUST NOT change any decision from `deny` or `confirm` to `allow`. |

### Isolation and replay

| ID | Rule |
|---|---|
| AUTH-025 | A decision MUST depend only on the tenant's own graph. No lookup, id resolution or error message MAY reveal whether an id exists in another tenant. |
| AUTH-027 | **Replay faithfulness.** `replay_without(x)` for a recorded decision `d` MUST equal the result of `check` on a graph in which `x` (and instructions derived solely from `x`) is quarantined, evaluated with `d`'s original action and `as_of`. Replay MUST NOT modify the live graph and MUST delete its clone. |

## 3. Conformance test map

Each rule has at least one test; property rules use `hypothesis`. Tests live in `tests/unit/spec/` (pure logic against the in-memory store), `tests/unit/` (models, scope, precedence, parser) and, once the FalkorDB adapter exists, the same checks run against it as contract tests (`tests/integration/`). `scripts/check_spec_tests.py` fails CI if a rule ID has no test whose name contains it (a rule can be listed as pending in the script until its phase; none is today).

| Rule | Tests |
|---|---|
| AUTH-001 | `test_auth001_default_deny` |
| AUTH-002 | `test_auth002_trust_set_by_server`, `test_auth002_external_owner_direct_is_untrusted`, `test_compute_trust` |
| AUTH-003 | `test_auth003_lineage_cases`, `test_auth003_lineage_through_a_derived_instruction`, `test_auth003_cycle_terminates`, `test_auth003_depth_limit_boundary` |
| AUTH-004 | `test_auth004_untrusted_ignored_and_listed`, `test_auth004_pending_untrusted_rule_is_listed_but_inert` |
| AUTH-005 | `test_auth005_mixed_never_allows`, `test_auth005_mixed_deny_is_honoured`, `test_auth005_trusted_candidates_take_precedence_over_mixed` |
| AUTH-006 | `test_auth006_untrusted_rule_stays_pending`, store enforcement `test_untrusted_instruction_cannot_be_activated` (integration), service `test_s2_forged_instruction_is_inert`, owner-only confirmation `test_only_an_owner_can_confirm_revoke_or_delegate` |
| AUTH-007 | `test_auth007_validity_window_edges`, `test_auth007_not_active_before_activation` |
| AUTH-008 | `test_auth008_revocation_as_of_uses_timestamps`, `test_auth008_revoked_instruction_appears_in_the_path` |
| AUTH-009 | `test_auth009_supersession_narrows`, `test_auth009_quarantined_superseder_does_not_supersede` |
| AUTH-010 | `test_auth010_quarantine_excludes` |
| AUTH-011 | `test_auth011_scope_matching_table`, `test_auth011_traversal_rejected` |
| AUTH-012 | `test_auth012_max_amount_inclusive`, `test_auth012_missing_amount_not_applicable`, `test_auth012_constraint_failed_path_names_the_rule` |
| AUTH-013 | `test_auth013_intersection_cases`, `test_auth013_amount_limit_is_the_minimum`, `test_auth013_delegate_cannot_exceed_delegator`, property `test_intersection_matches_iff_both_match` |
| AUTH-014 | `test_auth014_delegation_time_and_revocation`, `test_auth014_expired_delegation_is_inactive_not_revoked` |
| AUTH-015 | `test_auth015_deny_flows_down` |
| AUTH-016 | `test_auth016_depth_limit`, `test_auth016_cycle_terminates` |
| AUTH-017 | `test_auth017_recency_and_tie_break`, property `test_auth017_order_independent` |
| AUTH-018 | `test_auth018_reason_table_*` (one per row), `test_auth018_revoked_is_reported_before_constraint` |
| AUTH-019 | `test_auth019_graph_failure_denies`, `test_auth019_internal_error_denies`, `test_auth019_failure_to_record_denies` |
| AUTH-020 | `test_auth020_decision_record_complete`, `test_auth020_denials_have_a_path_and_are_recorded`, `test_auth020_persist_false_records_nothing` |
| AUTH-021 | `test_auth021_repeat_identical` |
| AUTH-022 | `test_auth022_untrusted_additions_do_not_change_decisions`, property `test_auth022_untrusted_non_interference` |
| AUTH-023 | property `test_auth023_revoke_allow_never_increases_permissiveness` |
| AUTH-024 | property `test_auth024_delegate_not_more_permissive` |
| AUTH-025 | `test_auth025_decisions_depend_only_on_own_store`, `test_tenant_graphs_are_isolated` (integration); uniform not-found errors land with the API |
| AUTH-026 | `test_auth026_future_events_ignored` (example and property forms) |
| AUTH-027 | `test_auth027_replay_equals_quarantined_check`, `test_auth027_live_graph_unchanged` (unit and integration), `test_auth027_clone_deleted`, `test_auth027_clone_deleted_even_when_the_replay_fails` (integration) |

## 4. Using this spec

- A pull request that changes decision behaviour MUST name the rule IDs it touches and update this file and its tests together.
- A new rule gets the next free ID; retired rules are marked "withdrawn", never reused.
- Scenario oracles in [../scenarios.md](../scenarios.md) are written by hand and MUST be consistent with these rules; `test_oracle_consistency` checks that.

## 5. Open points

1. Whether `confirm` should be allowed to chain through delegation (currently yes, as a narrowed `confirm`).
2. Whether a later narrow `allow` should override an earlier broad `deny` (currently yes, by recency; ADR-007).
3. Behaviour when `args.amount` is present but not numeric (currently: not applicable).
