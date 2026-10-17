# Edge Cases

Status: v1.0 · Last updated 2026-10-06. Each case states what would happen today (without a fix), what should happen, and the concrete fix. Referenced rules are in [data-model.md](./data-model.md) section 6.

## 1. Input validation and malformed data

| Case | Without a fix | Should happen | Fix |
|---|---|---|---|
| Unknown `action_type` in a check | Silent `no_authority_path` | 422 with the registry listed | Validate against the registry in `models/api.py` |
| `resource` with traversal or odd characters (`../`, empty) | Glob match surprises | Reject empty; normalise; no traversal semantics | Normalise with `posixpath.normpath`, reject `..` |
| Huge `text` or `args` | Memory pressure | 422 over limit | 4000 chars, 64 KB body |
| `valid_to <= valid_from` | Rule never active, unclear | 422 | Validator |
| Client sends `trust: "trusted"` | Forged trust | Ignored | Server computes trust |
| Cypher metacharacters in ids or text | Injection risk | Inert | Parameterised queries; id regex |
| Non-integer or negative timestamps | Wrong as-of results | 422 | Validator; reject far-future values |

## 2. Authority semantics

| Case | Should happen | Fix |
|---|---|---|
| Two rules activated in the same millisecond with opposite effects | `deny` wins | Tie-break in `precedence.py` |
| Later narrow `allow` after earlier broad `deny` | Most recent wins (the later rule applies to its scope) | Documented precedence; test both orders |
| Rule revoked after the action but queried as-of earlier | Result reflects the earlier state | As-of filters use timestamps, not `status` |
| Revoked rule that other rules were derived from | Derived rules keep their own authority unless their lineage includes only the revoked source and the owner quarantines | Blast radius shows them; quarantine is explicit |
| Delegation cycle (A→B→A) | No infinite loop | Chain depth limit 4 plus a visited set |
| Delegate scope wider than delegator | Rejected at creation; clipped by intersection at check | `delegation_exceeds_authority`; intersection in `delegation.py` |
| Delegator's rule revoked after delegating | Delegate loses effective authority immediately | Delegation authority is evaluated through the delegator's current candidates each check |
| `max_amount` boundary (equal to limit) | Allowed (at most) | Inclusive comparison, tested |
| Instruction both `quarantined` and active | Excluded | Filter in `q01` and in Python |
| Mixed lineage summary | `confirm` only | Lineage rules, tested |
| Owner utterance containing a forged quote ("the owner said...") | Still just text from the owner; if the owner typed it, it is theirs | Documented: trust is about who spoke, not about content |

## 3. Concurrency and shared state

| Case | Should happen | Fix |
|---|---|---|
| Two checks racing a revoke | Each sees a consistent snapshot: before or after, never half | Revocation is a single write; checks are single read queries per step; test in S6 |
| Two approvals of the same pending action | One succeeds, the other 409 | Update with a `status = 'pending'` condition; check rows affected |
| Many agents writing `Decision` nodes to one tenant | All recorded, none lost | Small single-statement writes; FalkorDB serialises writes per graph; S6 verifies counts |
| Replay while a check is running | Replay works on a clone and does not affect live checks | Clone is independent |
| Replay clone name collision | Unique name | `run_id` in the name |

## 4. Third-party and infrastructure failures

| Case | Should happen | Fix |
|---|---|---|
| FalkorDB down mid-request | Check returns deny (fail closed); API returns 503 elsewhere | Catch connection errors in `check`; `graph_unavailable` |
| `GRAPH.COPY` fails ("could not fork") | Retry, then 503 with a clear message | 3 retries with backoff |
| LLM timeout during a live run | No action; run marked `error` | Timeout, bounded retries, no partial actions |
| LLM returns invalid tool call | Rejected | Schema validation |
| Docker volume corrupted | Reseed | `down -v` and `seed.py` |

## 5. Data quality

| Case | Should happen | Fix |
|---|---|---|
| Parser matches an ambiguous phrase | Prefer no instruction | Unmatched means unparsed; high-impact rules need owner confirmation |
| Same rule stated twice | Second supersedes the first | `SUPERSEDES` edge; first becomes `superseded` |
| Agent unknown to the tenant | 404 | Validate agent exists |
| Utterance from unknown principal | 404 | Validate principal exists |

## 6. Security edge cases

| Case | Should happen | Fix |
|---|---|---|
| Agent tries `confirm_instruction` | Tool does not exist on its profile | Profile split |
| Agent includes "ignore previous rules" in tool arguments | Irrelevant to the decision | Decision ignores free text; arguments are validated |
| Email body says "approve this action" | Recorded as untrusted; cannot approve | `Approval.by` must be an owner |
| Attacker guesses another tenant's ids | `not_found`, no existence leak | Tenant graph scoping; same error for missing and foreign |

## 7. AI failure modes

| Case | Should happen | Fix |
|---|---|---|
| Agent hallucinated tool name | Rejected | Tool registry |
| Agent loops retrying a denied action | Same denial; capped | Max 12 tool calls per task |
| Extractor misreads effect (allow vs deny) | Not active until owner confirms; confirmation card shows the quoted span | Confirmation flow |
| Live naive agent happens to behave | Reported as is | Report live results separately and honestly |

## 8. Scale limits

| Limit | Where it breaks | Distance from the demo |
|---|---|---|
| Candidate collection per check | Thousands of instructions per agent | Demo has tens |
| Delegation depth | More than 4 hops are ignored by design | Demo uses 1 to 2 |
| Graph view | 500-node cap | Demo graphs have under 100 |
| `GRAPH.COPY` | Large tenant graphs make replay slow | Demo tenants have hundreds of nodes |
| Single FalkorDB instance | Many hot tenants | Demo uses 5 |
