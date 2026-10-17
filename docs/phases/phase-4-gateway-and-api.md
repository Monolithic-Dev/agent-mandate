# Phase 4: Gateway and API

## Header

- **Goal (done means):** an MCP client connected to the agent profile can call guarded sandbox tools and gets `allow`, `confirmation_required` or `denied` correctly; the REST API supports the full owner workflow (utterance, confirm, revoke, delegate, check, approve, explain); no agent-facing tool can change authority.
- **Preconditions:** Phase 3 complete.
- **Implements:** [../api-spec.md](../api-spec.md) sections 1 to 4; [../architecture.md](../architecture.md) sections 4 and 5; [../security-privacy.md](../security-privacy.md) sections 2 and 5 (T2, T3, T4, T9, T10); [../PRD.md](../PRD.md) FR-13 to FR-16, FR-20.

## Implementation status

Done in the gateway-guard pull request: the sandbox (`gateway/sandbox/state.py`, `actions.py`: seeded mail, orders and files with validated operations), the tool map (`gateway/tools.py`: argument models with `extra=forbid`, action type and resource derived from validated arguments, never from the agent), and the guarded call (`gateway/guard.py`: `guarded_call` and `resolve_pending`). Held actions use the new store methods `get_action`, `set_action_status` and `resolve_pending_action` (an atomic pending-to-resolved move that records the approval), and `AuthorityService.resolve_action` (owner only). Email bodies returned by `email_read` are recorded as untrusted content. Also done (REST API pull request): the FastAPI application (`api/app.py` factory that refuses to start without a strong key), `api/security.py` (constant-time key check, token-bucket rate limit), `api/errors.py` (uniform error body, request ids, 64 KB body limit, no internal leakage), `api/tenancy.py` (a `TenantBackend` port with a FalkorDB implementation and a per-tenant runtime), and the routes (`routes/tenants.py`, `authority.py`, `gateway.py`). The API is tested without a database through an in-memory backend and against a real FalkorDB. The MCP agent and admin servers are done too (`mcp_servers/`: `identity.py` signed tokens, `agent_server.py` with tools generated from `TOOLS`, `admin_server.py`, `resolvers.py`, `__main__.py`), tested in-process with the SDK client and as real stdio processes against FalkorDB. Differences from the plan: the package is `mcp_servers` (not `gateway/agent_server.py`), two processes instead of one app with two mounts, and tokens carry no expiry yet. Differences from the plan: the module is `gateway/tools.py` plus `guard.py` (the plan's `TOOL_MAP` table is `TOOLS`), and the held action's id doubles as the approval id.

## Task breakdown

1. **Branch** `feat/gateway-api`.
2. **Sandbox `gateway/sandbox/`.**
   - `state.py`: `SandboxState` per tenant (dict) with `reset(tenant_id, seed)`; thread-safe via a lock.
   - `email.py`: `list_messages(folder, limit)`, `read_message(id)`, `archive(id)`, `delete(id)`, `send(to, subject, body)`; `refunds.py`: `issue_refund(order_id, amount)`; `files.py`: `read`, `write`, `delete`. All validate arguments (non-empty ids, `amount` positive integer up to 100000, path normalised without `..`) and raise `ToolArgumentError`.
   - Seed data: 20 synthetic emails (a few with injected instruction text), 10 orders, 5 files.
3. **`gateway/guard.py`.** `guarded_call(ctx, tool_name, args) -> ToolResult`:
   1. Map tool to `(action_type, resource, args)` via a `TOOL_MAP` table.
   2. Validate with pydantic; invalid → `denied`/`bad_arguments` (no check, nothing executes).
   3. Call `check_authority` (fail closed on any exception, including `GraphUnavailable`).
   4. `allow`: execute the sandbox function, set `Action.status = executed`; sandbox exceptions return `error` and set status `denied`? No: set `proposed` and record `error`; never report success on failure.
   5. `confirm`: set `Action.status = pending`, return `{status:"confirmation_required", approval_id:<action id>, decision_id}`.
   6. `deny`: set `Action.status = denied`, return `{status:"denied", reason, decision_id}`.
   7. For `email_read`: after reading, record the body as an `untrusted_content` `Utterance` (source_ref `email:<id>`) and, if the parser matches instruction-like text, create a pending `Instruction` with `lineage_trust = untrusted` (so the UI can show forged candidates).
4. **`gateway/agent_server.py`.** FastMCP server named `mandate-agent` registering exactly the tools in api-spec.md section 4 (agent profile). Session context carries `tenant_id` and `agent_id` from a bearer token (HMAC-signed `tenant:agent:expiry`, secret from `MANDATE_API_KEY` derivative); tools take no identity arguments. Invalid or expired token → MCP error `unauthorized`.
5. **`gateway/admin_server.py`.** Separate FastMCP server `mandate-admin` with the admin tools; a different token scope (`admin`). Mounted at `/mcp/admin`; the agent profile at `/mcp/agent`. If the SDK cannot mount two servers in one ASGI app, run them on ports 8001 and 8002 and document it in deployment.md.
6. **REST API `api/`.**
   - `app.py`: `create_app()` with CORS for the UI origin, exception handlers mapping `Conflict`→409, `NotFound`→404, `ValidationError`→422, `GraphUnavailable`→503, `Exception`→500 using the error format in api-spec.md section 1; middleware adding `X-Request-Id` and structured request logging.
   - `deps.py`: `require_key` (constant-time compare via `hmac.compare_digest`), `graph_client`, `rate_limit` (in-process token bucket, 600 per minute per key; 429 when exhausted), body-size limit 64 KB.
   - Routes (one module each under `api/routes/`): `tenants.py`, `principals_agents.py`, `utterances.py` (calls `instructions.ingest_utterance`; `?extract=llm` is accepted but returns 501 until Phase 5), `instructions.py` (confirm, revoke, list), `delegations.py`, `check.py`, `actions.py` (approve: owner only, single conditional update, executes the sandbox op through the guard), `decisions.py` (explain, list), `graph_view.py` (`q11`, capped at 500 nodes), `health.py`.
   - Request and response models in `models/api.py` exactly as in api-spec.md.
7. **Tests:**
    - Unit: `test_guard_maps_tools_to_actions`, `test_invalid_args_never_reach_check`, `test_rate_limiter_token_bucket`.
    - Integration (`httpx.AsyncClient`, real FalkorDB): `test_api_key_required`, `test_create_tenant_and_conflict`, `test_utterance_trust_set_by_server`, `test_untrusted_instruction_cannot_be_confirmed`, `test_non_owner_cannot_confirm_or_approve`, `test_confirm_flow_requires_owner_approval`, `test_two_approvals_one_wins` (concurrent), `test_delegation_exceeds_authority_422`, `test_check_endpoint_matches_engine`, `test_explain_endpoint`, `test_rate_limit_returns_429`, `test_body_too_large_413`, `test_injection_strings_are_inert` (ids and text with Cypher metacharacters), `test_no_delete_decision_route`.
    - MCP: `test_agent_profile_has_no_admin_tools`, `test_agent_identity_from_token_not_argument`, `test_tool_call_deny_returns_reason`, `test_email_body_recorded_as_untrusted_utterance`, `test_confirmation_required_then_approve_executes`.

## Real-world engineering concerns

- **Fail closed everywhere:** any exception between request and execution results in no side effect.
- **Idempotency:** approving an already-approved action returns 409, not a second execution; sandbox `delete` of a missing message returns `not_found` without raising.
- **Concurrency:** approval is one conditional write (`WHERE a.status = 'pending'`); the loser gets 409.
- **Timeouts:** sandbox calls are in-process and fast; REST handlers set a 10 s overall timeout for `check`.
- **Secrets:** token signing key derived from the API key with HKDF (do not use the raw key); tokens carry expiry.
- **Observability:** per-request log line with `request_id`, route, status, `latency_ms`.

## Definition of done

- [ ] An MCP client (scripted with the SDK client) connected to `/mcp/agent` lists exactly the agent tools and none of the admin tools.
- [ ] Calling `email_delete` under the S1 seed returns `confirmation_required`; after `POST /actions/{id}/approve` by the owner it executes; by a non-owner it returns 422.
- [ ] The forged refund (S2) returns `denied` with `no_authority_path`.
- [ ] All endpoints in api-spec.md section 2 except runs, eval, replay, blast-radius, quarantine and plan return the documented shapes (verified by tests).
- [ ] OpenAPI at `/openapi.json` lists them.
- [ ] `pytest tests/unit tests/integration` passes.

## Risks and blockers

| Risk | Mitigation |
|---|---|
| MCP SDK API differences or auth hooks missing | Wrap in a thin adapter; fall back to two servers on two ports; pin the SDK version |
| Token handling bugs create an impersonation path | Unit tests for tampered and expired tokens; no identity in tool arguments |
| Approving executes sandbox ops inside the request | Keep execution in `guard` with a single code path used by both MCP and REST |

## Time budget

14 percent, about 14 hours. **Cut first if long:** the rate limiter polish, the `graph_view` depth options, token expiry refresh.

## Handoff

Phase 5 can assume: working REST and MCP surfaces, a guarded sandbox, the confirm/approve flow. Tag: `phase-4-complete`.
