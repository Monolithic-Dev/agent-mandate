# Security and Privacy

Status: v1.0 · Last updated 2026-10-06 · Implements [PRD.md](./PRD.md) section 12. This project is itself a security control, so its own threat model matters.

## 1. Sensitive data in this system

| Data | Why it matters | Handling |
|---|---|---|
| Owner utterances (rules) | They define what agents may do | Stored per tenant graph; no real personal data is used (all synthetic) |
| `Utterance.text` from emails | Could contain real content in a future adapter | Synthetic only now; size-limited; never logged in full |
| Sandbox email, files, refunds | Stand-ins for real systems | In-memory, synthetic |
| `MANDATE_API_KEY`, LLM API key | Control access and spend | `.env` only, never committed |
| Decisions and paths | The audit trail | Append-only in practice (revoked, never deleted) |
| Console users | Who may sign in, with which role | Registry graph; passwords as scrypt hashes (salted, 32 MiB cost); never returned by the API; disabled, never deleted |
| Sessions | A signed-in browser | Registry graph; only the SHA-256 of the cookie's random token is stored |
| Audit events | Who changed what | Registry graph, linked to the user and the tenant; the email tried in a failed sign-in is recorded |

## 2. AuthN and AuthZ

- **REST:** `X-Mandate-Key` header, compared in constant time against every key (so timing does not reveal which matched). The admin key (`MANDATE_API_KEY`) has every role and tenant; extra keys in `MANDATE_API_KEYS` (`id:secret:role:tenants;...`) have a role and a tenant list. Roles: `viewer` (reads), `operator` (viewer plus agent tool calls and checks), `admin` (everything else). One table (`api/keys.py::required_role`) decides what a request needs, and anything not clearly a read or an agent call needs `admin`, so a new route is strict by default. A key aimed at a tenant outside its list gets the same 404 as a missing tenant. Scoped keys only list their own tenants and cannot create tenants. Rate limits are per key. All routes except `/healthz` and `/readyz`; `/metrics` needs a key.
- **Console users:** people sign in with an email and a password (12 to 256 characters, hashed with scrypt). A sign-in creates a `Session` node and sets an HttpOnly, SameSite=Strict, Secure cookie holding a random 256-bit token; only its SHA-256 is stored. Every request looks the session up, so signing out, a password change (other sessions), a reset, disabling the user and "sign out everywhere" end sessions on the server at once, and a copied cookie stops working. Sessions end after `MANDATE_SESSION_IDLE_SECONDS` without a request (default two hours) and after `MANDATE_SESSION_TTL_SECONDS` in any case (default twelve hours). A wrong email and a wrong password get the same answer after the same scrypt work; sign-in is limited to ten attempts per email per minute. Users have the same roles and tenant lists as keys; managing users needs an admin with every tenant, and nobody can change their own role, tenants or status. The first admin is created on the server: `python -m mandate.users add`.
- **Cross-site requests:** with a session cookie, any request that is not GET, HEAD or OPTIONS must carry `X-Mandate-Client: console`. A browser cannot add that header to a cross-site request without a CORS preflight, which the API never grants, so a forged form or fetch is refused (403) even before SameSite applies. Sign-in requires the header too, so another site cannot sign a visitor in to an account it controls.
- **Audit trail:** every change through the API, including refused ones (401 after identifying, 403, 429) and failed sign-ins, becomes an `AuditEvent` in the registry graph, `(User)-[:PERFORMED]->(AuditEvent)-[:CONCERNS]->(Tenant)`, with the request id that also appears in the logs. Writing it happens after the response and never changes it; a failed write is logged and counted (`mandate_audit_write_failures_total`). Agents' tool calls are not duplicated there: each is a Decision with its own explanation. The CLI records its changes as `actor_kind: cli`.
- **Webhooks:** only admins see or change them, and URLs are masked once saved (a Slack URL is a credential); a JSON webhook's signing secret is shown once. To keep the API from being used to reach its own network (server-side request forgery), a webhook URL must be HTTPS and must not resolve to a private, loopback, link-local, multicast or reserved address; this is checked when the webhook is saved and again before every delivery, and redirects are never followed. `MANDATE_WEBHOOK_ALLOW_PRIVATE=true` lifts it for local testing only. A message's approval link is the same single-action, single-owner capability as any approval link, valid for an hour by default; anyone who can read the channel it is sent to can use it, so send it to a channel only the owner reads.
- **MCP agent profile:** bearer token bound to `(tenant_id, agent_id)` and to an expiry, all inside the HMAC signature. The agent cannot pass an identity argument. Tokens last `MANDATE_TOKEN_TTL_SECONDS` (default one day, at most 30 days). Secrets rotate: `MANDATE_TOKEN_SECRETS` lists signing secrets newest first (the first signs, all verify); drop the old one after its longest-lived token has expired. Each token has its own signed id; the owner revokes one token by that id (`revoke_agent_token`, or `POST .../token-revocations`), and the agent server checks the tenant's revocation list on every call, so a leaked token stops working at its next call while the agent's other tokens carry on. Tokens minted before ids existed (`mnd2`) can only be killed by rotating their secret out.
- **MCP admin profile:** separate token and separate mount; never configured into agents.
- **Approval links:** a capability for exactly one held action, one tenant and one approving owner, expiring after 15 minutes by default (a day at most), signed with a key derived from the agent-token secrets under its own label. Using it needs no API key. It is single use in effect: resolving moves the action out of `pending` in one atomic write, so the first use of any link for that action wins and later uses get 409. The console keeps the token in the URL fragment so it never reaches server logs. Anyone holding the link before it is used can act on it, so send it only to the owner, over a channel you trust.
- **Authority itself:** only a principal with `role = owner` can confirm or revoke; the server sets `Utterance.trust`.
- **Production plan:** single sign-on (OIDC) for console users, per-tenant OAuth for agents, signed instruction records, and a retention policy for audit events.
- **Input hardening:** tool arguments are strictly typed (a JSON `true` is not 1, `10.0` is not `10`); every request, tool and domain model rejects NUL characters (the graph database cannot store them); free text is stored as data and never interpreted. An injection corpus (`tests/data/abuse_strings.json`) is thrown at tool arguments, utterances, path ids, the key header and size limits in unit tests and against a real FalkorDB.

