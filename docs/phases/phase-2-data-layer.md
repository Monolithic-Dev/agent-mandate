# Phase 2: Data Layer

## Header

- **Goal (done means):** the full schema from the data model exists in FalkorDB, tenants can be created and dropped, queries `q01`–`q11` are validated on the live instance, and a seed script builds the S1 sample tenant.
- **Preconditions:** Phase 1 complete (`phase-1-complete` tag).
- **Implements:** [../data-model.md](../data-model.md) sections 1 to 12; [../architecture.md](../architecture.md) (`mandate.graph`, `mandate.models`).
- **Spec correction to make in this phase:** a repository module `src/mandate/graph/repo.py` is added (functions that write nodes and edges). Update [../project-structure.md](../project-structure.md) in the same pull request to list it.

## Implementation status

Done in the graph-adapter pull request: `graph/client.py` (named queries only, error mapping, copy and delete), `graph/queries/*.cypher` (validated on a live FalkorDB; see data-model.md section 7b), `graph/schema.py`, `graph/tenants.py`, `graph/mapping.py` and `graph/store.py` (`FalkorAuthorityStore`: implements the authority ports and the write operations; AUTH-006 enforced in `activate_instruction`). The in-memory fake and the FalkorDB store are held to the same behaviour by contract tests and a differential property test (`tests/integration/test_store_contract.py`). Remaining from this plan: the REST-facing use cases and `scripts/seed.py`. Host ports are configurable (`FALKORDB_PORT`, `FALKORDB_BROWSER_PORT`) because 6379 is often taken.

## Task breakdown

1. **Branch** `feat/data-layer`.
2. **`src/mandate/models/domain.py`.** Pydantic v2 models matching data-model.md section 3 exactly: `Principal`, `Utterance`, `Instruction`, `Scope`, `Agent`, `Summary`, `Action`, `Decision`, `Approval`, `Delegation`. Enums: `Effect(allow,deny,confirm)`, `Channel(owner_direct,untrusted_content)`, `Trust`, `LineageTrust`, `Role`, `AgentKind`, `InstructionStatus`, `ActionStatus`, `Result`. A `field_validator` per rule in data-model.md section 10 (id regex, `valid_to > valid_from`, action type in registry or wildcard, constraints keys limited to `max_amount`, timestamps non-negative and not more than 5 minutes in the future).
3. **`src/mandate/models/registry.py`.** `ACTION_TYPES` tuple, `HIGH_IMPACT` set, `is_valid_action_type(s)`.
4. **`src/mandate/graph/schema.py`.** `ensure_indexes(client, graph_name)` creating the indexes in data-model.md section 9 via `run_admin_text` (idempotent: swallow "already indexed" errors only). Attempt unique constraints on `id` per label; if the server syntax differs from the documented command, record the working syntax in a comment and in data-model.md section 9.
5. **`src/mandate/graph/tenants.py`.** `tenant_graph_name(tenant_id)` (validates `^[a-z0-9_]{1,40}$` with no `__`, so no tenant graph can match the replay marker; returns `t_<id>`), `create_tenant(client, tenant_id, name)` (writes a `Tenant` node in `mandate_registry`, creates the tenant graph, runs `ensure_indexes`; raises `TenantExists`), `drop_tenant`, `list_tenants`, `sweep_replay_graphs()` (deletes graphs containing `__replay_`).
6. **Queries.** Create `src/mandate/graph/queries/q01_direct_candidates.cypher` … `q11_graph_view.cypher` from data-model.md section 7. For each, run it against a hand-built tenant in the Browser (port 3000), fix any dialect issue, and update the SQL-free sketch in data-model.md in the same pull request. **Known areas to verify:** variable-length path with `all(... IN relationships(path) ...)` in q02; `collect` of map literals in q04 and q10; a parameterised variable-length bound in q11 (`*0..$depth` may not be allowed; if not, generate three fixed variants `q11_graph_view_d1/d2/d3`).
7. **`src/mandate/graph/repo.py`.** Functions (each uses one parameterised write query stored in `queries/w*.cypher`, named `w01_create_principal.cypher` … ; `run()` accepts `^[qw]\d{2}_`):
   - `create_principal`, `create_agent`, `create_utterance`, `create_summary`
   - `create_instruction_with_scope(utterance_or_summary_id, instruction, scope, agent_ids)` (single transaction-like query creating `Instruction`, `Scope`, `EXPRESSES`, `ABOUT`, `APPLIES_TO`)
   - `activate_instruction(id, at)`, `revoke_instruction(id, at, by_instruction=None)`, `supersede(new_id, old_id, at)`
   - `create_delegation(dlg)` and `revoke_delegation(id, at)`
   - `create_action`, `create_decision(decision, action_id, used)`, `set_action_status`
   - `set_quarantined(ids, value)`
   - **Validation:** every function validates input with the pydantic models first; every function returns the created model; writes that must be conditional (activate only if `status = 'pending'`, approve only if `status = 'pending'`) use `WHERE` and return a count; raise `Conflict` when the count is 0.
