# S6: concurrency

Generated 2026-10-08 07:57 UTC at git `0a31c7f`. Machine: Windows-11-10.0.26200-SP0, 16 logical CPUs; FalkorDB in a local container; the load generator and the API code run in this one Python process (threads), so latency includes contention for the interpreter.

| Variant | Tenants x agents | Checks | Writes | Wrong answers | Errors | Cross-tenant | Audit gaps | p50 ms | p95 ms | Checks/s |
|---|---|---|---|---|---|---|---|---|---|---|
| v1_read_heavy | 5 x 10 | 900 | 100 | 0 | 0 | 0 | 0 | 23.5 | 45.8 | 514 |
| v2_write_heavy | 5 x 10 | 500 | 500 | 0 | 0 | 0 | 0 | 29.6 | 782.7 | 190 |

## Revocation lag

Per revoked rule: the revoke's write window (a check that starts after it must be denied, and is), and the allows that started inside it, where either answer is correct.

| Variant | Revokes | Window p50 ms | Window max ms | Allows inside a window | Latest allow after revoke began, ms |
|---|---|---|---|---|---|
| v1_read_heavy | 15 | 237.8 | 1210.5 | 33 | 1169.9 |
| v2_write_heavy | 15 | 629.9 | 1430.2 | 17 | 683.8 |

## Problems

None.

## Limits

- The oracle is deterministic (what each agent's rules allow) plus a timing window for revokes; it does not cover multi-step races between several writers to one rule.
- One process with threads, one database node. Not a throughput benchmark. All workers start together (a closed loop of 50 clients), so latency is mostly queueing: p50 is roughly 50 clients divided by checks per second.
- An unscored warm-up run precedes the measured ones; without it the first variant's p95 was about 2 seconds (connection and query-plan cold start).
- Writes are duplicate grants and deny rules that cannot change an agent's answer; write conflicts that should change answers are covered by the unit and contract tests.
