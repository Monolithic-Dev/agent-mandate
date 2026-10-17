# Integration Guide

Status: v1.0 (planned interface; nothing here is implemented yet) · Last updated 2026-10-06. How a developer would put Agent Mandate in front of their own agent. The endpoints and tools are specified in [api-spec.md](./api-spec.md); this guide shows the intended workflow.

## 1. The idea in one picture

```
your agent  --MCP (agent profile, bearer token)-->  Agent Mandate gateway  --allowed calls only-->  tools
owner       --REST or admin MCP (admin key)------->  Agent Mandate API       (rules, revocations, approvals)
```
The agent receives only guarded tools and an `explain_decision` tool. It cannot create, confirm, revoke or delegate authority. The owner manages rules through the REST API or the admin profile.

## 2. Steps

1. **Run the stack** (Phase 4 onward): `docker compose up -d --build`.
2. **Create a tenant and agent:**
   - `POST /v1/tenants {"tenant_id":"acme","name":"Acme"}`
   - `POST /v1/tenants/acme/principals {"name":"Dana","role":"owner"}`
   - `POST /v1/tenants/acme/agents {"name":"inbox-agent","kind":"primary"}`
3. **State rules as the owner**, in plain language, through `POST /v1/tenants/acme/utterances` with `channel: "owner_direct"`. Review the proposed instructions and confirm each (`.../instructions/{iid}/confirm`).
4. **Issue an agent token** bound to `(tenant, agent)`: `POST /v1/tenants/acme/agents/{aid}/tokens {"by": owner}` or the admin MCP tool `agent_token`. Keep the returned `token_id`: if the token leaks, revoke just that token with `POST /v1/tenants/acme/token-revocations {"by": owner, "token_id": ...}` and it is refused from its next call. Tokens expire (one day by default); the agent never receives the admin key.
5. **Point the agent at the gateway.** Add an MCP server entry to the agent's configuration. The exact format depends on the client; the shape is usually:
   ```json
   {
     "mcpServers": {
       "mandate": {
         "url": "http://localhost:8000/mcp/agent",
         "headers": {"Authorization": "Bearer <agent token>"}
       }
     }
   }
   ```
   Check your client's documentation for the exact field names (some clients use `type`, `transport` or a command-based launcher). This snippet is illustrative.
6. **Remove the real tools** from the agent so that the gateway is the only route to consequential actions. If the agent can still call the underlying systems directly, the gateway protects nothing.
7. **Handle the three outcomes** in your agent loop:
   - `allowed`: the tool result is returned normally.
   - `confirmation_required` with an `approval_id`: stop and ask the owner. They approve in the console (the tenant page lists what is waiting), through `POST /v1/tenants/acme/actions/{approval_id}/approve`, or through a single-use approval link you send them (`POST .../actions/{approval_id}/approval-link`, opened at `/approve#<token>` on the console, no API key needed).
   - `denied` with a reason code: report the reason; do not retry or work around it.
8. **Ask why:** call `explain_decision(decision_id)` to show the authority path to the user.

## 3. Rules of thumb

- Keep the admin key out of agent environments, containers and prompts.
- Treat everything the agent reads (email, web, tool results) as data. The gateway records such text as untrusted utterances automatically when it passes through `email_read`-style tools; custom tools should report their results the same way (planned helper `record_untrusted_content`).
- Start with a deny-by-default policy and grant narrow rules (`read`, `archive`) before wider ones.
- Revoke by instruction or delegation, not by editing the graph directly.

## 4. Limits to expect

- The sandbox tools are mocks. Real adapters (IMAP, file stores) are post-release work with a separate privacy review ([roadmap.md](./roadmap.md) section 6).
- The system controls what the agent is authorised to do. It does not make the model resistant to manipulation; it limits what manipulation can accomplish.
- A single admin key and local deployment are assumed ([security-privacy.md](./security-privacy.md)).

## 5. Compatibility to verify in Phase 4

- Whether the chosen MCP SDK supports per-session bearer auth and two mounts.
- Whether common agent clients can send the `Authorization` header to an HTTP MCP endpoint, or need a stdio proxy.