8. **`scripts/seed.py`.** Creates tenants `acme` and `globex`, the principals, agents and the S1 sample records from data-model.md section 11 through `repo.py` (not raw Cypher), idempotent (`--reset` drops and recreates).
9. **Tests (integration unless noted):**
    - `tests/unit/test_models_validation.py`: `test_effect_enum_rejected`, `test_id_regex`, `test_constraints_unknown_key_rejected`, `test_valid_to_after_valid_from`, `test_future_timestamp_rejected`.
    - `tests/integration/test_tenants.py`: `test_create_and_list_tenant`, `test_duplicate_tenant_409`, `test_drop_tenant_removes_graph`, `test_sweep_replay_graphs`.
    - `tests/integration/test_schema.py`: `test_ensure_indexes_idempotent`.
    - `tests/integration/test_repo.py`: `test_create_instruction_creates_edges`, `test_activate_only_pending`, `test_revoke_sets_timestamp_and_status`, `test_set_quarantined`, `test_conditional_write_conflict`.
    - `tests/integration/test_queries.py`: one test per query `q01`–`q11` on the S1 seed asserting the expected rows (for example `test_q01_returns_read_and_delete_rules`, `test_q02_delegation_depth_limit`, `test_q04_lineage_of_forged_instruction`).
    - `tests/integration/test_isolation_basic.py`: `test_tenant_a_graph_does_not_contain_tenant_b_nodes`.

## Real-world engineering concerns

- **Concurrency:** FalkorDB serialises writes per graph; `repo.py` functions are single statements so partial writes cannot be observed. Conditional updates return a count to detect races.
- **Idempotency:** `ensure_indexes`, `seed.py` and `create_tenant` can be re-run safely.
- **Injection:** only `queries/*.cypher` files are executable; all values travel as parameters.
- **Observability:** each `run()` logs `query_name`, `graph`, `rows`, `duration_ms` at debug level.

## Definition of done

- [ ] `python scripts/seed.py --reset` creates `acme` and `globex` and prints node counts per label.
- [ ] All eleven `q*.cypher` files execute without error on the seed and the named tests pass.
- [ ] `create_tenant("acme")` twice raises `TenantExists`.
- [ ] `repo.activate_instruction` on an already active instruction raises `Conflict`.
- [ ] `tests/integration/test_isolation_basic.py` passes.
- [ ] `data-model.md` and `project-structure.md` match the code (names, queries, `repo.py`).

## Risks and blockers

| Risk | Mitigation |
|---|---|
| Dialect differences in Cypher (variable-length filters, map collection, parameterised bounds) | Validate each query early; keep fixed-depth variants as a fallback |
| Unique-constraint syntax differs | Use application-level uniqueness (ids are time-ordered random) and document |
| Index creation errors on empty labels | Create indexes after the first node of each label or ignore benign errors |

## Time budget

8 percent, about 8 hours. **Cut first if long:** unique constraints, `q11` depth variants beyond depth 2.

## Handoff

Phase 3 can assume: validated queries, `repo.py` writers, pydantic models, `seed.py`, tenants. Tag: `phase-2-complete`.