## 3. Transport and storage

- Local development uses plain HTTP on localhost. Any non-local deployment must terminate TLS in front of the API.
- FalkorDB is bound to localhost / the Compose network only; it is never published to the internet, and the Compose file does not map port 6379 on non-local hosts.
- No encryption at rest in v1 (synthetic data). Production: encrypted volumes and a managed FalkorDB with auth.

## 4. Secrets management

- `.env` (git-ignored) holds `MANDATE_API_KEY`, `ANTHROPIC_API_KEY`, `FALKORDB_PASSWORD`. `.env.example` lists names with empty values.
- CI uses repository secrets; no secret is echoed in logs (`structlog` processor redacts keys named `*key*`, `*token*`, `*secret*`).
- A pre-commit hook (or CI step) runs a secret scan (`gitleaks`) so a key is never pushed.

## 5. Threat model

| # | Threat | Mitigation | Test |
|---|---|---|---|
| T1 | **Forged instruction** in untrusted content becomes authority | `lineage_trust`; untrusted never activates; extractor runs only on `owner_direct` | S2 variants, `test_untrusted_cannot_activate` |
| T2 | **Agent grants itself authority** by calling an admin tool | MCP profile split; agent profile exposes no authority tools | `test_agent_profile_has_no_admin_tools` |
| T3 | **Agent impersonates another agent or tenant** | Identity bound to the session token; tenant in the token | S5, `test_cross_tenant_isolation` |
| T4 | **Cypher injection** through ids, patterns or text | Parameterised queries only; `graph/client.py` rejects non-file query text; id regex validation | `test_injection_strings_are_inert` |
| T5 | **Lost or stale rule** (revocation not honoured) | Check reads the graph on every call; no caching in v1; as-of queries | S3 |
| T6 | **Mixed-lineage laundering:** a summary mixes owner and untrusted text so a forged rule inherits trust | `mixed` lineage can only yield `confirm`, never `allow` | S2 variants with mixed summary |
| T7 | **Tampering with the audit trail** | Gateway, not the agent, writes `Action` and `Decision`; no delete endpoints for them; production plan adds an external append-only log | `test_no_delete_decision_route` |
| T8 | **Replay clone leaks** (cloned graph persists) | Clone name is unique and always deleted in a `finally` block; startup sweeps stale `__replay_` graphs | `test_replay_cleans_up` |
| T9 | **Denial of service** by floods of checks | Rate limit (600 per minute per key), body size limit, bounded graph view | load test in S6 |
| T10 | **Confused approver:** a non-owner approves a held action | `Approval.by` must be an owner; 422 otherwise | `test_non_owner_cannot_approve` |
| T11 | **Approval link misuse:** a link replayed, pointed at another action, or kept past its use | Tenant, action and approver are signed; expiry; first use wins atomically; the approver must still be an owner | `test_approval_links.py` |
| T12 | **Leaked agent token** used until it expires | Each token has an id; the owner revokes it and the agent server refuses it from its next call | `test_a_revoked_token_is_refused_from_its_next_call` |

## 6. Out of scope (stated honestly)

- Stopping all prompt injection: the system controls what an agent is **authorised** to do, not what the model reads or says.
- Protection if the host, the graph database or the admin key is compromised.
- Cryptographic non-repudiation of instructions (existing projects cover signed delegation chains).
- Real personal data. Do not connect real mailboxes without a separate privacy review.

## 7. Privacy

- All data is synthetic by design. A future real-data version needs: data minimisation (store hashes and short spans, not full bodies), tenant data export and deletion (drop the tenant graph), retention limits on utterance text, and a legal review for the relevant regime (for example India's DPDP Act or GDPR). Erasure-with-receipt was deliberately cut from v1 (PRD non-goals).

## 8. Assumptions
- A single trusted operator runs the system locally; multi-user access control is future work.
